"""Video on fal: the shot planner, each family's request, chained shots, ambience, resume and cancel."""

import asyncio

import pytest

from lanternist import timing
from lanternist.db import StepRun, to_micros
from lanternist.engines import catalog, local
from lanternist.engines.base import Item
from lanternist.engines.fal_video import FalVideo
from lanternist.engines.ffmpeg import probe
from lanternist.estimate import estimate
from lanternist.pipeline import BudgetExceeded, Pipeline
from lanternist.prompts import VIDEO_NEGATIVE
from lanternist.store import step_key

KLING = [float(s) for s in range(3, 16)]


@pytest.mark.parametrize(
    ("seconds", "lengths", "shots", "waste", "hold"),
    [
        (7, KLING, [6], 0, 1),  # a second held on the last frame beats paying for it
        (14, [4, 6, 8], [8, 6], 0, 0),  # Veo: two shots
        (23, KLING, [11, 11], 0, 1),  # past one generation: even shots
        (12, [5, 10, 15], [15], 3, 0),  # Wan: one shot, 3 s paid and trimmed
        (24.5, [8, 15], [8, 8, 8], 0, 0.5),  # three short shots bill less than two long ones
        (2, KLING, [3], 1, 0),  # shorter than the shortest length
    ],
)
def test_the_shot_planner_bills_the_least(seconds, lengths, shots, waste, hold):
    plan = timing.plan_shots(seconds, lengths, hold_max=1.0)
    assert (plan.shots, plan.waste, plan.hold) == (shots, waste, hold)


def video(cfg, model, quality=None) -> FalVideo:
    eng = catalog.video(cfg, None, model, quality)
    assert isinstance(eng, FalVideo)
    return eng


def clip(shots=(6,), seconds=6.0) -> Item:
    return Item(
        "s002",
        "m2",
        2,
        {"prompt": "a cat", "seed": 9, "keyframe": "k.png", "shots": list(shots), "seconds": seconds},
    )


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (
            "fal/h3-max-turbo",
            {
                "image_url": "U",
                "duration": 6,
                "seed": 10,
                "resolution": "768P",
                "prompt_expansion_mode": "balanced",
                "enable_safety_checker": True,
            },
        ),
        (
            "fal/h3-max",  # sends our prompt as is: only Turbo was compared with MiniMax's rewrite
            {
                "image_url": "U",
                "duration": 6,
                "seed": 10,
                "resolution": "768P",
                "prompt_expansion_mode": "disabled",
                "enable_safety_checker": True,
            },
        ),
        (
            "fal/kling-v3-pro",
            {
                "start_image_url": "U",
                "duration": "6",
                "negative_prompt": VIDEO_NEGATIVE,
                "generate_audio": False,
                "cfg_scale": 0.5,
            },
        ),
        (
            "fal/veo-3.1",
            {
                "image_url": "U",
                "duration": "6s",
                "negative_prompt": VIDEO_NEGATIVE,
                "seed": 10,
                "resolution": "1080p",
                "generate_audio": False,
                "aspect_ratio": "16:9",
                "auto_fix": False,
            },
        ),
        (
            "fal/wan-2.6-flash",
            {
                "image_url": "U",
                "duration": "6",
                "negative_prompt": VIDEO_NEGATIVE,
                "seed": 10,
                "resolution": "720p",
                "enable_prompt_expansion": False,
                "generate_audio": False,
                "multi_shots": False,
            },
        ),
        (
            "fal/wan-3.0",
            {
                "start_image_url": "U",
                "duration": 6,
                "resolution": "720p",
                "audio": True,
                "aspect_ratio": "16:9",
                "enable_prompt_expansion": False,
                "enable_thinking": False,
                "enable_safety_checker": True,
            },
        ),
        (
            "fal/ltx-2.5-fast",
            {
                "image_url": "U",
                "duration": 6,
                "resolution": "720p",
                "aspect_ratio": "16:9",
                "fps": 24,
                "generate_audio": True,
            },
        ),
    ],
)
def test_each_video_family_sends_exactly_this(cfg, model, expected):
    # Shot 1 of a chain: the seed moves on by one, as local LTX's do.
    assert video(cfg, model).arguments(clip(), 1, 6.0, "U") == {"prompt": "a cat", **expected}


@pytest.mark.parametrize(
    ("model", "quality", "shots", "seconds", "micros", "waste"),
    [
        ("fal/h3-max-turbo", None, [6], 6.0, 120_000, 0),  # 768P at the launch price, $0.02/s
        ("fal/h3-max-turbo", "480P", [5], 4.2, 62_500, 0.8),  # the cheapest test: $0.0125/s
        ("fal/h3-max", "1080P", [11, 11], 22.4, 1_760_000, 0),
        ("fal/kling-v3-standard", None, [6], 7.0, 504_000, 0),
        ("fal/veo-3.1", "4k", [8, 6], 14.0, 5_600_000, 0),
        ("fal/wan-2.6-flash", None, [15], 12.0, 375_000, 3.0),
    ],
)
def test_video_is_priced_per_second_billed(cfg, model, quality, shots, seconds, micros, waste):
    est = video(cfg, model, quality).estimate([clip(shots, seconds)])
    assert (est.micros, est.waste_seconds, est.paid_seconds) == (micros, waste, sum(shots))


# ------------------------------------------------------------------------------------ a render on fal
def endpoints(fakes) -> list[str]:
    return [fakes.fal.requests[r].endpoint for r in fakes.fal.submits]


async def test_a_hybrid_film_on_kling_with_ambience(fake_cfg, db, fakes, story_row, make_story):
    sb = make_story(("still", "video", "video"))
    sb.models.video = "fal/kling-v3-standard"
    for sc in sb.scenes:
        sc.sound = "soft wind over the sea"
    sb.scenes[2].sound = ""  # no sound line: that scene stays silent
    p = Pipeline(fake_cfg, db=db, story_id=story_row)
    before = {line["stage"]: line for line in estimate(p, sb, "render")["lines"]}
    assert before["motion"]["todo"] == 2 and before["motion"]["cost_micros"] > 0
    assert before["ambience"]["todo"] == 1

    film = await p.render(sb)
    kling = [e for e in endpoints(fakes) if "kling" in e]
    assert len(kling) == 2 and endpoints(fakes).count("fal-ai/mmaudio-v2") == 1
    assert probe(p.store.path(film.film))["has_audio"]
    assert estimate(p, sb, "render")["total_micros"] == 0  # all of it is cached now
    with db.session() as s:
        runs = s.query(StepRun).filter(StepRun.provider == "fal").all()
    assert {r.stage for r in runs} == {"motion", "ambience"} and all(r.status == "done" for r in runs)


def test_the_page_is_told_what_each_scene_cost_to_animate(client, wait, fakes, make_story):
    sb = make_story(("still", "video"))
    sb.models.video, sb.models.ambience = "fal/kling-v3-standard", "none"
    sid = client.post("/api/stories", json={"storyboard": sb.model_dump()}).json()["story"]["id"]
    progress = wait(client.post(f"/api/stories/{sid}/render").json()["id"])["progress"]
    assert progress["scenes"]["2"]["motion"]["cost_usd"] == 0.504  # 6 s of Kling at $0.084
    assert progress["stages"]["motion"]["spent_usd"] == progress["spent_usd"] == 0.504
    assert "cost_usd" not in progress["scenes"]["2"]["narration"]  # made on this machine


async def test_a_long_slot_is_two_chained_shots(fake_cfg, db, fakes, make_story):
    sb = make_story(("video",))
    sb.models.video, sb.models.ambience = "fal/kling-v3-standard", "none"
    sb.scenes[0].narration[0].text = " ".join(["Many words to say for a long while here."] * 8)
    p = Pipeline(fake_cfg, db=db)
    board = await p.board(sb)
    assert board.timeline.clip_length(0) > 16
    await p.motion(sb, board)
    shots = [fakes.fal.requests[r] for r in fakes.fal.submits if "kling" in fakes.fal.requests[r].endpoint]
    assert len(shots) == 2
    # The second shot starts from the first one's last frame, a picture of its own on fal.
    assert shots[0].arguments["start_image_url"] != shots[1].arguments["start_image_url"]
    assert len(fakes.fal.uploads) == 2


async def test_a_new_take_animates_one_scene_again(fake_cfg, db, fakes, make_story):
    sb = make_story(("video", "video"))
    sb.models.video, sb.models.ambience = "fal/h3-max-turbo", "none"
    p = Pipeline(fake_cfg, db=db)
    await p.render(sb)
    fakes.fal.submits.clear()
    sb.scenes[1].video_seed = 12345
    await p.render(sb)
    assert endpoints(fakes) == ["minimax/h3-max-turbo/image-to-video"]
    assert fakes.fal.requests[fakes.fal.submits[0]].arguments["seed"] == 12345


async def test_the_prompt_h3_rewrote_is_kept_without_keys(fake_cfg, db, fakes, make_story, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "fal-secret-5678")
    sb = make_story(("video",))
    sb.models.video, sb.models.ambience = "fal/h3-max-turbo", "none"
    sb.scenes[0].visual = "a note reading fal-secret-5678"
    p = Pipeline(fake_cfg, db=db)
    board = await p.board(sb)
    await p.motion(sb, board)
    [item] = p.motion_items(sb, board.timeline, list(board.keyframes), p.video(sb))
    rec = p.store.get_step(step_key("shot", motion=item.key, index=0))
    assert rec is not None
    assert rec["meta"]["expanded_prompt"].startswith("Shot: a note reading <fal key …5678>")


async def test_a_full_video_story_stops_before_the_video_stage_over_budget(
    fake_cfg, db, fakes, story_row, make_story
):
    sb = make_story(("video", "video", "video"))
    sb.models.video = "fal/kling-v3-pro"
    p = Pipeline(fake_cfg, db=db, story_id=story_row, budget_micros=to_micros("1"))
    with pytest.raises(BudgetExceeded, match="Animation would cost about") as e:
        await p.render(sb)
    assert e.value.stage == "motion" and e.value.short > 0 and not fakes.fal.submits
    p.budget_micros = to_micros("10")
    await p.render(sb)  # carries on: narration and pictures come from the cache
    assert all("kling" in e or "mmaudio" in e for e in endpoints(fakes))


# ------------------------------------------------------------------------------------ restarts and cancels
async def _start_motion(p: Pipeline, sb, fakes, db, until) -> asyncio.Task:
    """Animation under way: both scenes' requests submitted, and fal still working on them."""
    board = await p.board(sb)
    fakes.fal.polls_before_done = 10_000  # the requests stay in progress until the test lets them go
    task = asyncio.create_task(p.motion(sb, board))

    def running() -> bool:
        with db.session() as s:
            return s.query(StepRun).filter(StepRun.status == "running").count() == 2

    await until(running)
    return task


async def test_a_restart_polls_the_running_requests_instead_of_paying_again(
    fake_cfg, db, fakes, make_story, until
):
    sb = make_story(("video", "video"))
    sb.models.video, sb.models.ambience = "fal/h3-max-turbo", "none"
    task = await _start_motion(Pipeline(fake_cfg, db=db), sb, fakes, db, until)
    task.cancel()  # the server stopping: not the user's cancel
    with pytest.raises(asyncio.CancelledError):
        await task
    submitted = len(fakes.fal.submits)
    assert submitted == 2 and not fakes.fal.cancels

    fakes.fal.polls_before_done = 2
    for req in fakes.fal.requests.values():
        req.polls = 0
    await Pipeline(fake_cfg, db=db).motion(sb, await Pipeline(fake_cfg, db=db).board(sb))
    assert len(fakes.fal.submits) == submitted  # the same two requests, picked up again


async def test_the_users_cancel_cancels_the_requests_at_fal(fake_cfg, db, fakes, make_story, until):
    sb = make_story(("video", "video"))
    sb.models.video, sb.models.ambience = "fal/h3-max-turbo", "none"
    cancelled = False
    task = await _start_motion(
        Pipeline(fake_cfg, db=db, user_cancelled=lambda: cancelled), sb, fakes, db, until
    )
    cancelled = True
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sorted(fakes.fal.cancels) == sorted(fakes.fal.submits)
    with db.session() as s:
        assert {r.status for r in s.query(StepRun).filter(StepRun.provider == "fal")} == {"cancelled"}


async def test_a_film_with_every_stage_remote_never_takes_the_gpu(
    fake_cfg, db, fakes, make_story, monkeypatch
):
    """Definition of done, step 7: no lease, so neither Ollama nor ComfyUI is touched."""

    def no_lease(*args):
        raise AssertionError(f"the GPU lease was taken: {args[1:]}")

    monkeypatch.setattr(local, "lease", no_lease)
    sb = make_story(("still", "video"))
    sb.models.tts, sb.voice = "fal/elevenlabs-v3", "Aria"
    sb.models.image, sb.models.video = "fal/flux-2-klein-9b", "fal/kling-v3-standard"
    sb.scenes[1].sound = "rain on a tin roof"
    film = await Pipeline(fake_cfg, db=db).render(sb)
    assert film.film and {"elevenlabs", "klein", "kling", "mmaudio"} <= {
        part for e in endpoints(fakes) for part in ("elevenlabs", "klein", "kling", "mmaudio") if part in e
    }


def test_mmaudio_hears_the_clip_and_its_sound_line(cfg):
    eng = catalog.ambience(cfg, None, "fal/mmaudio-v2")
    item = Item(
        "s002", "a2", 2, {"video": "v.mp4", "prompt": "rain on a tin roof", "seed": 70000, "seconds": 45.0}
    )
    assert eng.arguments(item, "https://cdn/clip.mp4") == {
        "video_url": "https://cdn/clip.mp4",
        "prompt": "rain on a tin roof",
        "negative_prompt": "speech, talking, voices, singing, music",
        "seed": 70000 % 65536,
        "duration": 30.0,  # the most it scores; the rest of a longer clip goes quiet
        "num_steps": 25,
        "cfg_strength": 4.5,
        "mask_away_clip": False,
    }
    assert eng.estimate([item]).micros == 30_000  # 30 s at $0.001
    item.params["seconds"] = 12.5
    assert eng.estimate([item]).micros == 12_500
