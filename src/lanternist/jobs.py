"""The render queue: one in-process worker that runs jobs one at a time, in order.

Job state lives in SQLite, so a restart re-queues whatever was running; its finished steps are
served from the cache and it carries on where it stopped. Progress is a snapshot on the job row
that the SSE endpoint streams to the browser.
"""

import asyncio
import contextlib
import logging
import shutil
import time
import traceback
from typing import Any, cast

from . import pace, prefs
from .config import Settings
from .db import TERMINAL, Database, Job, now
from .keys import redact
from .llm import Calls
from .pipeline import ACTIONS, ITEM, LABELS, Board, BudgetExceeded, Event, Pipeline
from .storyboard import Storyboard

log = logging.getLogger(__name__)

THROTTLE = 0.25  # seconds between two writes of a snapshot while items land


def describe(e: Event) -> str:
    label = LABELS.get(e.stage, e.stage)
    if e.status == "start" and not e.total:
        return f"{label}: started"
    if e.status == "start":
        todo = e.total - e.done
        if not todo:
            return f"{label}: all {e.total} already made"
        return f"{label}: {todo} to make" + (f", {e.done} already made" if e.done else "")
    if e.status == "finish":
        return f"{label}: finished"
    if e.status == "done" and e.scene is not None:
        what = f"fails: {e.failed}" if e.failed is not None else "ready"
        return f"{label}: scene {e.scene} {what} ({e.done} of {e.total})"
    if e.status == "done" and e.who is not None:
        return f"{label}: {e.who} ready ({e.done} of {e.total})"
    if e.status == "done":
        return f"{label}: ready"
    return f"{label}: {e.status}"


class Progress:
    """Folds pipeline events into the snapshot the UI shows: one row per stage; each scene's step in
    each stage, and each character's portrait, as they move from queued to done; what the job has
    spent, in all and by stage; and a short log.

    A stage row names what makes its items (`model`, and `local` when that's this machine). For a
    board or render, `sheet` says whether it draws a cast sheet, and the portraits it will draw are in
    `cast` from the start. Told what its stages should take (`expect`), it also says how long is left
    as a range (`eta_s`), each stage's share of the time (`phases`) and how far through it is
    (`fraction`, by time). A stage row says how long it has worked (`secs`), and the mix how far
    through the film it is (`at`).

    A step is {state, asset, secs, tries, ahead, note, cost_micros}: its state is an item status, or
    "failed" when the picture check failed its picture, with why in `note`. A step made again keeps
    its last asset until the new one lands, so the page can show the old picture meanwhile. Its cost
    is what the provider billed for that scene in that stage; a portrait's and a check's are counted
    in their stage's spend only, since their runs aren't logged by scene."""

    def __init__(self, db: Database, job_id: str):
        self.db, self.job_id = db, job_id
        self.snap: dict[str, Any] = {"stages": {}, "scenes": {}, "cast": {}, "log": [], "message": ""}
        self.t0 = time.time()
        # What each stage of a board or render is expected to take: how long is left comes from it.
        self.expect: dict[str, pace.Expect] = {}
        self._last_write = 0.0
        self._later: asyncio.TimerHandle | None = None
        self._began: dict[tuple[str, str], float] = {}  # when work on each step began, by row and whose
        self._ran: dict[str, float] = {}  # seconds each stage has worked, not counting its current run
        self._since: dict[str, float] = {}  # when each stage at work now started on its first item

    def stage(self, e: Event) -> None:
        st = self.snap["stages"].setdefault(
            e.stage,
            {
                "label": LABELS.get(e.stage, e.stage),
                "doing": ACTIONS.get(e.stage, ""),
                "status": "running",
                "done": 0,
                "total": 0,
            },
        )
        if e.total:
            st["done"], st["total"] = e.done, e.total
        # A row is done once all its items are: the cast sheet's before the pictures of its batch.
        if e.status == "finish" or (e.status == "done" and e.done == e.total):
            st["status"] = "done"
        elif e.status == "cached" and e.scene is None and e.who is None:
            st.update(status="done", done=1, total=1)
        else:
            st["status"] = "running"
        # A stage's time runs from starting on its first item, so a batch's rows don't count each other's.
        if e.status in ("waiting", "working"):
            self._since.setdefault(e.stage, time.time())
        if st["status"] == "done" and e.stage in self._since:
            self._ran[e.stage] = self._ran.get(e.stage, 0.0) + time.time() - self._since.pop(e.stage)
        if e.asset and e.scene is None and e.who is None:
            st["asset"] = e.asset
        if e.at is not None:
            st["at"] = e.at
        if e.model:
            st["model"], st["local"] = e.model, e.local
        if e.status in ITEM:
            self._move(e)
        if e.message or e.status in ("start", "done", "finish"):
            self.note(
                f"{LABELS.get(e.stage, e.stage)}: {e.message}" if e.message else describe(e),
                flush=e.status != "done",
            )
        else:
            self.flush(force=False)

    def _move(self, e: Event) -> None:
        """Move one item's step along: a scene's, in its stage's row, or a character's portrait."""
        if e.scene is not None:
            whose = str(e.scene)
            step = self.snap["scenes"].setdefault(whose, {}).setdefault(e.stage, {})
        elif e.who is not None:
            whose, step = e.who, self.snap["cast"].setdefault(e.who, {})
        else:
            return
        if e.status == "cached" and step.get("asset") == e.asset:
            return  # made earlier in this job, and served from the cache now
        step["state"] = "failed" if e.failed is not None else e.status
        step.pop("ahead", None)
        if e.ahead is not None:
            step["ahead"] = e.ahead
        if e.status in ("waiting", "working"):  # from the moment it's asked for: a queue is part of it
            self._began.setdefault((e.stage, whose), time.time())
        if e.status in ("cached", "done"):
            step["asset"] = e.asset
            step.pop("note", None)
            if e.failed is not None:
                step["note"] = e.failed
        if e.status == "done":
            step["tries"] = step.get("tries", 0) + 1
            if (began := self._began.pop((e.stage, whose), None)) is not None:
                step["secs"] = round(time.time() - began, 1)

    def plan_cast(self, sheet: bool, portraits: list[str]) -> None:
        """What a board or render will draw of its cast, so the page shows it from the start: whether
        there's a cast sheet, and whose portraits (queued, until their stage reports them)."""
        self.snap["sheet"] = sheet
        for who in portraits:
            self.snap["cast"].setdefault(who, {"state": "queued"})

    def note(self, message: str, flush: bool = True) -> None:
        self.snap["message"] = message
        self.snap["log"] = (self.snap["log"] + [f"{time.time() - self.t0:6.1f}s  {message}"])[-40:]
        self.flush(force=flush)

    def flush(self, force: bool = True) -> None:
        wait = self._last_write + THROTTLE - time.time()
        if force or wait <= 0:
            self._write()
        elif self._later is None:
            # A moment later, so the last of a burst of events isn't held back until the next one.
            self._later = asyncio.get_running_loop().call_later(wait, self._write)

    def _write(self) -> None:
        if self._later is not None:
            self._later.cancel()
            self._later = None
        self._last_write = time.time()
        self._spend()
        self._time()
        self.db.update_job(self.job_id, progress=dict(self.snap))

    def _time(self) -> None:
        """How long each stage has worked; and, for a job that knows what its stages should take, how
        long it has left, each stage's share of its time and how far through it is."""
        now = time.time()
        seen: dict[str, pace.Seen] = {}
        for stage, st in self.snap["stages"].items():
            elapsed = self._ran.get(stage, 0.0) + (now - self._since[stage] if stage in self._since else 0.0)
            if (
                stage in self._ran or stage in self._since
            ):  # it has worked on an item: the writer's never does
                st["secs"] = round(elapsed, 1)
            steps = [s[stage] for s in self.snap["scenes"].values() if stage in s]
            if stage == "portraits":
                steps += self.snap["cast"].values()
            seen[stage] = pace.Seen(
                left=st["total"] - st["done"],
                secs=[s["secs"] for s in steps if "secs" in s],
                elapsed=elapsed,
                at=st.get("at", 0.0),
                waiting=any(s.get("state") == "waiting" for s in steps),
            )
        if not self.expect:
            return
        lo, hi, whole = pace.left(self.expect, seen)
        total = sum(whole.values())
        ran = now - self.t0
        self.snap["eta_s"] = [round(lo), round(hi)]
        self.snap["phases"] = [
            {"stage": k, "label": LABELS.get(k, k), "share": round(v / total, 4)}
            for k, v in whole.items()
            if v > 0
        ]
        # Shown as a percentage in the tab and the Library, which mustn't go back when an estimate grows.
        now_at = round(ran / (ran + (lo + hi) / 2), 3) if ran + lo + hi else 0.0
        self.snap["fraction"] = max(self.snap.get("fraction", 0.0), now_at)

    def _spend(self) -> None:
        """What the job has paid for so far: in all, by stage, and for each scene's step."""
        spend = self.db.spend_by_step(self.job_id)
        self.snap["spent_micros"] = sum(spend.values())
        by_stage: dict[str, int] = {}
        for (stage, scene), micros in spend.items():
            by_stage[stage] = by_stage.get(stage, 0) + micros
            if scene is not None and (step := self.snap["scenes"].get(str(scene), {}).get(stage)):
                step["cost_micros"] = micros
        for stage, micros in by_stage.items():
            if stage in self.snap["stages"]:
                self.snap["stages"][stage]["spent_micros"] = micros


# A few seconds on a remote model each: they run in a lane of their own, beside the queue, so a voice
# sample never waits behind a render. They never take the GPU.
FAST = ("sample",)


class Runner:
    def __init__(self, cfg: Settings, db: Database):
        self.cfg, self.db = cfg, db
        self.wakes = {False: asyncio.Event(), True: asyncio.Event()}  # by lane: fast or not
        self.current: tuple[str, asyncio.Task] | None = None  # the queue's running job
        self.current_fast: tuple[str, asyncio.Task] | None = None
        self._loops: list[asyncio.Task] = []
        self._event_loop: asyncio.AbstractEventLoop | None = None
        # Jobs the user cancelled, as opposed to a shutdown: only these cancel remote requests.
        self.cancel_requested: set[str] = set()

    def user_cancelled(self, job_id: str) -> bool:
        return job_id in self.cancel_requested

    # control ------------------------------------------------------------------------------------
    def start(self) -> None:
        self.db.requeue_running()  # interrupted by a restart: run again, cached steps skip
        self._event_loop = asyncio.get_running_loop()
        self._loops = [asyncio.create_task(self.loop(fast)) for fast in (False, True)]

    async def stop(self) -> None:
        for running in (self.current, self.current_fast):
            if running:
                running[1].cancel()
        for task in self._loops:
            task.cancel()

    def _wake(self, fast: bool) -> None:
        # Routes enqueue from FastAPI's thread pool; the event belongs to the server's loop.
        if self._event_loop and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(self.wakes[fast].set)
        else:
            self.wakes[fast].set()

    def enqueue(
        self,
        story_id: str | None,
        kind: str,
        version: int | None,
        params: dict | None = None,
        estimate: dict | None = None,
    ) -> Job:
        job = self.db.add_job(story_id, kind, version, params or {}, estimate)
        self._wake(kind in FAST)
        return job

    def cancel(self, job_id: str) -> bool:
        for running in (self.current, self.current_fast):
            if running and running[0] == job_id:
                self.cancel_requested.add(job_id)
                running[1].cancel()
                return True
        return self.db.cancel_queued(job_id)

    # loop -------------------------------------------------------------------------------------
    async def loop(self, fast: bool = False) -> None:
        """Run one lane's queued jobs one at a time, oldest first."""
        wake = self.wakes[fast]
        while True:
            job = self.db.next_job(FAST, fast)
            if job is None:
                wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(wake.wait(), timeout=5)
                continue
            await self.run(job.id, fast)

    async def run(self, job_id: str, fast: bool = False) -> None:
        job = self.db.update_job(job_id, status="running", started_at=now(), error=None)
        if job is None:
            return  # deleted with its story since it was picked
        progress = Progress(self.db, job_id)
        task = asyncio.create_task(self.execute(job, progress))
        if fast:
            self.current_fast = (job_id, task)
        else:
            self.current = (job_id, task)
        status, result, error = "done", None, None
        try:
            result = await task
        except asyncio.CancelledError:
            if cast(asyncio.Task, asyncio.current_task()).cancelling():  # run() always runs in a task
                status = "queued"  # the server is shutting down: run it again on the next start
                raise
            status = "cancelled"
        except BudgetExceeded as e:  # not a crash: the UI offers to raise the budget and carry on
            status, result, error = "failed", {"budget": e.info()}, redact(str(e))
            progress.note(f"stopped before spending: {error}")
        except Exception as e:  # a failed job must not stop the queue
            log.exception("job %s failed", job_id)
            status, error = "failed", redact(f"{e}\n\n{traceback.format_exc()[-3000:]}")
            progress.note(f"failed: {(redact(str(e)) or repr(e)).splitlines()[0][:200]}")
        finally:
            if fast:
                self.current_fast = None
            else:
                self.current = None
            self.cancel_requested.discard(job_id)
            if status == "done":
                for st in progress.snap["stages"].values():
                    st["status"] = "done"
            # Deleting a story deletes its jobs, a running one too; the row is then gone and this does nothing.
            self.db.update_job(
                job_id,
                status=status,
                result=result,
                error=error,
                finished_at=now(),
                progress=dict(progress.snap),
            )

    async def execute(self, job: Job, progress: Progress) -> dict:
        cfg = prefs.effective(self.cfg, self.db)  # what the Settings page saved applies from the next job
        pipeline = Pipeline(
            cfg,
            progress.stage,
            db=self.db,
            story_id=job.story_id,
            job_id=job.id,
            user_cancelled=lambda: self.user_cancelled(job.id),
            budget_micros=self.db.budget_micros(job.story_id, cfg.defaults.budget_usd)
            if job.story_id
            else None,
        )
        if job.kind == "sample":
            p = job.params
            return {"audio": await pipeline.sample(p["tts"], p["voice"], p["language"])}
        if job.story_id is None:
            raise ValueError(f"a {job.kind} job needs a story")
        calls = Calls(self.db, story_id=job.story_id, job_id=job.id)
        if job.kind == "write":
            from .writer import Brief, write_storyboard

            # Two passes, counted on the row once the first is done, so the page can say which is on.
            progress.stage(Event("write", "start"))
            sb = await write_storyboard(
                cfg,
                Brief(**job.params),
                emit=progress.note,
                calls=calls,
                drafted=lambda: progress.stage(Event("write", "progress", done=1, total=2)),
            )
            version = self.db.add_version(job.story_id, sb.model_dump(), note="written")
            progress.stage(Event("write", "finish", done=2, total=2))
            return {"version": version, **calls.summary()}

        with self.db.session() as s:
            story, row = self.db.storyboard(s, job.story_id, job.version)
        sb = Storyboard.model_validate(row.storyboard)
        if job.kind in ("board", "render"):
            progress.expect = pace.plan(cfg, self.db, job.estimate, job.kind, len(sb.scenes))
            sheet, portraits, _ = pipeline.picture_items(pipeline.image(sb), sb)
            progress.plan_cast(bool(sheet), [it.who for it in portraits if it.who])

        if job.kind == "rewrite":
            from .writer import rewrite_scene

            n = job.params["n"]
            progress.stage(Event("write", "start", message=f"rewriting scene {n}"))
            new = await rewrite_scene(cfg, sb, n, job.params["instruction"], calls=calls)
            sb.scenes = [new if s.n == n else s for s in sb.scenes]
            version = self.db.add_version(job.story_id, sb.model_dump(), note=f"rewrote scene {n}")
            progress.stage(Event("write", "finish", done=1, total=1))
            return {"version": version, **calls.summary()}

        if job.kind == "cast":
            cast, _ = await pipeline.draw(sb, cast_only=True)
            return {"cast": cast}

        if job.kind == "board":
            b, checked, _ = await self.checked_board(pipeline, job, sb)
            return {
                "cast": b.cast,
                "keyframes": b.keyframes,
                "total": round(b.timeline.total, 2),
                "poster": b.keyframes[0] if b.keyframes else None,
                **checked,
            }

        if job.kind == "render":
            b, checked, made_from = await self.checked_board(pipeline, job, sb)
            film = await pipeline.render(sb, b)
            dest = cfg.library / "films" / f"{story.slug}-v{made_from}.mp4"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pipeline.store.path(film.film), dest)
            return {
                "film": film.film,
                "srt": film.srt,
                "vtt": film.vtt,
                "duration": film.duration,
                "path": str(dest),
                "poster": film.poster,
                **checked,
            }

        raise ValueError(f"unknown job kind {job.kind}")

    async def checked_board(
        self, pipeline: Pipeline, job: Job, sb: Storyboard
    ) -> tuple[Board, dict, int | None]:
        """The board, and what its picture check did for the job's result; with the version the job
        then made its pictures from. The pictures the check drew again are kept even when the board
        fails after them, so running it again carries on from there."""
        before = sb.model_copy(deep=True)
        try:
            b = await pipeline.board(sb)
        except BaseException as e:
            kept = self.keep_redraws(pipeline, job, before, sb)
            if isinstance(e, asyncio.CancelledError) and not self.user_cancelled(job.id):
                # A shutdown: the job runs again on the next start, from the new seeds rather than the
                # pictures that failed. A job that failed or was cancelled keeps the version it drew.
                self._take_version(job, kept)
            raise
        checked: dict = {"flagged": b.flagged} if b.flagged else {}
        kept = self.keep_redraws(pipeline, job, before, sb)
        if kept:
            version, redrawn = kept
            checked |= {"version": version, "redrawn": {n: b.redrawn[n] for n in redrawn}}
        return b, checked, self._take_version(job, kept)

    def _take_version(self, job: Job, kept: tuple[int, list[int]] | None) -> int | None:
        """The version the job's pictures come from: the one its check saved, when nothing else was
        saved while it ran, so the new version is exactly what this job made; else the one it started on."""
        if kept and kept[0] == (job.version or 0) + 1:
            self.db.update_job(job.id, version=kept[0])
            return kept[0]
        return job.version

    def keep_redraws(
        self, pipeline: Pipeline, job: Job, before: Storyboard, after: Storyboard
    ) -> tuple[int, list[int]] | None:
        """Save the seeds of the pictures the check drew again in the story's latest version, as a
        re-roll's would, on the scenes whose picture is still the one it checked, so an edit saved while
        the job ran is kept. Returns the new version and the scenes it kept seeds for, or None when
        there was nothing to keep."""
        if not pipeline.redrawn or job.story_id is None:
            return None
        seeds = {sc.n: sc.seed for sc in after.scenes if sc.n in pipeline.redrawn}
        checked = pipeline.keyframe_keys(before)
        kept: list[int] = []

        def change(latest: Storyboard) -> str:
            keys = pipeline.keyframe_keys(latest)
            for sc in latest.scenes:
                if sc.n in seeds and keys.get(sc.n) is not None and keys.get(sc.n) == checked.get(sc.n):
                    sc.seed = seeds[sc.n]
                    kept.append(sc.n)
            return f"the picture check drew scene{'s' if len(kept) > 1 else ''} {', '.join(map(str, kept))} again"

        version = self.db.change_story(job.story_id, change)
        return (version, kept) if version is not None else None


def is_terminal(status: str) -> bool:
    return status in TERMINAL
