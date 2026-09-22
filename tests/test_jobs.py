"""The job queue: one job at a time, and nothing a user does to a story stops the queue."""

import asyncio
import time

from lanternist import jobs
from lanternist.cli import _printer
from lanternist.config import Settings
from lanternist.db import Job, Story
from lanternist.jobs import THROTTLE, Progress, Runner
from lanternist.pipeline import ITEM, Event, Pipeline
from lanternist.storyboard import CastMember


async def test_deleting_a_story_while_its_job_runs_keeps_the_queue_going(cfg, db):
    with db.session() as s:
        s.add(Story(id="s1", slug="a", title="A", version=0))
        s.commit()
    runner = Runner(cfg, db)
    job = runner.enqueue("s1", "board", 1)

    async def delete_the_story(job, progress):  # what DELETE /api/stories does meanwhile
        with db.session() as s:
            s.query(Job).filter_by(story_id="s1").delete()
            s.delete(s.get(Story, "s1"))
            s.commit()
        return {}

    runner.execute = delete_the_story
    await runner.run(job.id)  # raised AttributeError on the missing row, which ended the queue's loop
    with db.session() as s:
        assert s.query(Job).count() == 0
    assert runner.current is None


def written(db, job_id: str) -> dict:
    """The snapshot as the job row holds it: what the page gets."""
    with db.session() as s:
        return s.get(Job, job_id).progress


async def test_the_snapshot_follows_every_scene_and_portrait_to_done(fake_cfg, db, make_story):
    sb = make_story(("still", "video"))
    sb.cast.append(CastMember(id="bo", name="Bo", look="boy in a blue cap"))
    sb.portraits = True
    job = db.add_job(None, "board", None, {}, None)
    progress = Progress(db, job.id)
    seen: dict[tuple[str, str], list[str]] = {}

    def follow(e: Event) -> None:
        progress.stage(e)
        whose = e.who if e.who is not None else str(e.scene)
        if e.status in ITEM and whose != "None":
            seen.setdefault((e.stage, whose), []).append(e.status)

    await Pipeline(fake_cfg, follow, db=db, job_id=job.id).board(sb)
    snap = progress.snap
    assert seen[("keyframes", "1")] == ["queued", "working", "done"]
    assert seen[("portraits", "bo")] == ["queued", "working", "done"]
    for n in ("1", "2"):
        for row in ("narration", "keyframes"):
            step = snap["scenes"][n][row]
            assert step["state"] == "done" and step["asset"] and step["tries"] == 1 and "secs" in step
    assert {who: step["state"] for who, step in snap["cast"].items()} == {"a": "done", "bo": "done"}
    assert snap["stages"]["keyframes"]["doing"] == "Painting the scenes"
    assert "asset" not in snap["stages"]["portraits"]  # each portrait under its character, not the row

    # Everything is made now: the next board shows each step as it was, from the cache.
    again = Progress(db, job.id)
    await Pipeline(fake_cfg, again.stage, db=db, job_id=job.id).board(sb)
    assert again.snap["scenes"]["2"]["keyframes"] == {
        "state": "cached",
        "asset": snap["scenes"]["2"]["keyframes"]["asset"],
    }
    assert {step["state"] for step in again.snap["cast"].values()} == {"cached"}


async def test_the_last_of_a_burst_of_events_is_written(cfg, db):
    job = db.add_job(None, "board", None, {}, None)
    progress = Progress(db, job.id)
    progress.stage(Event("keyframes", "start", done=0, total=2))
    progress.stage(Event("keyframes", "queued", scene=1))
    progress.stage(Event("keyframes", "working", scene=1))
    assert written(db, job.id)["scenes"] == {}  # within the throttle of the start: not written yet
    await asyncio.sleep(THROTTLE + 0.1)
    assert written(db, job.id)["scenes"]["1"]["keyframes"]["state"] == "working"


async def test_a_step_waiting_at_a_provider_says_how_many_are_ahead(cfg, db):
    job = db.add_job(None, "render", None, {}, None)
    progress = Progress(db, job.id)
    progress.stage(Event("motion", "waiting", scene=4, ahead=2))
    assert progress.snap["scenes"]["4"]["motion"] == {"state": "waiting", "ahead": 2}
    progress.stage(Event("motion", "working", scene=4))
    assert progress.snap["scenes"]["4"]["motion"] == {"state": "working"}


async def test_the_snapshot_shows_what_each_paid_step_cost(cfg, db):
    job = db.add_job(None, "render", None, {}, None)
    for scene, micros in ((2, 75_000), (2, 25_000), (3, 100_000)):
        db.start_run(
            job_id=job.id, scene=scene, stage="motion", model_id="fal/x", provider="fal", cost_micros=micros
        )
    db.start_run(job_id=job.id, stage="keyframes", model_id="local/x", provider="local", gpu_seconds=16)
    progress = Progress(db, job.id)
    progress.stage(Event("motion", "start", done=0, total=2))
    progress.stage(Event("motion", "done", scene=2, done=1, total=2, asset="v.mp4"))
    progress.flush()
    snap = written(db, job.id)
    assert snap["spent_micros"] == 200_000 and snap["stages"]["motion"]["spent_micros"] == 200_000
    assert snap["scenes"]["2"]["motion"]["cost_micros"] == 100_000
    assert "3" not in snap["scenes"]  # paid for, but not reported yet: nothing to hang its cost on


async def test_a_render_reports_each_scene_through_motion_clips_and_the_mix(fake_cfg, make_story):
    events: list[Event] = []
    await Pipeline(fake_cfg, events.append).render(make_story(("still", "video")))

    def moves(stage: str, scene: int | None = None) -> list[str]:
        """Where an item went, in order; not the mix's ticks, each time ffmpeg moves on."""
        return [
            e.status
            for e in events
            if e.stage == stage and e.scene == scene and e.status in ITEM and e.at is None
        ]

    assert moves("motion", 2) == ["queued", "working", "done"]
    assert moves("clips", 1) == ["queued", "working", "done"]
    assert moves("mix") == ["queued", "working", "done"]


async def test_the_cli_prints_a_line_for_each_item_made_and_no_more(fake_cfg, make_story, capsys):
    await Pipeline(fake_cfg, _printer()).render(make_story(("still", "video")))
    lines = capsys.readouterr().out.splitlines()
    statuses = {line.split("]", 1)[1].split()[1] for line in lines}  # "[  0.1s] clips     done  3/3 scene 3"
    assert statuses == {"start", "done", "finish", "progress"}


async def test_paced_fakes_take_that_long_for_each_item(fake_cfg, make_story, monkeypatch):
    monkeypatch.setenv("LANTERNIST_FAKE_PACE", "0.05")
    cfg = fake_cfg.model_copy(update={"fake_pace": Settings().fake_pace})
    t0 = time.monotonic()
    await Pipeline(cfg).narrate(make_story(("still", "still", "still")))
    assert time.monotonic() - t0 >= 3 * 0.05


class Clock:
    """Stands in for the time module in jobs.py: time moves only when a test moves it."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def time(self) -> float:
        return self.now


async def test_each_row_of_a_batch_counts_its_own_time_and_a_redraw_adds_to_it(db, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(jobs, "time", clock)
    progress = Progress(db, db.add_job(None, "board", None, {}, None).id)

    def made(stage: str, scene: int | None, secs: float, done: int, total: int) -> None:
        progress.stage(Event(stage, "working", scene=scene))
        clock.now += secs
        progress.stage(Event(stage, "done", scene=scene, done=done, total=total, asset=f"{stage}{scene}.png"))

    progress.stage(Event("cast", "start", done=0, total=1))
    progress.stage(Event("keyframes", "start", done=0, total=2))
    made("cast", None, 10, 1, 1)
    made("keyframes", 1, 16, 1, 2)
    made("keyframes", 2, 16, 2, 2)
    clock.now += 30  # the check
    progress.stage(Event("keyframes", "start", done=1, total=2))  # scene 2 drawn again
    made("keyframes", 2, 16, 2, 2)
    progress.stage(Event("write", "start"))  # a stage with no items to work on has no time to tell
    progress.flush()
    stages = progress.snap["stages"]
    assert (stages["cast"]["secs"], stages["keyframes"]["secs"]) == (10, 48)
    assert "secs" not in stages["write"]


def test_the_portraits_to_draw_are_on_the_snapshot_before_they_start(db):
    progress = Progress(db, db.add_job(None, "board", None, {}, None).id)
    progress.plan_cast(True, ["a", "bo"])
    progress.stage(Event("portraits", "done", who="a", done=1, total=2, asset="a.png"))
    progress.plan_cast(True, ["a", "bo"])  # planned again (a job run twice): what's made stays made
    assert progress.snap["sheet"] is True
    assert {who: step["state"] for who, step in progress.snap["cast"].items()} == {
        "a": "done",
        "bo": "queued",
    }
