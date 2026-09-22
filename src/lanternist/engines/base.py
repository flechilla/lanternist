"""The engine interface: every stage runs a local or a remote model through the same three calls.

A stage builds one Item per output it needs, serves the ones the step cache already holds, and
hands the rest to its engine as one batch:

    key(kind, **inputs)       the step key; the engine adds what's model-specific
    estimate(items)           what the batch would cost, from list prices; pure
    run(items, ctx, on_item)  make them; `on_item` fires as each output lands

A local engine loads its model once for the whole batch, under the GPU lease. A remote one runs the
items concurrently under its provider's semaphore and never takes the lease.

An item can wait on another in the same batch (`after`): keyframes on a cast sheet drawn in the
same job. Its key and references are only known once that output is stored, so the engine calls
`ctx.bind(item)` first: a remote engine before submitting it, a local one when its output arrives
(the worker reads the reference straight from the work dir).
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from .. import registry
from ..config import Settings
from ..db import Database, to_micros
from ..providers.fal import Fal, FalResult, RunSpec
from ..registry import ModelEntry
from ..store import Store

log = logging.getLogger(__name__)

CAST_SIZE = (1024, 1024)
PORTRAIT_SIZE = (768, 1024)  # one character, full length
MAX_REFS = 3  # portraits a picture is drawn from; a crowd gets the whole cast sheet instead


def keyframe_size(cfg: Settings) -> tuple[int, int]:
    # klein wants sides divisible by 16: 1920x1080 is drawn at 1920x1088 and cropped when framed.
    r = cfg.render
    return (r.width + 15) // 16 * 16, (r.height + 15) // 16 * 16


@dataclass
class Item:
    id: str  # "cast", "s003": names its work files
    key: str | None  # the step key; None until the item it waits on is stored
    scene: int | None = None
    params: dict = field(default_factory=dict)  # prompt, seed, size, refs, chunks, shots, …
    after: str | None = None  # an item in the same batch whose output this one needs
    stage: str | None = None  # the progress row it reports under, when not its stage's own


@dataclass
class Output:
    item: Item
    path: Path
    meta: dict = field(default_factory=dict)  # kept in the step record
    secs: float | None = None  # how long it took: GPU seconds for a local engine
    extra: dict[str, Path] = field(default_factory=dict)  # more files the step makes, by asset name


@dataclass
class Estimate:
    """What a batch would cost at list prices. Local engines cost GPU time instead of money."""

    items: int = 0
    units: Decimal = Decimal(0)  # in the price's unit
    micros: int = 0
    gpu_seconds: float = 0.0
    paid_seconds: float = 0.0  # video: seconds billed
    waste_seconds: float = 0.0  # video: seconds billed and then trimmed away

    def __add__(self, other: "Estimate") -> "Estimate":
        return Estimate(
            self.items + other.items,
            self.units + other.units,
            self.micros + other.micros,
            round(self.gpu_seconds + other.gpu_seconds, 1),
            round(self.paid_seconds + other.paid_seconds, 3),
            round(self.waste_seconds + other.waste_seconds, 3),
        )


def gpu_estimate(entry: ModelEntry, units: float, items: int) -> Estimate:
    """A local model's estimate: its registry GPU seconds per unit, and no money."""
    per = entry.price.gpu_seconds or 0.0
    return Estimate(items=items, units=Decimal(str(round(units, 3))), gpu_seconds=round(per * units, 1))


def _unbound(item: Item) -> None:
    raise RuntimeError(f"{item.id} waits on {item.after}, but its stage gave no way to bind it")


@dataclass
class StepContext:
    """What one batch runs with: where to write, whom to tell, and whose job it is."""

    cfg: Settings
    store: Store
    work: Path
    stage: str
    db: Database | None = None
    story_id: str | None = None
    job_id: str | None = None
    user_cancelled: Callable[[], bool] = lambda: False
    note: Callable[[str, int | None], None] = lambda message, scene: None  # a progress line
    bind: Callable[[Item], None] = _unbound


OnItem = Callable[[Output], None]


class Maker:
    """Whatever a stage hands its batch to: a model's engine, or ffmpeg for clips and the mix."""

    remote = False
    model_id: str | None = None  # the registry id, for the step_runs rows of local models

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        raise NotImplementedError


class Engine(Maker):
    """One model from the registry, for one capability."""

    def __init__(self, cfg: Settings, entry: ModelEntry):
        self.cfg, self.entry = cfg, entry
        self.model_id = entry.id

    def key(self, kind: str, **inputs) -> str:
        raise NotImplementedError

    def estimate(self, items: list[Item]) -> Estimate:
        raise NotImplementedError


class TtsEngine(Engine):
    """Narration: a scene's words go out as chunks, each synthesised on its own."""

    def chunks(self, words: str) -> list[str]:
        raise NotImplementedError


class VideoEngine(Engine):
    """Image-to-video: a clip longer than one generation is cut into shots chained on last frames."""

    def shots(self, seconds: float) -> list[float]:
        raise NotImplementedError


class FalEngine(Engine):
    """A model on fal: requests go through the queue client, which logs each one in step_runs before
    polling it, resumes it after a restart, and cancels it only on the user's cancel."""

    remote = True
    version = 1  # in every step key: bump it when the request an adapter builds changes on purpose

    def __init__(self, cfg: Settings, entry: ModelEntry, db: Database | None, quality: str | None = None):
        super().__init__(cfg, entry)
        self.db = db
        self.quality = entry.pick_quality(quality)
        self._fal: Fal | None = None
        self._uploads: dict[str, asyncio.Future[str]] = {}

    @property
    def engine_id(self) -> str:
        return f"{self.entry.id}@{self.version}"

    @property
    def fal(self) -> Fal:
        # Made on first use, so estimating and keying never need the key.
        if self._fal is None:
            self._fal = Fal(self.cfg, self.db)
        return self._fal

    def options(self) -> dict:
        """The request fields the model decides: its defaults and the chosen quality."""
        q = self.entry.quality
        return self.entry.defaults | ({q.param: self.quality} if q else {})

    def unit_price(self, tier: str | None = None) -> Decimal:
        return self.entry.list_price(tier)

    def micros(self, units: Decimal | float, tier: str | None = None) -> int:
        return to_micros(Decimal(str(units)) * self.unit_price(tier))

    async def request(
        self, ctx: StepContext, item: Item, arguments: dict, role: str | None = None, estimate: int = 0
    ) -> FalResult:
        """Run one request for `item`, reporting its place in fal's queue as a progress line."""
        endpoint = self.entry.endpoint_for(role)
        # Read at request time: the stage may have just refreshed what fal bills.
        billing = registry.billing(self.db, self.entry.id, role) if self.db else None
        seen: dict[str, object] = {}
        where = f"scene {item.scene}" if item.scene is not None else item.id.replace("_", " ")

        def on_status(status: str, d: dict) -> None:
            now = (status, d.get("queue_position"))
            if seen.get("last") == now:
                return
            seen["last"] = now
            if status == "IN_QUEUE":
                pos = d.get("queue_position")
                ctx.note(f"{where}: waiting at fal" + (f", {pos} ahead" if pos else ""), item.scene)
            elif status == "IN_PROGRESS":
                ctx.note(f"{where}: generating at fal", item.scene)

        spec = RunSpec(
            stage=item.stage or ctx.stage,
            model_id=self.entry.id,
            story_id=ctx.story_id,
            job_id=ctx.job_id,
            scene=item.scene,
            step_key=item.key,
            unit=billing.unit if billing else self.entry.price.unit,
            unit_price=billing.unit_price if billing else None,
            estimate_micros=estimate,
            user_cancelled=ctx.user_cancelled,
        )
        t0 = time.monotonic()
        res = await self.fal.run(endpoint, arguments, spec, on_status=on_status)
        log.info("%s %s done in %.1fs", self.entry.id, item.id, time.monotonic() - t0)
        return res

    async def fetch(self, url: str, dest: Path) -> Path:
        """Download a result into the work dir, keeping the extension fal gave it."""
        suffix = Path(urlparse(url).path).suffix.lower()
        return await self.fal.download(url, dest.with_suffix(suffix) if suffix else dest)

    async def upload(
        self, ctx: StepContext, asset: str, ttl_hours: float | None = None, path: Path | None = None
    ) -> str:
        """Put a stored file (or `path`, named `asset`) on fal. Items running together share one upload
        of the same file: every keyframe waits on the one cast sheet upload rather than starting its own."""
        if asset not in self._uploads:
            self._uploads[asset] = asyncio.ensure_future(
                self.fal.upload(path or ctx.store.path(asset), asset=asset, ttl_hours=ttl_hours)
            )
        try:
            return await asyncio.shield(self._uploads[asset])
        except Exception:
            self._uploads.pop(asset, None)  # a failed upload is tried afresh next time
            raise


async def gather_all(jobs: list) -> None:
    """Run coroutines together and let every one finish before raising the first failure: a scene
    fal refuses shouldn't throw away the scenes already paid for, which are stored as they land."""
    results = await asyncio.gather(*jobs, return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException):
            raise r
