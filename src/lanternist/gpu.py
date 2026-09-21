"""One GPU, many models: a lease that clears the card before each stage.

On a 32 GB card the writer (Ollama), the keyframe model and LTX-2.5 cannot be resident together,
and ComfyUI and Ollama both keep models loaded after they finish. Before a stage runs, the lease
asks the others to unload, then waits until NVML reports enough free memory. One stage holds the
GPU at a time.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import Settings

log = logging.getLogger(__name__)
_lock = asyncio.Lock()


class GpuBusy(RuntimeError):
    pass


@dataclass
class GpuProc:
    pid: int
    used_gb: float
    cmd: str


@dataclass
class VramInfo:
    name: str
    total_gb: float
    free_gb: float
    procs: list[GpuProc]


def vram() -> VramInfo | None:
    try:
        import pynvml

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        name = pynvml.nvmlDeviceGetName(h)
        procs = []
        for p in pynvml.nvmlDeviceGetComputeRunningProcesses(h):
            try:
                cmd = Path(f"/proc/{p.pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()[:120]
            except OSError:
                cmd = "?"
            procs.append(GpuProc(p.pid, (p.usedGpuMemory or 0) / 2**30, cmd.strip()))
        return VramInfo(name if isinstance(name, str) else name.decode(), mem.total / 2**30, mem.free / 2**30, procs)
    except Exception as e:  # noqa: BLE001 - no NVIDIA driver, or NVML unavailable
        log.debug("nvml unavailable: %s", e)
        return None


async def unload_ollama(cfg: Settings, client: httpx.AsyncClient, keep: str | None = None):
    try:
        r = await client.get(f"{cfg.ollama.url}/api/ps", timeout=5)
        for m in r.json().get("models", []):
            if m["name"] != keep:
                await client.post(f"{cfg.ollama.url}/api/generate",
                                  json={"model": m["name"], "keep_alive": 0}, timeout=30)
                log.info("unloaded ollama model %s", m["name"])
    except httpx.HTTPError as e:
        log.debug("ollama not reachable: %s", e)


async def unload_comfyui(cfg: Settings, client: httpx.AsyncClient):
    try:
        await client.post(f"{cfg.comfyui.url}/free", json={"unload_models": True, "free_memory": True}, timeout=5)
    except httpx.HTTPError as e:
        log.debug("comfyui not reachable: %s", e)


def _owner_marker(cfg: Settings, owner: str) -> str | None:
    """A cmdline fragment identifying the owner's own process, whose VRAM counts as available to it."""
    if owner == "comfyui":
        return f"--port {urlparse(cfg.comfyui.url).port}"
    if owner == "ollama":
        return "ollama"
    return None


async def wait_free(need_gb: float, timeout: float = 90, own: str | None = None) -> None:
    deadline = time.monotonic() + timeout
    while True:
        info = vram()
        if info is None:
            return
        mine = sum(p.used_gb for p in info.procs if own and own in p.cmd)
        if info.free_gb + mine >= need_gb:
            return
        if time.monotonic() > deadline:
            holders = ", ".join(f"pid {p.pid} {p.used_gb:.1f} GB ({p.cmd[:60]})" for p in info.procs)
            raise GpuBusy(f"needs {need_gb:.0f} GB free VRAM, only {info.free_gb:.1f} GB after "
                          f"{timeout:.0f}s. Held by: {holders or 'unknown'}")
        await asyncio.sleep(1)


@asynccontextmanager
async def lease(cfg: Settings, owner: str, need_gb: float):
    """Hold the GPU for one stage. `owner` is 'ollama', 'comfyui', or a worker name."""
    async with _lock:
        if not cfg.fake_engines:
            async with httpx.AsyncClient() as client:
                if owner != "ollama":
                    await unload_ollama(cfg, client)
                if owner != "comfyui":
                    await unload_comfyui(cfg, client)
            await wait_free(need_gb, own=_owner_marker(cfg, owner))
        yield
