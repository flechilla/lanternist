"""`lanternist worker` as real processes, on the test's database and library: one killed in the middle of
a video, and one stopped by SIGTERM, as a deploy stops it. The fake fal makes each request last
LANTERNIST_FAKE_PACE, so there's a request open to stop the worker during; each test takes a few
seconds."""

import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from test_api import storyboard

from lanternist.db import Database, Job, StepRun
from lanternist.jobs import STOP_GRACE
from lanternist.providers.fake import FakeWorld

WORKER = "heartbeat_seconds = 0.5\nstale_seconds = 3\n"


@pytest.fixture
def hosted(hosted_config, monkeypatch) -> Iterator[tuple[Database, Path]]:
    """The hosted edition's database, migrated as a deploy does, and its library."""
    monkeypatch.setenv("LANTERNIST_FAKE_PACE", "1")
    cfg = hosted_config(WORKER)
    db = Database(cfg.database_url)
    db.migrate()
    yield db, cfg.library
    db.close()


@pytest.fixture
def workers(tmp_path) -> Iterator[Callable[[], subprocess.Popen]]:
    """Starts `lanternist worker` processes, each logging to a file of its own; kills what's left."""
    started: list[subprocess.Popen] = []

    def start() -> subprocess.Popen:
        log = (tmp_path / f"worker-{len(started)}.log").open("w")
        cmd = [sys.executable, "-c", "from lanternist.cli import app; app()", "worker"]
        started.append(subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT))
        return started[-1]

    yield start
    for p in started:
        p.kill()
        p.wait()


def a_render(db: Database) -> str:
    """A render of a story whose first two scenes are videos."""
    owner = db.sign_in("test|ann", "ann@example.com").id
    sb = storyboard(voice="Vivian")
    sb["scenes"][0]["mode"] = "video"
    story = db.create_story(owner, "Test story", "en", sb)
    return db.add_job(owner, story.id, "render", story.version, {}, None).id


def motion_runs(db: Database) -> list[StepRun]:
    with db.session() as s:
        return s.query(StepRun).filter(StepRun.stage == "motion").all()


def job(db: Database, job_id: str) -> Job:
    with db.session() as s:
        return s.get(Job, job_id)


def until(cond: Callable[[], object], timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while not cond():
        assert time.time() < deadline, "timed out"
        time.sleep(0.05)


def paid_once(db: Database, library: Path) -> bool:
    """fal got one request for each video step: whoever finished a step polled the request already made."""
    runs = motion_runs(db)
    endpoints = {r.meta["endpoint"] for r in runs}
    sent = [q for q in FakeWorld(library / "fake").fal.requests.values() if q.endpoint in endpoints]
    return len(sent) == len({r.step_key for r in runs}) == 2


def mid_video(db: Database, workers) -> tuple[str, subprocess.Popen]:
    """A render, and the worker running it, once it has a video's request open at fal."""
    job_id, first = a_render(db), workers()
    until(lambda: any(r.status in ("submitted", "running") for r in motion_runs(db)))
    return job_id, first


def test_a_killed_worker_is_picked_up_and_pays_fal_once(hosted, workers):
    db, library = hosted
    job_id, first = mid_video(db, workers)
    first.send_signal(signal.SIGKILL)
    first.wait()
    second = workers()  # takes the job once its heartbeat is stale_seconds old
    until(lambda: job(db, job_id).status == "done")
    assert job(db, job_id).worker.endswith(f"-{second.pid}") and paid_once(db, library)


def test_sigterm_hands_the_job_back(hosted, workers):
    db, library = hosted
    job_id, first = mid_video(db, workers)
    first.send_signal(signal.SIGTERM)  # a deploy
    assert first.wait(timeout=STOP_GRACE) == 0
    handed = job(db, job_id)
    assert (handed.status, handed.worker, handed.slot) == ("queued", None, None)  # no heartbeat to wait out
    workers()
    until(lambda: job(db, job_id).status == "done")
    assert paid_once(db, library)
