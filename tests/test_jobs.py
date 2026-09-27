"""The job queue: one job at a time, and nothing a user does to a story stops the queue."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from lanternist import jobs, pace
from lanternist.cli import _printer
from lanternist.config import Settings, Worker
from lanternist.db import LOCAL, Job, Story, now
from lanternist.engines.base import whole
from lanternist.jobs import THROTTLE, Progress, Runner
from lanternist.pipeline import ITEM, Event, Pipeline
from lanternist.storyboard import CastMember


async def test_deleting_a_story_while_its_job_runs_keeps_the_queue_going(cfg, db):
    with db.session() as s:
        s.add(Story(owner_id=LOCAL, id="s1", slug="a", title="A", version=0))
        s.commit()
    runner = Runner(cfg, db)
    runner.enqueue(LOCAL, "s1", "board", 1)

    async def delete_the_story(job, progress):  # what DELETE /api/stories does meanwhile
        assert db.delete_story(LOCAL, "s1")
        return {}

    runner.execute = delete_the_story
    await runner.run(db.claim_job(runner.name, jobs.FAST, False))  # raised AttributeError on the missing row
    assert db.jobs(LOCAL, active=False, limit=10) == []
    assert not runner.running


def test_claim_gives_each_worker_its_own_job(db):
    """Workers asking at the same moment never get the same job, and between them take every one."""
    queued = {db.add_job(LOCAL, None, "render", None, {}, None).id for _ in range(20)}
    db.add_job(LOCAL, None, "sample", None, {}, None)  # the other lane's
    start = threading.Barrier(4)

    def worker() -> list[str]:
        start.wait()
        claimed = []
        while job := db.claim_job(threading.current_thread().name, jobs.FAST, False, per_user=20):
            claimed.append(job.id)
        return claimed

    with ThreadPoolExecutor(4) as pool:
        claims = [f.result() for f in [pool.submit(worker) for _ in range(4)]]
    every = [job_id for claimed in claims for job_id in claimed]
    assert sorted(every) == sorted(queued)
    assert {(db.get_job(LOCAL, j).status, db.get_job(LOCAL, j).started_at is not None) for j in every} == {
        ("running", True)
    }


def written(db, job_id: str) -> dict:
    """The snapshot as the job row holds it: what the page gets."""
    with db.session() as s:
        return s.get(Job, job_id).progress


async def test_the_snapshot_follows_every_scene_and_portrait_to_done(fake_cfg, db, make_story):
    sb = make_story(("still", "video"))
    sb.cast.append(CastMember(id="bo", name="Bo", look="boy in a blue cap"))
    sb.portraits = True
    job = db.add_job(LOCAL, None, "board", None, {}, None)
    progress = Progress(db, job.id, "w")
    seen: dict[tuple[str, str], list[str]] = {}

    def follow(e: Event) -> None:
        progress.stage(e)
        whose = e.who if e.who is not None else str(e.scene)
        if e.status in ITEM and whose != "None":
            seen.setdefault((e.stage, whose), []).append(e.status)

    await Pipeline(fake_cfg, follow, db=db, job_id=job.id, owner=LOCAL).board(sb)
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
    again = Progress(db, job.id, "w")
    await Pipeline(fake_cfg, again.stage, db=db, job_id=job.id, owner=LOCAL).board(sb)
    assert again.snap["scenes"]["2"]["keyframes"] == {
        "state": "cached",
        "asset": snap["scenes"]["2"]["keyframes"]["asset"],
        "tries": 1,
    }
    # A row the cache holds all of is done from its start, not running until its batch ends.
    assert again.snap["stages"]["portraits"]["status"] == "done"
    assert {step["state"] for step in again.snap["cast"].values()} == {"cached"}


async def test_the_last_of_a_burst_of_events_is_written(cfg, db):
    db.add_job(LOCAL, None, "board", None, {}, None)
    job = db.claim_job("w", jobs.FAST, False)
    progress = Progress(db, job.id, "w")
    progress.stage(Event("keyframes", "start", done=0, total=2))
    progress.stage(Event("keyframes", "queued", scene=1))
    progress.stage(Event("keyframes", "working", scene=1))
    assert written(db, job.id)["scenes"] == {}  # within the throttle of the start: not written yet
    await asyncio.sleep(THROTTLE + 0.1)
    assert written(db, job.id)["scenes"]["1"]["keyframes"]["state"] == "working"


async def test_a_step_waiting_at_a_provider_says_how_many_are_ahead(cfg, db):
    job = db.add_job(LOCAL, None, "render", None, {}, None)
    progress = Progress(db, job.id, "w")
    progress.stage(Event("motion", "waiting", scene=4, ahead=2))
    assert progress.snap["scenes"]["4"]["motion"] == {"state": "waiting", "ahead": 2}
    progress.stage(Event("motion", "working", scene=4))
    assert progress.snap["scenes"]["4"]["motion"] == {"state": "working"}


async def test_the_snapshot_shows_what_each_paid_step_cost(cfg, db):
    db.add_job(LOCAL, None, "render", None, {}, None)
    job = db.claim_job("w", jobs.FAST, False)
    for scene, micros in ((2, 75_000), (2, 25_000), (3, 100_000)):
        db.start_run(
            job_id=job.id, scene=scene, stage="motion", model_id="fal/x", provider="fal", cost_micros=micros
        )
    db.start_run(job_id=job.id, stage="keyframes", model_id="local/x", provider="local", gpu_seconds=16)
    progress = Progress(db, job.id, "w")
    progress.stage(Event("motion", "start", done=0, total=2))
    progress.stage(Event("motion", "done", scene=2, done=1, total=2, asset="v.mp4"))
    progress.flush()
    snap = written(db, job.id)
    assert snap["spent_micros"] == 200_000 and snap["stages"]["motion"]["spent_micros"] == 200_000
    assert snap["scenes"]["2"]["motion"]["cost_micros"] == 100_000
    assert "3" not in snap["scenes"]  # paid for, but not reported yet: nothing to hang its cost on


async def test_a_render_reports_each_scene_through_motion_clips_and_the_mix(fake_cfg, make_story):
    events: list[Event] = []
    await Pipeline(fake_cfg, events.append, owner=LOCAL).render(make_story(("still", "video")))

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
    await Pipeline(fake_cfg, _printer(), owner=LOCAL).render(make_story(("still", "video")))
    lines = capsys.readouterr().out.splitlines()
    statuses = {line.split("]", 1)[1].split()[1] for line in lines}  # "[  0.1s] clips     done  3/3 scene 3"
    assert statuses == {"start", "done", "finish", "progress"}


async def test_paced_fakes_take_that_long_for_each_item(fake_cfg, make_story, monkeypatch):
    monkeypatch.setenv("LANTERNIST_FAKE_PACE", "0.05")
    cfg = fake_cfg.model_copy(update={"fake_pace": Settings().fake_pace})
    t0 = time.monotonic()
    await Pipeline(cfg, owner=LOCAL).narrate(make_story(("still", "still", "still")))
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
    progress = Progress(db, db.add_job(LOCAL, None, "board", None, {}, None).id, "w")

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
    progress = Progress(db, db.add_job(LOCAL, None, "board", None, {}, None).id, "w")
    progress.plan_cast(True, ["a", "bo"])
    progress.stage(Event("portraits", "done", who="a", done=1, total=2, asset="a.png"))
    progress.plan_cast(True, ["a", "bo"])  # planned again (a job run twice): what's made stays made
    assert progress.snap["sheet"] is True
    assert {who: step["state"] for who, step in progress.snap["cast"].items()} == {
        "a": "done",
        "bo": "queued",
    }


def test_the_library_says_how_far_a_running_job_is(db):
    with db.session() as s:
        s.add(Story(owner_id=LOCAL, id="s1", slug="a", title="A", version=0))
        s.commit()
    db.add_job(LOCAL, "s1", "render", 1, {}, None)
    running = db.claim_job("w", jobs.FAST, False)
    queued = db.add_job(LOCAL, "s1", "board", 1, {}, None)
    db.update_job(running.id, "w", progress={"fraction": 0.42})
    [row] = db.library(LOCAL)
    assert (row.active, row.progress) == (2, 0.42)
    db.end_job(running.id, "w", "done")
    db.request_cancel(LOCAL, queued.id)
    [row] = db.library(LOCAL)
    assert (row.active, row.progress) == (0, None)


async def test_how_far_a_job_is_never_goes_back_when_an_estimate_grows(db, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(jobs, "time", clock)
    progress = Progress(db, db.add_job(LOCAL, None, "render", None, {}, None).id, "w")
    progress.expect = {"keyframes": pace.Expect(2, 10.0, basis="history")}
    clock.now += 20
    progress.flush()
    before = progress.snap["fraction"]
    progress.expect["keyframes"].items = 200  # the check sent many back to be drawn again
    clock.now += 1
    progress.flush()
    assert 0 < before == progress.snap["fraction"]


# ------------------------------------------------------------------------------------ workers
def held(db, worker: str, kind: str = "render", story_id: str | None = None) -> Job:
    """A job `worker` has claimed: added, then claimed, so it's the one claimed."""
    db.add_job(LOCAL, story_id, kind, None, {}, None)
    job = db.claim_job(worker, jobs.FAST, kind in jobs.FAST, per_user=10)
    assert job is not None
    return job


def beat_at(db, job_id: str, when) -> None:
    with db.session() as s:
        s.get(Job, job_id).heartbeat_at = when
        s.commit()


def row(db, job_id: str) -> Job:
    with db.session() as s:
        return s.get(Job, job_id)


def test_heartbeat_stamps_only_its_own_jobs(db):
    mine, theirs = held(db, "w1"), held(db, "w2")
    long_ago = now() - timedelta(minutes=5)
    for job in (mine, theirs):
        beat_at(db, job.id, long_ago)
    assert db.heartbeat("w1", [mine.id]) == {mine.id: "held"}
    assert row(db, mine.id).heartbeat_at > long_ago and row(db, theirs.id).heartbeat_at == long_ago


def test_heartbeat_tells_held_cancel_lost_and_gone(db):
    with db.session() as s:
        s.add(Story(owner_id=LOCAL, id="s1", slug="a", title="A", version=0))
        s.commit()
    carry_on, cancel, lost, gone = (
        held(db, "w1"),
        held(db, "w1"),
        held(db, "w2"),
        held(db, "w1", story_id="s1"),
    )
    assert db.request_cancel(LOCAL, cancel.id)
    assert db.delete_story(LOCAL, "s1")
    assert db.heartbeat("w1", [carry_on.id, cancel.id, lost.id, gone.id]) == {
        carry_on.id: "held",
        cancel.id: "cancel",
        lost.id: "lost",  # another worker's: w1 thinks it still holds it
        gone.id: "gone",
    }


def test_requeue_stale_leaves_a_live_workers_job_alone(db):
    live, dead = held(db, "w1"), held(db, "w2")
    beat_at(db, dead.id, now() - timedelta(minutes=2))
    assert db.requeue_stale(timedelta(seconds=60)) == 1
    assert (row(db, live.id).status, row(db, live.id).worker) == ("running", "w1")
    back = row(db, dead.id)
    assert (back.status, back.worker, back.heartbeat_at) == ("queued", None, None)
    assert back.started_at is not None  # it ran before, which the claim puts first


def test_a_worker_that_lost_its_job_writes_nothing(db):
    job = held(db, "w1")
    db.update_job(job.id, "w1", progress={"message": "drawing"})
    db.requeue_stale(timedelta(0))  # w1 went quiet
    assert db.claim_job("w2", jobs.FAST, False).id == job.id
    assert not db.update_job(job.id, "w1", progress={"message": "stale"}, version=7)
    assert not db.end_job(job.id, "w1", "done", result={"film": "old.mp4"})
    kept = row(db, job.id)
    assert (kept.status, kept.worker, kept.progress, kept.version, kept.result) == (
        "running",
        "w2",
        {"message": "drawing"},
        None,
        None,
    )
    assert db.end_job(job.id, "w2", "queued")  # handed back: nobody holds it, and it has no slot
    assert (row(db, job.id).worker, row(db, job.id).slot) == (None, None)


def fast_beats(cfg: Settings) -> Settings:
    return cfg.model_copy(update={"worker": Worker(heartbeat_seconds=0.02, stale_seconds=0.2)})


def waiting_forever(runner: Runner, stopped: list):
    """An `execute` that runs until it's stopped, and records whether that was its user's cancel."""

    async def execute(job, progress):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.append(runner.user_cancelled(job.id))
            raise

    return execute


async def test_a_cancel_reaches_the_worker_that_holds_the_job(cfg, db, until):
    api, worker = Runner(cfg, db), Runner(fast_beats(cfg), db)  # two processes: the API's, and a worker's
    worker.name, stopped = "worker-1", []
    worker.execute = waiting_forever(worker, stopped)
    worker.start()
    try:
        job = api.enqueue(LOCAL, None, "render", None)
        await until(lambda: job.id in worker.running)
        assert api.cancel(LOCAL, job.id) and job.id in worker.running  # the API's own runner holds nothing
        await until(lambda: db.get_job(LOCAL, job.id).status == "cancelled")
        assert stopped == [True]  # as the user's cancel, which cancels at fal too
    finally:
        await worker.stop()


async def test_a_deleted_storys_job_is_cancelled_at_fal(cfg, db, until):
    with db.session() as s:
        s.add(Story(owner_id=LOCAL, id="s1", slug="a", title="A", version=0))
        s.commit()
    worker, stopped = Runner(fast_beats(cfg), db), []
    worker.execute = waiting_forever(worker, stopped)
    worker.start()
    try:
        job = worker.enqueue(LOCAL, "s1", "render", 1)
        await until(lambda: job.id in worker.running)
        assert db.delete_story(LOCAL, "s1")  # another process deleted it: nobody will resume the job
        await until(lambda: stopped)
        assert stopped == [True] and db.jobs(LOCAL, active=False, limit=5) == []
    finally:
        await worker.stop()


async def test_a_worker_cut_off_from_the_database_stops_its_jobs(cfg, db, until, monkeypatch):
    worker, stopped = Runner(fast_beats(cfg), db), []
    worker.execute = waiting_forever(worker, stopped)
    worker.start()
    try:
        job = worker.enqueue(LOCAL, None, "render", None)
        await until(lambda: job.id in worker.running)

        def unreachable(*_):
            raise OSError("connection refused")

        for method in ("heartbeat", "claim_job"):
            monkeypatch.setattr(db, method, unreachable)
        await until(lambda: stopped)  # within the lease, before another worker may take it
        assert stopped == [False]  # as a shutdown: fal's requests are left for the next holder
        await until(lambda: db.get_job(LOCAL, job.id).status == "queued")
    finally:
        monkeypatch.undo()
        await worker.stop()


# ------------------------------------------------------------------------------------ fair turns
def people(db, *names: str) -> list[str]:
    return [db.sign_in(f"test|{name}", f"{name}@example.com").id for name in names]


def test_claim_takes_turns_between_users(db):
    """Two workers and one render each at a time: whoever was served longest ago goes next, so Cleo,
    who queued last, doesn't wait behind Ann's and Bob's backlogs."""
    ann, bob, cleo = people(db, "ann", "bob", "cleo")
    for owner, count in ((ann, 3), (bob, 2), (cleo, 2)):
        for _ in range(count):
            db.add_job(owner, None, "render", None, {}, None)
    order, running = [], []
    for _ in range(7):
        if len(running) == 2:  # both workers are busy: the render that started first ends first
            first = running.pop(0)
            db.end_job(first.id, first.worker, "done")
        job = db.claim_job("w", jobs.FAST, False)
        order.append(job.owner_id)
        running.append(job)
    assert order == [ann, bob, cleo, ann, bob, cleo, ann]


def test_a_person_at_their_limit_is_skipped(db):
    ann, bob = people(db, "ann", "bob")
    for owner in (ann, ann, bob):
        db.add_job(owner, None, "render", None, {}, None)
    assert db.claim_job("w1", jobs.FAST, False).owner_id == ann
    assert db.claim_job("w2", jobs.FAST, False).owner_id == bob  # ann's second is older, but she has one
    assert db.claim_job("w3", jobs.FAST, False) is None
    assert db.claim_job("w3", jobs.FAST, False, per_user=2).owner_id == ann


def test_a_job_that_ran_before_goes_first(db):
    ann, bob = people(db, "ann", "bob")
    db.add_job(ann, None, "render", None, {}, None)
    db.add_job(bob, None, "render", None, {}, None)
    ran = db.claim_job("w1", jobs.FAST, False, per_user=2)
    db.add_job(ann, None, "render", None, {}, None)
    db.requeue_stale(timedelta(0))  # w1 died with ann's first render
    again = db.claim_job("w2", jobs.FAST, False)
    assert again.id == ran.id and again.slot == 0


def test_two_claims_for_one_person_cannot_both_win(db):
    """Two workers can each count the other's claim before it commits: the unique (owner, slot)
    settles it."""
    [ann] = people(db, "ann")
    for _ in range(8):
        db.add_job(ann, None, "render", None, {}, None)
    start = threading.Barrier(4)

    def claim(n: int) -> Job | None:
        start.wait()
        return db.claim_job(f"w{n}", jobs.FAST, False)

    with ThreadPoolExecutor(4) as pool:
        won = [job for job in pool.map(claim, range(4)) if job is not None]
    assert len(won) == 1 and won[0].slot == 0
    assert len(db.jobs(ann, active=True, limit=10)) == 8  # one running, seven waiting their turn


async def test_two_workers_and_three_users_take_fair_turns(cfg, db, until):
    ann, bob, cleo = people(db, "ann", "bob", "cleo")
    starts: list[str] = []
    at_once: dict[str, int] = {}

    async def execute(job, progress):  # a render of a fixed length
        starts.append(job.owner_id)
        at_once[job.owner_id] = at_once.get(job.owner_id, 0) + 1
        assert at_once[job.owner_id] == 1, "two renders at once for one person"
        await asyncio.sleep(0.1)
        at_once[job.owner_id] -= 1
        return {}

    workers = [Runner(cfg, db), Runner(cfg, db)]
    for n, worker in enumerate(workers):
        worker.name, worker.execute = f"w{n}", execute
        worker.start()
    try:
        for owner, count in ((ann, 3), (bob, 2), (cleo, 2)):
            for _ in range(count):
                workers[0].enqueue(owner, None, "render", None)
        await until(lambda: len(starts) == 7 and not any(w.running for w in workers), timeout=10)
    finally:
        for worker in workers:
            await worker.stop()
    # Everyone's first film starts before anyone's second, and everyone's second before Ann's third.
    assert set(starts[:3]) == set(starts[3:6]) == {ann, bob, cleo} and starts[6] == ann


async def test_a_cancel_heard_while_stopping_claims_nothing_more(cfg, db, until):
    """The heartbeat goes on while a stopping worker's job stores what fal billed; a cancel it hears
    then ends the job, and the worker still stops."""
    worker, started = Runner(fast_beats(cfg), db), []

    async def execute(job, progress):
        started.append(job.id)
        await whole(asyncio.sleep(0.3))  # storing what fal billed, through the stop
        return {}

    worker.execute = execute
    worker.start()
    first = worker.enqueue(LOCAL, None, "render", None)
    await until(lambda: started)
    second = worker.enqueue(LOCAL, None, "render", None)
    stopping = asyncio.create_task(worker.stop())
    await asyncio.sleep(0)
    assert db.request_cancel(LOCAL, first.id)
    await asyncio.wait_for(stopping, timeout=5)
    assert started == [first.id]
    assert (db.get_job(LOCAL, first.id).status, db.get_job(LOCAL, second.id).status) == (
        "cancelled",
        "queued",
    )
