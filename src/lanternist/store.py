"""Content-addressed assets and the step cache: a folder locally, R2 and the database in hosted.

The folder (the local edition's library, and the hosted edition's disk cache):

    assets/ab/<sha256>.<ext>    every image, wav and mp4, named by its content
    steps/ab/<key>.json         one record per finished step: its outputs and metadata
    derived/ab/<sha256>-<name>  files made from an asset for the pages, such as a smaller picture

The hosted edition keeps its files on R2 (plans/STORAGE_PLAN.md), under a prefix per owner, and its
step records in the `steps` table. ffmpeg reads files, so the folder stays, as a cache of what the jobs
on this machine read and made:

    u/<owner>/assets/ab/<sha256>.<ext>     shared/… for what everyone shares (voice samples)
    u/<owner>/derived/ab/<sha256>-<name>
    scratch/u/<owner>/ab/<sha256>.<ext>    ffmpeg's scene clips: the bucket deletes them after 7 days

A step's key hashes everything that decides its output (kind, engine and version, parameters,
the final prompt, the seed, upstream asset hashes), so an edit re-runs exactly the steps it
reaches and nothing else.
"""

import asyncio
import hashlib
import json
import mimetypes
import os
import shutil
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Settings
from .db import EVERYONE, Database, now
from .providers.s3 import S3, attachment

IMMUTABLE = "private, max-age=31536000, immutable"  # an asset never changes under its name, nor a thumbnail
URL_SECONDS = 2 * 3600  # signed at the top of the hour: every address handed out has at least an hour left
SCRATCH_RECORD = timedelta(days=6)  # a day under the bucket's 7-day rule, so no record outlives its files
RECENT = 3600  # seconds: a file used this recently may be read by a running job, so the cache keeps it
TRIM_TO = 0.8  # of [storage] cache_gb, once the cache is over it
TYPES = {".vtt": "text/vtt", ".srt": "application/x-subrip"}  # what mimetypes may not know


class StoreError(RuntimeError):
    pass


def step_key(kind: str, **inputs) -> str:
    blob = json.dumps({"kind": kind, **inputs}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def content_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return TYPES.get(suffix) or mimetypes.guess_type(name)[0] or "application/octet-stream"


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.assets = self.root / "assets"
        self.steps = self.root / "steps"
        self.tmp_root = self.root / "tmp"
        for d in (self.assets, self.steps, self.tmp_root):
            d.mkdir(parents=True, exist_ok=True)

    # assets ---------------------------------------------------------------------------------
    async def put(self, src: Path, move: bool = True, scratch: bool = False) -> str:  # noqa: ARG002 - R2's to act on; a folder keeps all
        """Add a file; returns its asset id '<sha>.<ext>'. `scratch`: ffmpeg can make it again for
        nothing, so the hosted store lets it expire."""
        src = Path(src)
        sha = file_sha(src)
        ext = src.suffix.lstrip(".").lower() or "bin"
        asset = f"{sha}.{ext}"
        dest = self.path(asset)
        if dest.exists():
            if move:
                src.unlink()
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            (shutil.move if move else shutil.copy2)(src, dest)
        return asset

    def path(self, asset: str) -> Path:
        return self.assets / asset[:2] / asset

    async def file(self, asset: str) -> Path:
        """The asset as a file on this machine, for a stage to read."""
        return self.path(asset)

    async def files(self, assets: list[str]) -> list[Path]:
        return list(await asyncio.gather(*(self.file(a) for a in assets)))

    def sha(self, asset: str) -> str:
        return asset.split(".", 1)[0]

    def derived(self, asset: str, name: str) -> Path:
        """Where a file made from an asset is kept, such as a smaller copy of a picture: beside the
        assets, named by the asset and what it is, so it's made once."""
        return self.root / "derived" / asset[:2] / f"{self.sha(asset)}-{name}"

    async def put_derived(self, asset: str, name: str, src: Path) -> Path:
        path = self.derived(asset, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        src.replace(path)  # whole or not at all, if two pages ask at once
        return path

    # steps ----------------------------------------------------------------------------------
    def _step_path(self, key: str) -> Path:
        return self.steps / key[:2] / f"{key}.json"

    def get_step(self, key: str) -> dict | None:
        p = self._step_path(key)
        if not p.is_file():
            return None
        record = json.loads(p.read_text())
        # A record whose assets were deleted is a miss, not an error.
        if all(self.path(a).is_file() for a in record.get("assets", {}).values()):
            return record
        return None

    def get_steps(self, keys: list[str]) -> dict[str, dict]:
        """The records of these steps that the cache holds, by key."""
        return {k: rec for k in keys if (rec := self.get_step(k))}

    def put_step(self, key: str, record: dict, scratch: bool = False) -> dict:  # noqa: ARG002 - as in put
        p = self._step_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, indent=1)
        os.replace(tmp, p)
        return record

    def tmp(self) -> Path:
        return Path(tempfile.mkdtemp(dir=self.tmp_root))


def _prefix(owner: str | None) -> str:
    return "shared" if owner is None else f"u/{owner}"


def asset_key(owner: str | None, asset: str) -> str:
    """Where an owner's asset is on R2; owner None for what everyone shares."""
    return f"{_prefix(owner)}/assets/{asset[:2]}/{asset}"


def scratch_key(owner: str | None, asset: str) -> str:
    return f"scratch/{_prefix(owner)}/{asset[:2]}/{asset}"


def derived_key(owner: str | None, asset: str, name: str) -> str:
    return f"{_prefix(owner)}/derived/{asset[:2]}/{asset.split('.', 1)[0]}-{name}"


def presigned(s3: S3, key: str, download: str | None = None) -> tuple[str, int]:
    """A presigned GET of `key` for the browser, and how many seconds the redirect to it may be kept.
    It's signed at the top of the hour, so every request that hour gets the same address, and the
    browser's cache keeps working."""
    at = datetime.now(UTC)
    hour = at.replace(minute=0, second=0, microsecond=0)
    url = s3.presign(key, hour, URL_SECONDS, attachment(download) if download else None)
    return url, 3600 - int((at - hour).total_seconds())


class R2Store(Store):
    """The hosted store: files on R2 under the owner's prefix, this folder as their disk cache, and the
    step records in the database. A record is written only once R2 has its files, so a record found
    means the files are there, and nothing needs asking R2 first."""

    def __init__(self, cache: Path, s3: S3, db: Database, owner: str | None):
        super().__init__(cache)
        self.s3, self.db, self.owner = s3, db, owner  # None: what everyone shares
        self.records_owner = EVERYONE if owner is None else owner  # whose step records these are

    async def put(self, src: Path, move: bool = True, scratch: bool = False) -> str:
        """Always uploaded, even when the cache had it: a scratch file's 7 days start again."""
        asset = await super().put(src, move)
        key = scratch_key(self.owner, asset) if scratch else asset_key(self.owner, asset)
        await self.s3.put(key, self.path(asset), self.sha(asset), content_type(asset), IMMUTABLE)
        return asset

    async def file(self, asset: str) -> Path:
        path = self.path(asset)
        if path.is_file():
            path.touch()  # used now, so trim keeps it
            return path
        if await self.s3.get(asset_key(self.owner, asset), path) or await self.s3.get(
            scratch_key(self.owner, asset), path
        ):
            return path
        raise StoreError(
            f"{asset} is on neither this machine nor R2 (under {_prefix(self.owner)}/), though a step record names it"
        )

    async def put_derived(self, asset: str, name: str, src: Path) -> Path:
        path = await super().put_derived(asset, name, src)
        await self.s3.put(
            derived_key(self.owner, asset, name), path, file_sha(path), content_type(name), IMMUTABLE
        )
        return path

    def get_step(self, key: str) -> dict | None:
        return self.get_steps([key]).get(key)

    def get_steps(self, keys: list[str]) -> dict[str, dict]:
        return self.db.get_steps(self.records_owner, keys)

    def put_step(self, key: str, record: dict, scratch: bool = False) -> dict:
        self.db.put_step(self.records_owner, key, record, now() + SCRATCH_RECORD if scratch else None)
        return record


def of(cfg: Settings, db: Database | None, owner: str | None) -> Store:
    """The owner's store, or with owner None the one everyone shares (voice samples): the library
    folder locally, R2 in hosted."""
    root = cfg.library_for(owner)
    if not cfg.hosted_edition:
        return Store(root)
    if db is None:
        raise StoreError("the hosted store keeps its step records in the database: make it with one")
    return R2Store(root, S3(cfg), db, owner)


def trim(cfg: Settings) -> int:
    """Keep the hosted disk cache under [storage] cache_gb: once it's over, delete the least recently used
    files until it's down to TRIM_TO of it, and never one used in the last hour. Returns the bytes freed."""
    files = []
    for base in (cfg.library / "u", cfg.library / "shared"):
        for p in base.rglob("*") if base.is_dir() else ():
            if p.is_file() and "tmp" not in p.relative_to(base).parts:
                st = p.stat()
                files.append((st.st_mtime, st.st_size, p))
    total, limit = sum(size for _, size, _ in files), cfg.storage.cache_gb * 1e9
    if total <= limit:
        return 0
    freed, recent = 0, time.time() - RECENT
    for used, size, p in sorted(files):
        if total - freed <= limit * TRIM_TO or used > recent:
            break
        p.unlink(missing_ok=True)
        freed += size
    return freed


async def forget(cfg: Settings, db: Database, owner: str) -> None:
    """Delete everything an account stored: its files on R2, under both of its prefixes, its step records
    and its disk cache. Running it again finds nothing more to delete. Phase I's account deletion calls
    it, with the account's stories."""
    s3 = S3(cfg)
    for prefix in (f"{_prefix(owner)}/", f"scratch/{_prefix(owner)}/"):
        await s3.delete_prefix(prefix)
    db.forget_steps(owner)
    shutil.rmtree(cfg.library_for(owner), ignore_errors=True)
