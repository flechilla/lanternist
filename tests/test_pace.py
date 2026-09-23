"""How long a job has left: what each stage is expected to take, and the pace the job keeps."""

from datetime import datetime, timedelta

import pytest

from lanternist import pace
from lanternist.check import CHECKS_AT_ONCE
from lanternist.db import LOCAL
from lanternist.jobs import Progress
from lanternist.pace import Expect, Seen
from lanternist.pipeline import Event, Pipeline


def test_a_stage_not_started_takes_what_its_model_took_before():
    lo, hi, whole = pace.left({"narration": Expect(10, 3.0, basis="history")}, {})
    assert (lo, hi) == pytest.approx((22.5, 42.0))
    assert whole == {"narration": 30.0}


def test_the_pace_this_job_keeps_replaces_the_expectation():
    seen = {"keyframes": Seen(left=10, secs=[16.0, 18.0], elapsed=60.0)}
    lo, hi, whole = pace.left({"keyframes": Expect(12, 30.0, basis="guess")}, seen)
    assert (lo, hi) == pytest.approx((170 * 0.85, 170 * 1.2))
    assert whole == {"keyframes": 230.0}  # a minute run, and ten pictures of 17 s to come


def test_one_item_made_is_not_yet_a_pace():
    seen = {"keyframes": Seen(left=10, secs=[4.0], elapsed=30.0)}
    _, _, whole = pace.left({"keyframes": Expect(11, 20.0, basis="listed")}, seen)
    assert whole == {"keyframes": 230.0}


def test_items_made_at_once_divide_the_time():
    _, _, whole = pace.left({"motion": Expect(37, 5.0, at_once=4, basis="history")}, {})
    assert whole == {"motion": 50.0}  # ten rounds of four


def test_an_item_waiting_in_a_queue_widens_the_range():
    expect = {"motion": Expect(8, 5.0, at_once=4, basis="history")}
    calm = pace.left(expect, {"motion": Seen(left=8, secs=[], elapsed=0.0)})
    queued = pace.left(expect, {"motion": Seen(left=8, secs=[], elapsed=0.0, waiting=True)})
    assert queued[0] == calm[0] and queued[1] == pytest.approx(calm[1] * 2)


def test_the_mix_goes_on_at_the_pace_ffmpeg_has_kept():
    seen = {"mix": Seen(left=1, secs=[], elapsed=12.0, at=0.75)}
    lo, hi, whole = pace.left({"mix": Expect(1, 40.0)}, seen)
    assert whole == {"mix": 16.0}  # three quarters in 12 s: a quarter in 4 more
    assert (lo, hi) == pytest.approx((4 * 0.85, 4 * 1.2))


def test_a_stage_nobody_expected_is_guessed():
    lo, hi, _ = pace.left({}, {"clips": Seen(left=4, secs=[], elapsed=0.0)})
    assert (lo, hi) == pytest.approx((4 * pace.GUESS["clips"] * 0.5, 4 * pace.GUESS["clips"] * 2.0))


def test_the_plan_prices_time_from_the_estimate_and_the_history(fake_cfg, db):
    for secs in (12.0, 16.0, 20.0):
        db.start_run(
            stage="keyframes",
            model_id="local/flux2-klein-9b",
            provider="local",
            status="done",
            wall_seconds=secs,
        )
    estimate = {
        "lines": [
            {
                "stage": "narration",
                "model": "local/qwen3-tts-1.7b",
                "local": True,
                "todo": 4,
                "gpu_seconds": 20.0,
            },
            {
                "stage": "keyframes",
                "model": "local/flux2-klein-9b",
                "local": True,
                "todo": 6,
                "gpu_seconds": 90.0,
            },
            {"stage": "motion", "model": "fal/h3-max-turbo", "local": False, "todo": 2, "gpu_seconds": 0.0},
        ]
    }
    plan = pace.plan(fake_cfg, db, estimate, "render", scenes=4)
    assert plan["narration"] == Expect(4, 5.0, 1, "listed")  # 20 s of GPU for 4 scenes
    assert plan["keyframes"] == Expect(4, 16.0, 1, "history")  # a picture a scene; klein's median here
    assert plan["cast"] == Expect(0, 15.0, 1, "listed")  # counted in the keyframes line, never run here
    assert plan["motion"] == Expect(2, pace.GUESS["motion"], fake_cfg.fal.max_concurrency, "guess")
    assert plan["clips"].items == 4 and plan["mix"].items == 1
    assert "check" not in plan  # no checker set


async def test_the_snapshot_says_how_long_is_left_and_where_the_time_goes(fake_cfg, db, make_story):
    job = db.add_job(LOCAL, None, "render", None, {}, None)
    progress = Progress(db, job.id)
    progress.expect = {"narration": Expect(2, 3.0, basis="history"), "mix": Expect(1, 30.0)}
    await Pipeline(fake_cfg, progress.stage, db=db, job_id=job.id).narrate(make_story(("still", "still")))
    progress.flush()
    snap = progress.snap
    assert "secs" in snap["stages"]["narration"] and "mix" not in snap["stages"]
    lo, hi = snap["eta_s"]
    assert (lo, hi) == (15, 60)  # the mix alone is left: a guess of 30 s
    assert [(p["stage"], p["label"]) for p in snap["phases"]] == [
        ("narration", "Narration"),
        ("mix", "Final mix"),
    ]
    assert 0 < snap["fraction"] < 1


async def test_the_mix_says_how_far_through_the_film_it_is(fake_cfg, make_story):
    events: list[Event] = []
    await Pipeline(fake_cfg, events.append).render(make_story(("still",)))
    at = [e.at for e in events if e.stage == "mix" and e.at is not None]
    assert at and at == sorted(at) and at[-1] == pytest.approx(1.0, abs=0.05)


def test_the_check_expects_one_picture_a_scene(fake_cfg, db):
    cfg = fake_cfg.model_copy(
        update={"defaults": fake_cfg.defaults.model_copy(update={"checker": "openrouter/fake/cheap"})}
    )
    # A cast sheet, two portraits and three scenes, all to draw: the line counts six pictures.
    line = {
        "stage": "keyframes",
        "model": "local/flux2-klein-9b",
        "local": True,
        "todo": 6,
        "gpu_seconds": 90.0,
    }
    plan = pace.plan(cfg, db, {"lines": [line]}, "board", scenes=3)
    assert plan["keyframes"].items == 3
    assert plan["check"] == Expect(3, pace.GUESS["check"], CHECKS_AT_ONCE, "guess")


def test_a_models_history_is_its_finished_runs_newest_first(db):
    t0 = datetime(2026, 9, 22, 12)
    for i, (secs, status) in enumerate(((5.0, "done"), (3600.0, "failed"), (7.0, "done"))):
        db.start_run(
            stage="motion",
            model_id="fal/x",
            provider="fal",
            status=status,
            wall_seconds=secs,
            created_at=t0 + timedelta(minutes=i),
        )
    db.start_run(stage="keyframes", model_id="local/k", provider="local", status="done", gpu_seconds=16.0)
    assert db.step_seconds("motion", "fal/x", 1) == [7.0]
    assert db.step_seconds("motion", "fal/x", 50) == [7.0, 5.0]  # a timed-out request isn't a pace
    assert db.step_seconds("keyframes", "local/k", 50) == [16.0]  # GPU time, when that's all there is
