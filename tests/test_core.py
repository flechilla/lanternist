from pathlib import Path

import pytest

from lanternist import prompts, text, timing
from lanternist.config import Render
from lanternist.engines import ffmpeg
from lanternist.engines.worker import MARK, WORKERS
from lanternist.importers.prototype import import_story
from lanternist.store import step_key
from lanternist.storyboard import CastMember, Line, Place, Scene, Storyboard
from lanternist.writer import (
    Brief,
    WriterBoard,
    WriterScene,
    WriterShot,
    _parse_story,
    ambience_only,
    assemble,
    inline_schema,
    split_shots,
)

PROTO = Path.home() / "ai" / "bedtime-stories" / "stories"


def board(**kw) -> Storyboard:
    return Storyboard(
        title="Luna",
        language="es",
        style="watercolour, no text",
        cast=[
            CastMember(id="luna", name="Luna", look="small grey cat, white patch on nose."),
            CastMember(id="tomas", name="Tomás", look="big old white gull"),
        ],
        scenes=[
            Scene(
                n=1,
                narration=[Line(text="Luna vivía en el faro.")],
                visual="Wide shot of a lighthouse.",
                motion="waves roll",
                sound="wind",
                cast=["luna"],
            )
        ],
        **kw,
    )


def test_timeline_slots_and_handles():
    tl = timing.timeline([10.0, 5.0, 8.0], gap=0.5, lead_in=0.5, tail=1.5, xfade=0.8)
    assert tl.speech_starts == [0.5, 11.0, 16.5]
    assert tl.bounds == [0.0, 11.0, 16.5, 26.0]
    assert tl.total == 26.0
    # Each clip meets the next one half a crossfade into it, and they tile the film.
    assert tl.clip_length(0) == pytest.approx(11.4)
    assert tl.clip_start(1) == pytest.approx(10.6)
    assert tl.clip_length(1) == pytest.approx(6.3)
    assert tl.clip_start(2) + tl.clip_length(2) == pytest.approx(tl.total)


def test_single_scene_has_no_handles():
    tl = timing.timeline([4.0], gap=0.5, lead_in=0.5, tail=1.5, xfade=0.8)
    assert tl.clip_length(0) == tl.total == 6.0


def test_ltx_frames_and_shots():
    assert timing.ltx_frames(10.0, 24) == 241
    assert (timing.ltx_frames(10.01, 24) - 1) % 8 == 0
    assert timing.shot_lengths(12, 20) == [12]
    assert timing.shot_lengths(30, 20) == [15, 15]
    assert all(s <= 19.5 for s in timing.shot_lengths(58, 20))


def test_cues_follow_chunk_durations():
    cs = timing.cues([["Hola. Adiós."]], [[3.0]], [1.0], chunk_gap=0.25)
    assert cs[0].start == 1.0 and cs[-1].end == pytest.approx(4.0)
    assert "-->" in timing.srt(cs) and timing.vtt(cs).startswith("WEBVTT")


def test_sentences_split_cjk_and_latin():
    assert text.sentences("Hola. ¿Qué tal? Bien!") == ["Hola.", "¿Qué tal?", "Bien!"]
    assert text.sentences("你好。我很好！") == ["你好。", "我很好！"]
    chunks = text.pack(" ".join(["Una frase corta."] * 40), 350)
    assert all(len(c) <= 350 for c in chunks) and len(chunks) > 1


def test_tts_normalisation_keeps_non_english_quotes():
    assert "«" in text.normalize_for_tts("«Hola»", "es")
    assert "“" not in text.normalize_for_tts("“Hi”", "en")


def test_prompts_restate_cast_and_style():
    sb = board()
    kf = prompts.keyframe(sb, sb.scenes[0])
    assert kf == (
        "Wide shot of a lighthouse. Characters: Luna, small grey cat, white patch on nose, "
        "watercolour, no text"
    )
    v = prompts.video(sb, sb.scenes[0])
    assert v.endswith(prompts.VIDEO_SUFFIX) and "waves roll" in v and "wind" in v
    sheet = prompts.cast_sheet(sb)
    assert "2 characters" in sheet and "First, small grey cat" in sheet and sheet.endswith("no text")


def test_objects_and_places_are_locked_like_characters():
    sb = board()
    sb.cast.append(CastMember(id="kite", name="Poppy", look="red diamond kite, yellow bows.", kind="object"))
    sb.places = [Place(id="faro", name="el faro", look="white stone lighthouse, red lamp room.")]
    sc = sb.scenes[0].model_copy(update={"cast": ["luna", "kite"], "place": "faro"})
    assert prompts.scene_picture(sb, sc) == (
        "Wide shot of a lighthouse. Characters: Luna, small grey cat, white patch on nose. "
        "Objects: Poppy, red diamond kite, yellow bows. Setting: white stone lighthouse, red lamp room"
    )
    assert "Luna (image 1), small grey cat" in prompts.keyframe(sb, sc, numbered=True)
    # The cast sheet holds the characters; an object is locked by its look alone.
    assert "2 characters" in prompts.cast_sheet(sb) and "kite" not in prompts.cast_sheet(sb)
    assert "show only the second from the left: big old white gull" in prompts.portrait(sb, sb.cast[1])


def test_step_key_changes_with_inputs():
    assert step_key("a", x=1) == step_key("a", x=1)
    assert step_key("a", x=1) != step_key("a", x=2)
    assert step_key("a", x=1) != step_key("b", x=1)


def test_camera_expressions():
    assert ffmpeg.resolve_camera("auto", 0) == "push_in"
    assert ffmpeg.resolve_camera("auto", 1) == "pull_out"
    z, x, _ = ffmpeg.camera_expr("pan_left", 100)
    assert z == "1.1" and "on/99" in x


def test_a_paragraph_cuts_between_its_shots():
    # Scene 2 is another shot of scene 1's paragraph: the short pause, and a cut on its first word.
    tl = timing.timeline(
        [10.0, 5.0, 8.0],
        gap=0.5,
        lead_in=0.5,
        tail=1.5,
        xfade=0.8,
        continues=[False, True, False],
        shot_gap=0.25,
    )
    assert tl.speech_starts == [0.5, 10.75, 16.25] and tl.cuts == [1]
    assert tl.clip_length(0) == pytest.approx(10.75)  # no handle into a cut
    assert tl.clip_start(1) == pytest.approx(10.75) and tl.clip_length(1) == pytest.approx(5.9)
    assert tl.clip_start(2) + tl.clip_length(2) == pytest.approx(tl.total)
    g = ffmpeg.mix_graph(tl, Render(), None)
    assert "xfade=transition=fade:duration=0.0:offset=10.750[x1]" in g
    assert "xfade=transition=fade:duration=0.8:offset=15.850[x2]" in g
    # Without continuing shots, nothing moves.
    assert timing.timeline([10.0, 5.0], 0.5, 0.5, 1.5, 0.8, [False, False], 0.25) == timing.timeline(
        [10.0, 5.0], gap=0.5, lead_in=0.5, tail=1.5, xfade=0.8
    )


def test_every_scene_sound_sits_the_same_distance_under_the_voice():
    # Clips at -17, -30 and -48 LUFS against narration at -25: lowered, raised, and raised at most MAX_LIFT.
    assert ffmpeg.ambience_gains([-17.0, -30.0, -48.0, ffmpeg.SILENT], [-25.0, -25.0]) == [
        -8.0,
        5.0,
        12.0,
        0.0,
    ]
    assert ffmpeg.ambience_gains([-20.0], [ffmpeg.SILENT]) == [0.0]
    g = ffmpeg.mix_graph(timing.timeline([4.0], 0.5, 0.5, 1.5, 0.8), Render(), None, gains=[-8.0])
    assert "[0:a]volume=-8.0dB,adelay=delays=0:all=1[a0]" in g
    assert (
        "loudnorm=I=-16.0:TP=-1.5:LRA=11:print_format=json" in g
    )  # measuring, until it's told what it measured


def test_mix_graph_offsets():
    tl = timing.timeline([10.0, 5.0], gap=0.5, lead_in=0.5, tail=1.5, xfade=0.8)
    g = ffmpeg.mix_graph(tl, Render(), None)
    assert "xfade=transition=fade:duration=0.8:offset=10.600" in g
    assert "adelay=delays=10600:all=1" in g  # clip 2's ambience starts with its clip
    assert "adelay=delays=11000:all=1" in g  # scene 2's narration starts at its boundary


@pytest.mark.skipif(not (PROTO / "maya-and-the-mountain.txt").is_file(), reason="prototype not present")
def test_import_prototype_maya():
    sb = import_story(PROTO / "maya-and-the-mountain.txt", mode="video")
    assert sb.title == "Maya and the Mountain"
    assert len(sb.scenes) == 12 and all(s.mode == "video" for s in sb.scenes)
    assert sb.style.startswith("3D animated feature film still")
    assert sb.cast_sheet_prompt.startswith("A 3D animated film character sheet")
    # The prototype's keyframe prompt is prompt + ", " + STYLE.
    assert prompts.keyframe(sb, sb.scenes[0]).endswith(", " + sb.style)


def test_writer_parse_and_assemble():
    title, paras = _parse_story(
        "**TÍTULO: Luna y el faro**\n\nPrimer párrafo con palabras.\n\nSegundo párrafo aquí."
    )
    assert title == "Luna y el faro" and len(paras) == 2
    assert _parse_story("Luna y el faro\n\nPrimer párrafo con palabras.")[0] == "Luna y el faro"
    untitled = _parse_story("Bip stood in the corner of the shop. He was shy.\n\nThen a box fell down.")
    assert untitled[0] is None and len(untitled[1]) == 2
    shot = {"sentences": 1, "visual": "v", "motion": "m", "sound": "s", "place": "", "camera": "static"}
    wb = WriterBoard.model_validate(
        {
            "title": "Luna",
            "cast": [
                {"id": "Luna", "name": "Luna", "look": "grey cat", "kind": "character"},
                {"id": "lamp", "name": "the lamp", "look": "brass lamp", "kind": "object"},
            ],
            "places": [{"id": "Faro", "name": "el faro", "look": "white tower"}],
            "scenes": [
                {
                    "n": i,
                    "shots": [shot | {"cast": ["luna", "nobody"], "place": "faro", "key_moment": i == 2}],
                }
                for i in (1, 2)
            ],
        }
    )
    sb = assemble(Brief(idea="x", language="es", mode="hybrid"), title, paras, wb)
    assert [s.mode for s in sb.scenes] == ["still", "video"]
    assert sb.scenes[0].cast == ["luna"] and sb.cast[0].id == "luna"
    assert [c.kind for c in sb.cast] == ["character", "object"] and [c.id for c in sb.characters] == ["luna"]
    assert sb.places[0].id == "faro" and sb.scenes[0].place == "faro" and sb.portraits
    schema = inline_schema(WriterBoard)
    assert "$ref" not in str(schema) and "title" in schema["properties"] and "title" in schema["required"]
    # Hybrid caps video at ~30% of shots, spread over the marked key moments.
    many = WriterBoard.model_validate(
        {
            "title": "t",
            "cast": [],
            "places": [],
            "scenes": [{"n": i, "shots": [shot | {"cast": [], "key_moment": True}]} for i in range(1, 11)],
        }
    )
    sb = assemble(Brief(idea="x", mode="hybrid"), "t", [f"p {i} words here" for i in range(10)], many)
    assert sum(s.mode == "video" for s in sb.scenes) == 3


def test_paragraphs_split_into_shots_on_sentence_boundaries():
    paragraph = (
        "The wind came to the seaside town on Saturday, tugging at hats and washing lines. "
        "Mira held her brand new red kite tightly. Her little brother Sam carried the ball of string."
    )
    first = {"visual": "wide", "motion": "m", "sound": "s", "cast": [], "place": "", "camera": "auto"}
    shots = [
        WriterShot.model_validate(first | {"sentences": 1, "key_moment": False}),
        WriterShot.model_validate(first | {"sentences": 2, "visual": "close", "key_moment": True}),
    ]
    board = WriterBoard(title="t", cast=[], places=[], scenes=[WriterScene(n=1, shots=shots)])
    sb = assemble(Brief(idea="x", mode="hybrid"), "t", [paragraph], board)
    assert [s.text for s in sb.scenes] == [
        "The wind came to the seaside town on Saturday, tugging at hats and washing lines.",
        "Mira held her brand new red kite tightly. Her little brother Sam carried the ball of string.",
    ]
    assert [(s.n, s.continues, s.visual, s.mode) for s in sb.scenes] == [
        (1, False, "wide", "still"),
        (2, True, "close", "video"),
    ]
    # Counts that don't add up are mended: the last shot takes what's left, and a shot too short
    # to hold a picture joins the one before.
    assert [w for w, _ in split_shots(paragraph, [shots[0], shots[0], shots[0], shots[0]])] == [
        "The wind came to the seaside town on Saturday, tugging at hats and washing lines.",
        "Mira held her brand new red kite tightly.",
        "Her little brother Sam carried the ball of string.",
    ]
    three = shots[1].model_copy(update={"sentences": 3})
    assert [w for w, _ in split_shots(paragraph, [three, three])] == [paragraph]
    assert [w for w, _ in split_shots("Oh no! The kite flew off over the harbour wall.", shots)] == [
        "Oh no! The kite flew off over the harbour wall."
    ]


def test_ambience_only_drops_voices_and_music():
    assert (
        ambience_only("Gentle ocean waves, a soft, warm voice (implied), the wind")
        == "Gentle ocean waves, the wind"
    )
    assert ambience_only("A gentle, melodic chime sound") == "soft room tone"
    assert ambience_only("wind over water, distant waves") == "wind over water, distant waves"


def test_every_worker_speaks_the_runners_protocol():
    """Workers run in other venvs and can't import lanternist, so each restates the marker. This keeps them in step."""
    scripts = sorted(WORKERS.glob("*.py"))
    assert scripts
    for script in scripts:
        assert f'"{MARK}"' in script.read_text(encoding="utf-8"), (
            f"{script.name} doesn't prefix its events with {MARK!r}"
        )
