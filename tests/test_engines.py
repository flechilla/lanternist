"""The engine interface: local engines keep today's step keys; fal engines send exact requests and price them."""

from datetime import date

import pytest

from lanternist import prompts, registry, timing
from lanternist.config import Paths, Settings
from lanternist.engines import catalog
from lanternist.engines.base import Item, keyframe_size
from lanternist.engines.fal_image import FalImage, aspect_ratio
from lanternist.engines.local import LocalQwenTts
from lanternist.pipeline import Board, Narration, Pipeline
from lanternist.providers.fal import FalError
from lanternist.storyboard import CastMember, Line, Scene, Storyboard
from lanternist.voices import Voice


def golden() -> Storyboard:
    return Storyboard(
        title="Golden",
        language="es",
        style="watercolour, no text",
        seed=7,
        cast=[CastMember(id="luna", name="Luna", look="small grey cat")],
        scenes=[
            Scene(
                n=1,
                narration=[Line(text="Luna vivía en el faro. Cada noche miraba el mar.")],
                visual="A lighthouse at dusk",
                motion="waves roll",
                sound="wind",
                cast=["luna"],
                mode="video",
            ),
            Scene(
                n=2,
                narration=[Line(text="Un día llegó una gaviota vieja.")],
                visual="A gull lands",
                cast=["luna"],
                seed=42,
            ),
        ],
    )


def test_local_step_keys_are_unchanged(tmp_path):
    """The keys the pipeline made before the engine interface (computed on main), so a library stays cached."""
    cfg = Settings(paths=Paths(library=tmp_path / "lib", voices=[tmp_path]))
    p, sb = Pipeline(cfg), golden()
    tts = LocalQwenTts(
        cfg,
        registry.get("local/qwen3-tts-1.7b"),
        Voice("demo", tmp_path / "demo.wav", "Hola", "ab" * 32),
        "es",
    )
    assert [it.key for it in p.narration_items(sb, tts)] == [
        "59f230d6dc6a815aa547a50b0152fdf0583f1fd42790880f875dc539e7c575d5",
        "5d6261e2357fade810d7545bf509d88d43007013051df741f9323fe6e60719b4",
    ]
    img = p.image(sb)
    assert p._cast_key(img, sb, prompts.cast_sheet(sb)) == (
        "922654e7748ecc83f2b49e97b79471b2163894993d0b4083a3b35df1eb6b945c"
    )
    cast = "c" * 64 + ".png"
    assert [p._keyframe_key(img, prompts.keyframe(sb, sc), sb.scene_seed(sc), cast) for sc in sb.scenes] == [
        "32ca4d4cd71be93f15a3affcc9114da574230b910a184e31f3327cb717fb2f25",
        "ceb0287acc0a2c2198e028f021b9e09d6ec0e0fa280466cf68b43e9c2c7efe26",
    ]
    assert p._keyframe_key(img, prompts.keyframe(sb, sb.scenes[0]), 8, None) == (
        "4f6e92a861c3f8be5f135ec9fb2a453024064af47748bc3210d6889f26fddf56"
    )
    tl = timing.timeline([12.0, 30.0], 0.45, 0.5, 1.5, 0.8)
    board = Board(
        [Narration("a.wav", 12.0, [], []), Narration("b.wav", 30.0, [], [])],
        "c.png",
        ["k1.png", "k2.png"],
        tl,
    )
    sb.scenes[1].mode = "video"
    assert [it.key for it in p.motion_items(sb, board.timeline, list(board.keyframes), p.video(sb))] == [
        "1219dfec2dc822a08708f82898540b2e8b23198b36bb6a28d27508962f575d5a",
        "6e1cc8dd8a3011f1f7483191002cbfb8fd898d157ecf4a7921d1673aee25535b",
    ]


def test_a_clip_length_a_hair_over_a_whole_second_keeps_its_frames(tmp_path):
    """3.07 + 5.75 s of narration make scene 2's clip 7.000000000000001 s: 177 frames on main, not 169."""
    cfg = Settings(paths=Paths(library=tmp_path / "lib", voices=[tmp_path]))
    sb = golden()
    sb.scenes = [
        Scene(n=i, narration=[Line(text="x")], visual=f"v{i}", cast=["luna"], mode="video") for i in (1, 2, 3)
    ]
    tl = timing.timeline([3.07, 5.75, 5.0], 0.45, 0.5, 1.5, 0.8)
    p = Pipeline(cfg)
    items = p.motion_items(sb, tl, ["k1.png", "k2.png", "k3.png"], p.video(sb))
    assert items[1].key == "c6f0043af794e429f77645ec290dc55b11fdcd7d45f350e5c4cd0d219674f240"


def test_a_story_whose_video_model_left_the_registry_still_opens(client, wait):
    sb = {
        "title": "Gone",
        "models": {"video": "fal/gone-video"},
        "scenes": [{"n": 1, "narration": [{"text": "A few words."}], "visual": "v", "mode": "video"}],
    }
    sid = client.post("/api/stories", json={"storyboard": sb}).json()["story"]["id"]
    wait(client.post(f"/api/stories/{sid}/board").json()["id"])
    story = client.get(f"/api/stories/{sid}")
    assert story.status_code == 200 and story.json()["board"]["scenes"][0]["motion"] is None
    assert client.get(f"/api/stories/{sid}/estimate").status_code == 422


def test_a_picture_model_change_is_a_new_key(cfg):
    p, sb = Pipeline(cfg), golden()
    local = p._cast_key(p.image(sb), sb, "a cast")
    sb.models.image = "fal/nano-banana-pro"
    pro = p._cast_key(p.image(sb), sb, "a cast")
    sb.models.image_quality = "4K"
    assert len({local, pro, p._cast_key(p.image(sb), sb, "a cast")}) == 3


# ------------------------------------------------------------------------------------ fal pictures
def picture(refs=("cast.png",), w=1920, h=1088, seed=9) -> Item:
    return Item(
        "s001", "k1", 1, {"prompt": "a cat", "seed": seed, "width": w, "height": h, "refs": list(refs)}
    )


def fal_image(cfg, model: str, quality=None) -> FalImage:
    eng = catalog.image(cfg, None, model, quality)
    assert isinstance(eng, FalImage)
    return eng


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (
            "fal/flux-2-klein-9b",
            {
                "image_size": {"width": 1920, "height": 1088},
                "seed": 9,
                "num_inference_steps": 4,
                "output_format": "png",
                "enable_safety_checker": True,
            },
        ),
        (
            "fal/nano-banana-pro",
            {
                "aspect_ratio": "16:9",
                "seed": 9,
                "resolution": "2K",
                "output_format": "png",
                "num_images": 1,
                "limit_generations": True,
                "safety_tolerance": "4",
            },
        ),
        (
            "fal/seedream-5-pro",
            {
                "image_size": {"width": 1920, "height": 1088},
                "output_format": "png",
                "num_images": 1,
                "enable_safety_checker": True,
            },
        ),
        (
            "fal/flux-2-max",
            {
                "image_size": {"width": 1920, "height": 1088},
                "seed": 9,
                "output_format": "png",
                "safety_tolerance": "2",
                "enable_safety_checker": True,
            },
        ),
    ],
)
def test_each_picture_family_sends_exactly_this(cfg, model, expected):
    body = fal_image(cfg, model).arguments(picture(), ["https://cdn/cast.png"])
    assert body == {"prompt": "a cat", "image_urls": ["https://cdn/cast.png"], **expected}


def test_a_cast_sheet_goes_to_the_text_to_image_endpoint_square(cfg):
    eng = fal_image(cfg, "fal/nano-banana-2", "1K")
    body = eng.arguments(picture(refs=(), w=1024, h=1024), [])
    assert "image_urls" not in body and body["aspect_ratio"] == "1:1" and body["resolution"] == "1K"
    assert eng.entry.endpoint_for("text_to_image") == "fal-ai/nano-banana-2"
    assert aspect_ratio(1920, 1088) == "16:9"


@pytest.mark.parametrize(
    ("model", "quality", "item", "micros"),
    [
        ("fal/flux-2-klein-9b", None, picture(), 33_979),  # (2.089 MP out + 1 MP in) x $0.011
        ("fal/flux-2-klein-9b", None, picture(refs=(), w=1024, h=1024), 6_291),  # text to image, $0.006/MP
        ("fal/nano-banana-2", None, picture(), 120_000),  # 2K by default
        ("fal/nano-banana-2", "0.5K", picture(), 60_000),
        ("fal/nano-banana-pro", "4K", picture(), 300_000),
        ("fal/seedream-5-pro", None, picture(), 67_500),  # under 1536x1536
        ("fal/seedream-5-pro", None, picture(w=2048, h=2048), 135_000),
        ("fal/flux-2-max", None, picture(), 160_000),  # ceil(3.09) = 4 MP: $0.07 + 3 x $0.03
    ],
)
def test_pictures_are_priced_from_their_list_prices(cfg, model, quality, item, micros):
    assert fal_image(cfg, model, quality).estimate([item]).micros == micros


def test_an_unknown_quality_falls_back_to_the_models_default(cfg):
    assert fal_image(cfg, "fal/nano-banana-pro", "0.5K").quality == "2K"


def test_a_launch_price_ends_on_its_date():
    price = registry.Price.model_validate(
        {
            "unit": "output_second",
            "usd": "0.02",
            "until": "2026-09-30",
            "then": {"unit": "output_second", "usd": "0.04"},
        }
    )
    assert str(price.on(date(2026, 9, 30)).usd) == "0.02" and str(price.on(date(2026, 10, 1)).usd) == "0.04"


# ------------------------------------------------------------------------------------ fal board, end to end
async def test_a_board_on_fal_draws_the_cast_first_and_uploads_it_once(fake_cfg, db, fakes):
    sb = golden()
    sb.models.image = "fal/flux-2-klein-9b"
    events = []
    p = Pipeline(fake_cfg, events.append, db=db, story_id=None)
    cast, keyframes = await p.draw(sb)
    reqs = [fakes.fal.requests[r] for r in fakes.fal.submits]
    assert [r.endpoint for r in reqs] == ["fal-ai/flux-2/klein/9b"] + ["fal-ai/flux-2/klein/9b/edit"] * 2
    assert len(fakes.fal.uploads) == 1  # every keyframe shares one upload of the cast sheet
    assert all(r.arguments["image_urls"] == fakes.fal.uploads for r in reqs[1:])
    assert cast and len(keyframes) == 2
    assert any(e.stage == "cast" and e.status == "done" and e.asset == cast for e in events)
    assert any("generating at fal" in e.message for e in events if e.status == "progress")

    # A second board is all cache hits; a re-roll asks for one picture.
    fakes.fal.submits.clear()
    assert await p.draw(sb) == (cast, keyframes)
    sb.scenes[1].seed = 99
    await p.draw(sb)
    assert len(fakes.fal.submits) == 1


async def test_a_blanked_picture_is_an_error_not_a_black_frame(fake_cfg, db, fakes, monkeypatch):
    sb = golden()
    sb.models.image = "fal/flux-2-klein-9b"
    real = fakes.fal._make

    async def nsfw(req):
        await real(req)
        req.output["has_nsfw_concepts"] = [True]

    monkeypatch.setattr(fakes.fal, "_make", nsfw)
    with pytest.raises(FalError, match="safety check blanked the cast sheet"):
        await Pipeline(fake_cfg, db=db).draw(sb)


def test_the_picture_catalog_prices_every_model(cfg):
    cat = catalog.catalog(cfg, None, "image.keyframe")
    rows = {m["id"]: m for m in cat["models"]}
    assert cat["default"] == "local/flux2-klein-9b" and cat["models"][0]["local"]
    assert rows["local/flux2-klein-9b"]["usd"] is None and rows["local/flux2-klein-9b"]["gpu_seconds"] == 15
    assert rows["fal/nano-banana-pro"]["usd"] == 0.15
    assert [o["usd"] for o in rows["fal/nano-banana-pro"]["quality"]["options"]] == [0.15, 0.15, 0.3]
    assert not rows["fal/nano-banana-pro"]["available"]  # no fal key here
    assert keyframe_size(cfg) == (1920, 1088)


def test_fal_step_keys_are_pinned(tmp_path):
    """A change to what a fal adapter keys on re-makes (and re-bills) every story: bump its version."""
    (tmp_path / "demo.wav").write_bytes(b"RIFF fake")
    cfg = Settings(paths=Paths(library=tmp_path / "lib", voices=[tmp_path]))
    sb = golden()
    sb.scenes = sb.scenes[:1]
    sb.scenes[0].narration = [Line(text="Luna vivía en el faro.")]
    sb.scenes[0].sound = "wind"
    sb.models.image, sb.models.video, sb.models.tts, sb.voice = (
        "fal/flux-2-klein-9b",
        "fal/h3-max-turbo",
        "fal/elevenlabs-v3",
        "Aria",
    )
    p = Pipeline(cfg)
    img = p.image(sb)
    assert (
        p._cast_key(img, sb, "a cast") == "7f5577c05795157a562c9395a593f1ae3cfed5f1c92636f2d2e219be9b0b8b9d"
    )
    assert p._keyframe_key(img, "a picture", 8, "c" * 64 + ".png") == (
        "6c9ba2fa0266073eb676203c111e706d27f1e7833df294b13444cb4b8f5180bb"
    )
    assert p.narration_items(sb, p.tts(sb))[0].key == (
        "03aad02697fdca5a853d873e6cee22891f6a7c589475d592de91ac31f005ef48"
    )
    motion = p.motion_items(sb, timing.timeline([6.0], 0.45, 0.5, 1.5, 0.8), ["k1.png"], p.video(sb))
    assert (motion[0].key, motion[0].params["shots"]) == (
        "b4500d49d597fe9c2943b32ae3d2934cdfef0255644c82a37012b3b760b2542b",
        [7.0],
    )
    ambience = catalog.ambience(cfg, None, "fal/mmaudio-v2")
    assert p.ambience_items(sb, motion, {1: "v" * 64 + ".mp4"}, ambience)[0].key == (
        "9e18612b73d890ada8660debe6cb7a5a5a2d8ccfb9c4ed3bb086ea54829e8683"
    )
