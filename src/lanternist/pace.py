"""How long a board or render has left, as a range, and each stage's share of the whole.

Before a stage starts, each of its items is expected to take what its model took on this machine
before (the median of its recent step_runs), else what the registry says a local model takes, else a
rough guess. Once a few are made in this job, the pace they kept replaces that. A stage that runs
items at once (requests at fal, checks, clips) divides its time by how many.

The range says how sure it is: a guess spreads wider than a measurement, and items waiting in a
provider's queue can wait any time. It's a range and not a countdown, so it never promises a second.
"""

import math
import statistics
from dataclasses import dataclass

from .check import CHECKS_AT_ONCE
from .config import Settings
from .db import Database
from .engines.local import Clips
from .pipeline import LABELS

# Seconds an item takes when nothing better is known: fal's queues and this machine's ffmpeg vary.
GUESS = {
    "narration": 5.0,
    "cast": 20.0,
    "portraits": 20.0,
    "keyframes": 20.0,
    "check": 5.0,
    "motion": 60.0,
    "ambience": 15.0,
    "clips": 1.0,
    "mix": 30.0,
}
PICTURES = ("cast", "portraits", "keyframes")  # the rows the estimate's picture line counts as one
MEASURED = 2  # items made in this job before their pace replaces what was expected
HISTORY = 50  # recent runs of a model its median is taken over
# How far below and above its middle a stage's time may land, by what that time is based on.
SPREAD = {"job": (0.85, 1.2), "history": (0.75, 1.4), "listed": (0.7, 1.6), "guess": (0.5, 2.0)}


@dataclass
class Expect:
    """What a stage of a job is expected to take, before it starts."""

    items: int  # to make
    secs: float  # each
    at_once: int = 1
    basis: str = "guess"  # history | listed | guess


@dataclass
class Seen:
    """A stage as far as the job has run it."""

    left: int  # items not made yet
    secs: list[float]  # how long each item it made took, from starting on it to its output landing
    elapsed: float  # seconds the stage has run
    at: float = 0.0  # how far through its one item it is, when it says (the mix)
    waiting: bool = False  # an item is in a provider's queue


def plan(cfg: Settings, db: Database, estimate: dict | None, kind: str, scenes: int) -> dict[str, Expect]:
    """Each stage a board or render job runs, with what it's expected to take: from the estimate the
    job was quoted, which counts what's left to make in each stage and names its model."""
    out: dict[str, Expect] = {}
    for line in (estimate or {}).get("lines", []):
        rows = PICTURES if line["stage"] == "keyframes" else (line["stage"],)
        at_once = 1 if line["local"] else cfg.fal.max_concurrency
        listed = line["gpu_seconds"] / line["todo"] if line["local"] and line["todo"] else None
        for row in rows:
            secs, basis = _prior(db, row, line["model"], listed)
            out[row] = Expect(line["todo"] if row == line["stage"] else 0, secs, at_once, basis)
    if cfg.defaults.checker:
        secs, basis = _prior(db, "check", cfg.defaults.checker, None)
        drawn = out["keyframes"].items if "keyframes" in out else scenes  # each new picture is checked
        out["check"] = Expect(drawn, secs, CHECKS_AT_ONCE, basis)
    if kind == "render":
        out["clips"] = Expect(scenes, GUESS["clips"], Clips.CONCURRENT)
        out["mix"] = Expect(1, GUESS["mix"])
    return out


def _prior(db: Database, stage: str, model: str, listed: float | None) -> tuple[float, str]:
    if runs := db.step_seconds(stage, model, HISTORY):
        return statistics.median(runs), "history"
    if listed:
        return listed, "listed"
    return GUESS[stage], "guess"


def left(expect: dict[str, Expect], seen: dict[str, Seen]) -> tuple[float, float, dict[str, float]]:
    """The seconds the job has left, low and high, and each stage's time in all: run and to run, in
    the order the stages run."""
    lo = hi = 0.0
    whole: dict[str, float] = {}
    for stage in sorted(
        {*expect, *seen}, key=lambda s: list(LABELS).index(s) if s in LABELS else len(LABELS)
    ):
        e, s = expect.get(stage), seen.get(stage)
        at_once = e.at_once if e else 1
        if s and len(s.secs) >= MEASURED:
            per, basis = statistics.mean(s.secs), "job"
        elif e:
            per, basis = e.secs, e.basis
        else:
            per, basis = GUESS.get(stage, 0.0), "guess"
        items = s.left if s else e.items if e else 0
        t = math.ceil(items / at_once) * per * (1 - (s.at if s else 0.0))
        low, high = SPREAD[basis]
        lo += t * low
        hi += t * high * (2 if s and s.waiting else 1)
        whole[stage] = (s.elapsed if s else 0.0) + t
    return lo, hi, whole
