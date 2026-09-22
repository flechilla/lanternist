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

from . import prefs
from .config import Settings
from .db import TERMINAL, Database, Job, now
from .keys import redact
from .llm import Calls
from .pipeline import Event, Pipeline
from .storyboard import Storyboard

log = logging.getLogger(__name__)

STAGES = ["write", "narration", "cast", "keyframes", "motion", "clips", "mix"]
LABELS = {
    "write": "Writing",
    "narration": "Narration",
    "cast": "Cast sheet",
    "keyframes": "Pictures",
    "motion": "Animation",
    "clips": "Scene clips",
    "mix": "Final mix",
}


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
        return f"{label}: scene {e.scene} ready ({e.done} of {e.total})"
    if e.status == "done":
        return f"{label}: ready"
    return f"{label}: {e.status}"


class Progress:
    """Folds pipeline events into the snapshot the UI shows: one row per stage, plus a short log."""

    def __init__(self, db: Database, job_id: str):
        self.db, self.job_id = db, job_id
        self.snap: dict[str, Any] = {"stages": {}, "log": [], "message": ""}
        self.t0 = time.time()
        self._last_write = 0.0

    def stage(self, e: Event) -> None:
        st = self.snap["stages"].setdefault(e.stage, {"status": "running", "done": 0, "total": 0})
        if e.total:
            st["done"], st["total"] = e.done, e.total
        if e.status == "finish":
            st["status"] = "done"
        elif e.status == "cached" and e.scene is None:
            st.update(status="done", done=1, total=1)
        else:
            st["status"] = "running"
        if e.asset and e.scene is not None:
            st.setdefault("assets", {})[str(e.scene)] = e.asset
        elif e.asset:
            st["asset"] = e.asset
        if e.message or e.status in ("start", "done", "finish"):
            self.note(
                f"{LABELS.get(e.stage, e.stage)}: {e.message}" if e.message else describe(e),
                flush=e.status != "done",
            )
        else:
            self.flush()

    def note(self, message: str, flush: bool = True) -> None:
        self.snap["message"] = message
        self.snap["log"] = (self.snap["log"] + [f"{time.time() - self.t0:6.1f}s  {message}"])[-40:]
        self.flush(force=flush)

    def flush(self, force: bool = True) -> None:
        if not force and time.time() - self._last_write < 0.25:
            return
        self._last_write = time.time()
        with self.db.session() as s:
            job = s.get(Job, self.job_id)
            if job:
                job.progress = dict(self.snap)
                s.commit()


class Runner:
    def __init__(self, cfg: Settings, db: Database):
        self.cfg, self.db = cfg, db
        self.wake = asyncio.Event()
        self.current: tuple[str, asyncio.Task] | None = None
        self._loop: asyncio.Task | None = None
        # Jobs the user cancelled, as opposed to a shutdown: only these cancel remote requests.
        self.cancel_requested: set[str] = set()

    def user_cancelled(self, job_id: str) -> bool:
        return job_id in self.cancel_requested

    # control ------------------------------------------------------------------------------------
    def start(self) -> None:
        with self.db.session() as s:
            for job in s.query(Job).filter(Job.status == "running"):
                job.status = "queued"  # interrupted by a restart: run again, cached steps skip
            s.commit()
        self._loop = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        if self.current:
            self.current[1].cancel()
        if self._loop:
            self._loop.cancel()

    def enqueue(self, story_id: str, kind: str, version: int | None, params: dict | None = None) -> Job:
        with self.db.session() as s:
            job = Job(story_id=story_id, kind=kind, version=version, params=params or {}, progress={})
            s.add(job)
            s.commit()
        self.wake.set()
        return job

    def cancel(self, job_id: str) -> bool:
        if self.current and self.current[0] == job_id:
            self.cancel_requested.add(job_id)
            self.current[1].cancel()
            return True
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if job and job.status == "queued":
                job.status, job.finished_at = "cancelled", now()
                s.commit()
                return True
        return False

    # loop -------------------------------------------------------------------------------------
    async def loop(self) -> None:
        while True:
            with self.db.session() as s:
                job = s.query(Job).filter(Job.status == "queued").order_by(Job.created_at).first()
            if job is None:
                self.wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.wake.wait(), timeout=5)
                continue
            await self.run(job.id)

    async def run(self, job_id: str) -> None:
        job = self.db.update_job(job_id, status="running", started_at=now(), error=None)
        if job is None:
            return  # deleted with its story since it was picked
        progress = Progress(self.db, job_id)
        task = asyncio.create_task(self.execute(job, progress))
        self.current = (job_id, task)
        status, result, error = "done", None, None
        try:
            result = await task
        except asyncio.CancelledError:
            if cast(asyncio.Task, asyncio.current_task()).cancelling():  # run() always runs in a task
                status = "queued"  # the server is shutting down: run it again on the next start
                raise
            status = "cancelled"
        except Exception as e:  # a failed job must not stop the queue
            log.exception("job %s failed", job_id)
            status, error = "failed", redact(f"{e}\n\n{traceback.format_exc()[-3000:]}")
            progress.note(f"failed: {(redact(str(e)) or repr(e)).splitlines()[0][:200]}")
        finally:
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
        pipeline = Pipeline(cfg, progress.stage)
        calls = Calls(self.db, story_id=job.story_id, job_id=job.id)
        if job.kind == "write":
            from .writer import Brief, write_storyboard

            progress.stage(Event("write", "start"))
            sb = await write_storyboard(cfg, Brief(**job.params), emit=progress.note, calls=calls)
            version = self.db.add_version(job.story_id, sb.model_dump(), note="written")
            progress.stage(Event("write", "finish", done=1, total=1))
            return {"version": version, **calls.summary()}

        with self.db.session() as s:
            story, row = self.db.storyboard(s, job.story_id, job.version)
        sb = Storyboard.model_validate(row.storyboard)

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
            b = await pipeline.board(sb)
            return {
                "cast": b.cast,
                "keyframes": b.keyframes,
                "total": round(b.timeline.total, 2),
                "poster": b.keyframes[0] if b.keyframes else None,
            }

        if job.kind == "render":
            film = await pipeline.render(sb)
            dest = cfg.library / "films" / f"{story.slug}-v{job.version}.mp4"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pipeline.store.path(film.film), dest)
            return {
                "film": film.film,
                "srt": film.srt,
                "vtt": film.vtt,
                "duration": film.duration,
                "path": str(dest),
                "poster": film.poster,
            }

        raise ValueError(f"unknown job kind {job.kind}")


def is_terminal(status: str) -> bool:
    return status in TERMINAL
