"""Content-addressed assets and the step cache, both plain files under the library folder.

    assets/ab/<sha256>.<ext>    every image, wav and mp4, named by its content
    steps/ab/<key>.json         one record per finished step: its outputs and metadata
    derived/ab/<sha256>-<name>  files made from an asset for the pages, such as a smaller picture

A step's key hashes everything that decides its output (kind, engine and version, parameters,
the final prompt, the seed, upstream asset hashes), so an edit re-runs exactly the steps it
reaches and nothing else.
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


def step_key(kind: str, **inputs) -> str:
    blob = json.dumps({"kind": kind, **inputs}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.assets = self.root / "assets"
        self.steps = self.root / "steps"
        self.tmp_root = self.root / "tmp"
        for d in (self.assets, self.steps, self.tmp_root):
            d.mkdir(parents=True, exist_ok=True)

    # assets ---------------------------------------------------------------------------------
    def put(self, src: Path, move: bool = True) -> str:
        """Add a file; returns its asset id '<sha>.<ext>'."""
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

    def sha(self, asset: str) -> str:
        return asset.split(".", 1)[0]

    def derived(self, asset: str, name: str) -> Path:
        """Where a file made from an asset is kept, such as a smaller copy of a picture: beside the
        assets, named by the asset and what it is, so it's made once."""
        return self.root / "derived" / asset[:2] / f"{self.sha(asset)}-{name}"

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

    def put_step(self, key: str, record: dict) -> dict:
        p = self._step_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, indent=1)
        os.replace(tmp, p)
        return record

    def tmp(self) -> Path:
        return Path(tempfile.mkdtemp(dir=self.tmp_root))
