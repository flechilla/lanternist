"""The model registry: every model the app can offer, local or remote, with its limits and price.

Entries live in the TOML files next to this module, one per capability. The pickers, the
estimator, the doctor and the engines all read them. On top of the shipped files:

- `<library>/models.toml` can re-price or disable an entry (`disabled = true`), or add one that
  points a known adapter family at a new endpoint;
- the `model_prices` table, filled by `lanternist models --sync`, overrides the base price and
  status of fal endpoints with what fal's pricing API and catalog say today.

Writer models aren't listed here: they are whatever Ollama has pulled and OpenRouter offers.
"""

import asyncio
import copy
import re
import tomllib
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

HERE = Path(__file__).parent
CAPABILITIES = ("writer.chat", "tts.speak", "image.keyframe", "video.image_to_video", "audio.ambience")
Capability = Literal["writer.chat", "tts.speak", "image.keyframe", "video.image_to_video", "audio.ambience"]
Provider = Literal["local", "ollama", "openrouter", "fal"]
Unit = Literal["output_second", "audio_second", "image", "megapixel", "1k_chars", "token"]


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit: Unit
    usd: Decimal | None = None             # list price per unit, remote models
    gpu_seconds: float | None = None       # GPU time per unit, local models
    tiers: dict[str, Decimal] = {}         # named alternatives: resolutions, audio on, a second endpoint
    synced: date | None = None
    source: str = "registry"               # registry | fal_pricing_api


class Durations(BaseModel):
    """The clip lengths a video model bills, or LTX's frame rule when running locally."""
    model_config = ConfigDict(extra="forbid")
    values: list[float] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    frames: str | None = None              # "8k+1": any length, in frames
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
    family: str | None = None              # which input builder a remote adapter uses
    endpoint: str | None = None            # the main endpoint of a remote model
    endpoints: dict[str, str] = {}         # extra endpoints by role, e.g. text_to_image, clone
    engine_id: str | None = None           # local models: the id inside every step key
    references: int = 0                    # reference images a picture model accepts
    clone: bool = False                    # narration: clones from a reference clip
    voices: list[str] = []                 # narration: preset voice ids
    languages: list[str] = []              # narration: ISO 639-1 codes; empty means not listed
    max_chars: int | None = None           # narration: longest text per request
    audio: Literal["none", "ambience"] = "none"   # video: whether it makes its own sound bed
    durations: Durations | None = None
    defaults: dict = {}                    # request fields always sent
    commercial_use: bool | Literal["below_10m_revenue"] = True
    licence: str = ""
    notes: str = ""
    status: str = "active"                 # active | deprecated, from fal's catalog
    price: Price

    @property
    def remote(self) -> bool:
        return self.provider in ("openrouter", "fal")

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
            e.status = row.status
            if row.unit != e.price.unit:
                continue   # the pricing API's unit doesn't match ours: keep the list price
            if role:
                e.price.tiers[role] = Decimal(row.unit_price)
            else:
                e.price.usd, e.price.source = Decimal(row.unit_price), row.source
                e.price.synced = row.synced_at.date()
    return entries


def get(model_id: str, library: Path | None = None, db=None) -> ModelEntry:
    entries = load(library, db)
    if model_id not in entries:
        raise KeyError(f"no model '{model_id}' in the registry (known: {', '.join(sorted(entries))})")
    return entries[model_id]


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
            lines.append({"model": key, "endpoint": ep, "status": status, "price": None, "unit": None,
                          "api_unit": None, "changed": False, "matches": False})
            continue
        unit = normalise_unit(str(p.get("unit", "")))
        changed = db.record_price(key, unit, str(p["unit_price"]), "fal_pricing_api", endpoint=ep,
                                  currency=p.get("currency") or "USD", status=status)
        lines.append({"model": key, "endpoint": ep, "status": status, "price": p["unit_price"], "unit": unit,
                      "api_unit": p.get("unit"), "changed": changed, "matches": unit == e.price.unit})
    return lines
