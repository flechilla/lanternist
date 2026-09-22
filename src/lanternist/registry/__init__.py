"""The model registry: every model the app can offer, local or remote, with its limits and price.

Entries live in the TOML files next to this module, one per capability. The pickers, the
estimator, the doctor and the engines all read them. On top of the shipped files:

- `<library>/models.toml` can re-price or disable an entry (`disabled = true`), or add one that
  points a known adapter family at a new endpoint;
- the `model_prices` table, filled by `lanternist models --sync`, adds what fal bills today and
  whether each endpoint is still active.

Two prices, on purpose. `price` is the list price per our unit (second of video, image, 1k
characters) with its tiers (audio on, resolution), read from each model page: estimates use it.
`billing` is fal's base price per *billing unit* from its pricing API. fal quotes one base price per
endpoint and bills options such as audio off or a lower resolution as fewer billable units, so
the actual cost of a request is its X-Fal-Billable-Units header times `billing`, never times the
list price. The two can differ (Veo's billing price is its audio-on list price; LTX bills in
cent-sized "units").

Writer models aren't listed here: they are whatever Ollama has pulled and OpenRouter offers.
"""

import asyncio
import copy
import logging
import re
import tomllib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)

HERE = Path(__file__).parent
SYNC_EVERY = timedelta(days=1)
_synced: dict[Path, datetime] = {}  # when each library's prices were last refreshed from fal
CAPABILITIES = ("writer.chat", "tts.speak", "image.keyframe", "video.image_to_video", "audio.ambience")
Capability = Literal["writer.chat", "tts.speak", "image.keyframe", "video.image_to_video", "audio.ambience"]
Provider = Literal["local", "ollama", "openrouter", "fal"]
Unit = Literal["output_second", "audio_second", "image", "megapixel", "1k_chars", "token"]


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit: Unit
    usd: Decimal | None = None  # list price per unit, remote models
    gpu_seconds: float | None = None  # GPU time per unit, local models
    tiers: dict[str, Decimal] = {}  # named alternatives: resolutions, audio on, a second endpoint
    first: Decimal | None = None  # the first unit of a request, when it costs more than the rest
    synced: date | None = None
    source: str = "registry"  # registry | fal_pricing_api
    until: date | None = None  # a launch price's last day; `then` applies from the day after
    then: "Price | None" = None

    def on(self, day: date | None = None) -> "Price":
        """The price that applies on `day` (today by default)."""
        if self.until and self.then and (day or date.today()) > self.until:
            return self.then.on(day)
        return self

    def per_unit(self, tier: str | None = None) -> Decimal | None:
        """USD per unit, for a named tier (a quality, a second endpoint) when it has its own price."""
        return self.tiers.get(tier, self.usd) if tier else self.usd


class Quality(BaseModel):
    """A request field a story may choose, such as the resolution. Each option not priced at the
    list price has its own entry in `price.tiers`."""

    model_config = ConfigDict(extra="forbid")
    param: str  # the request field, e.g. "resolution"
    options: list[str]
    default: str
    labels: dict[str, str] = {}  # how the picker names an option, when not by its value


class Billing(BaseModel):
    """fal's base price per billing unit for one endpoint, from its pricing API."""

    unit_price: Decimal
    unit: str  # fal's own unit name: seconds, megapixels, units, …
    synced: date


class Durations(BaseModel):
    """The clip lengths a video model bills, or LTX's frame rule when running locally."""

    model_config = ConfigDict(extra="forbid")
    values: list[float] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    frames: str | None = None  # "8k+1": any length, in frames
    fps: int | None = None
    max_seconds: float | None = None

    def lengths(self) -> list[float]:
        if self.values:
            return sorted(self.values)
        if self.min is not None and self.max is not None and self.step:
            n = round((self.max - self.min) / self.step)
            return [round(self.min + i * self.step, 3) for i in range(n + 1)]
        return []

    @property
    def longest(self) -> float | None:
        return self.max_seconds or (max(self.lengths()) if self.lengths() else None)


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    capability: Capability
    provider: Provider
    family: str | None = None  # which input builder a remote adapter uses
    endpoint: str | None = None  # the main endpoint of a remote model
    endpoints: dict[str, str] = {}  # extra endpoints by role, e.g. text_to_image, clone
    engine_id: str | None = None  # local models: the id inside every step key
    references: int = 0  # reference images a picture model accepts
    clone: bool = False  # narration: clones from a reference clip
    voices: list[str] = []  # narration: preset voice ids
    languages: list[str] = []  # narration: ISO 639-1 codes; empty means not listed
    max_chars: int | None = None  # narration: longest text per request
    audio: Literal["none", "ambience"] = "none"  # video: whether it makes its own sound bed
    durations: Durations | None = None
    seed: bool = False  # takes a seed input; without one, a re-roll still asks again
    quality: Quality | None = None
    defaults: dict = {}  # request fields always sent
    commercial_use: bool | Literal["below_10m_revenue"] = True
    licence: str = ""
    notes: str = ""
    status: str = "active"  # active | deprecated | unlisted, from fal's catalog
    price: Price
    billing: dict[str, Billing] = {}  # by endpoint role ("" for the main one), after a sync

    @property
    def remote(self) -> bool:
        return self.provider in ("openrouter", "fal")

    def pick_quality(self, wanted: str | None) -> str | None:
        """The quality to ask for: the one wanted if this model offers it, else its default."""
        if self.quality is None:
            return None
        return wanted if wanted in self.quality.options else self.quality.default

    def endpoint_for(self, role: str | None = None) -> str:
        if role is None:
            if not self.endpoint:
                raise KeyError(f"{self.id} has no endpoint")
            return self.endpoint
        return self.endpoints[role]

    def all_endpoints(self) -> dict[str | None, str]:
        out: dict[str | None, str] = {None: self.endpoint} if self.endpoint else {}
        return out | dict(self.endpoints)


@lru_cache
def _shipped() -> tuple[dict, ...]:
    out = []
    for path in sorted(HERE.glob("*.toml")):
        out.extend(tomllib.loads(path.read_text()).get("model", []))
    return tuple(out)


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def user_file(library: Path) -> Path:
    return library / "models.toml"


def _raw(library: Path | None) -> list[dict]:
    raw = {d["id"]: copy.deepcopy(d) for d in _shipped()}
    path = user_file(library) if library else None
    if path and path.is_file():
        for d in tomllib.loads(path.read_text()).get("model", []):
            mid = d.get("id")
            if not mid:
                continue
            if d.get("disabled"):
                raw.pop(mid, None)
                continue
            raw[mid] = _merge(raw[mid], d) if mid in raw else d
    return list(raw.values())


def load(library: Path | None = None, db=None) -> dict[str, ModelEntry]:
    """Every entry, with the user's overrides and, given the database, today's synced prices."""
    entries = {}
    for d in _raw(library):
        d = {k: v for k, v in d.items() if k != "disabled"}
        entries[d["id"]] = ModelEntry.model_validate(d)
    if db is not None:
        for key, row in db.latest_prices().items():
            mid, _, role = key.partition("#")
            e = entries.get(mid)
            if e is None:
                continue
            if not role:
                e.status = row.status
            e.billing[role] = Billing(
                unit_price=Decimal(row.unit_price), unit=row.unit, synced=row.synced_at.date()
            )
    return entries


def get(model_id: str, library: Path | None = None, db=None) -> ModelEntry:
    entries = load(library, db)
    if model_id not in entries:
        raise KeyError(f"no model '{model_id}' in the registry (known: {', '.join(sorted(entries))})")
    return entries[model_id]


def billing(db, model_id: str, role: str | None = None) -> Billing | None:
    """What fal bills per unit for one of a model's endpoints, as last synced; None before a sync."""
    row = db.latest_prices().get(model_id if not role else f"{model_id}#{role}")
    if row is None:
        return None
    return Billing(unit_price=Decimal(row.unit_price), unit=row.unit, synced=row.synced_at.date())


def by_capability(capability: str, library: Path | None = None, db=None) -> list[ModelEntry]:
    return [e for e in load(library, db).values() if e.capability == capability]


def normalise_unit(unit: str) -> str:
    """Map a unit name from fal's pricing API onto ours; unknown names come back as they are."""
    u = unit.strip().lower()
    if re.search(r"megapixel|\bmp\b", u):
        return "megapixel"
    if re.search(r"1k|1,?000|thousand", u) and "char" in u:
        return "1k_chars"
    if "second" in u:
        return "output_second"
    if "image" in u:
        return "image"
    if "token" in u:
        return "token"
    if "minute" in u:
        return "minute"
    return u


async def sync_prices(cfg, db, fal=None) -> list[dict]:
    """Read today's price and status of every fal endpoint in the registry into `model_prices`."""
    from ..providers.fal import Fal

    fal = fal or Fal(cfg, db)
    entries = [e for e in load(cfg.library).values() if e.provider == "fal"]
    targets = [(e, role, ep) for e in entries for role, ep in e.all_endpoints().items()]
    endpoints = sorted({ep for *_, ep in targets})
    prices, catalog = await asyncio.gather(fal.pricing(endpoints), fal.catalog(endpoints))
    lines = []
    for e, role, ep in targets:
        key = e.id if role is None else f"{e.id}#{role}"
        meta = catalog.get(ep)
        status = (meta or {}).get("status") or ("unlisted" if meta is None else "active")
        p = prices.get(ep)
        if p is None:
            lines.append(
                {
                    "model": key,
                    "endpoint": ep,
                    "status": status,
                    "price": None,
                    "unit": None,
                    "api_unit": None,
                    "changed": False,
                    "matches": False,
                }
            )
            continue
        api_unit = str(p.get("unit", ""))
        changed = db.record_price(
            key,
            api_unit,
            str(p["unit_price"]),
            "fal_pricing_api",
            endpoint=ep,
            currency=p.get("currency") or "USD",
            status=status,
        )
        lines.append(
            {
                "model": key,
                "endpoint": ep,
                "status": status,
                "price": p["unit_price"],
                "api_unit": api_unit,
                "changed": changed,
                "drift": _drift(e, role, api_unit, p["unit_price"]),
            }
        )
    return lines


async def ensure_synced(cfg, db) -> None:
    """Refresh what fal bills, at most once a day per library, before remote steps run: actual
    costs are billable units times these prices. A failed refresh only leaves yesterday's prices
    in use, so it's logged, not raised."""
    from ..providers import ProviderError

    last = _synced.get(cfg.library)
    if last and datetime.now(UTC) - last < SYNC_EVERY:
        return
    try:
        await sync_prices(cfg, db)
    except (ProviderError, httpx.HTTPError) as e:
        log.warning("couldn't refresh fal's prices (%s); costs use the last ones synced", e)
        return
    _synced[cfg.library] = datetime.now(UTC)


def _drift(e: ModelEntry, role: str | None, api_unit: str, api_price) -> str | None:
    """Why fal's billing price doesn't line up with any list price, if it doesn't; None when it does.

    Only comparable when fal bills in our unit. A base price that matches no list tier usually means
    the model page changed: re-read it and update the registry."""
    price_now = e.price.on()
    if normalise_unit(api_unit) != price_now.unit:
        return None
    listed = (
        {price_now.usd, price_now.first, *price_now.tiers.values()}
        if role is None
        else {price_now.tiers.get(role)}
    )
    price = Decimal(str(api_price))
    if any(v is not None and abs(v - price) < Decimal("0.0000005") for v in listed):
        return None
    shown = ", ".join(f"${v.normalize()}" for v in sorted(v for v in listed if v is not None))
    return f"fal bills ${price.normalize()} per {api_unit}, which matches no list price ({shown})"
