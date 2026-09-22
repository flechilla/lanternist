"""Health checks: is everything a film needs installed, reachable and ready on this machine?"""

import asyncio
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from . import registry
from .config import Settings
from .gpu import vram
from .keys import LABELS, get_key
from .voices import find_voice

LTX_NODES = [
    "LTXVImgToVideoInplace",
    "LTXVConcatAVLatent",
    "LTXVDualCFGGuider",
    "LTXVLatentUpsampler",
    "LTXVAudioVAEDecode",
    "LTXVEmptyLatentAudio",
    "SaveVideo",
    "CreateVideo",
]


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str

    def dict(self):
        return asdict(self)


def _out(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


async def _py(python, code: str, timeout: float = 120) -> tuple[bool, str]:
    if not python.is_file():
        return False, f"no interpreter at {python}"
    proc = await asyncio.create_subprocess_exec(
        str(python), "-c", code, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return False, "timed out"
    if proc.returncode:
        return False, err.decode(errors="replace").strip().splitlines()[-1][:300]
    return True, out.decode().strip()


def needs(cfg: Settings) -> dict[str, bool]:
    """Which engines and providers the default models use, the picture check among them; the checks for
    the rest are advisory."""
    d = cfg.defaults
    llms = (d.writer, d.checker)
    # Ambience only runs for a video model that makes no sound of its own.
    silent = registry.get(d.video, cfg.library).audio == "none"
    media = (d.tts, d.image, d.video, d.ambience if silent else "none")
    local = {
        "qwen3tts": d.tts.startswith("local/"),
        "klein": d.image.startswith("local/"),
        "comfyui": d.video.startswith("local/"),
        "ollama": not d.writer or any(m.startswith("ollama/") for m in llms),
    }
    return local | {
        "gpu": any(local.values()),
        "ram": local["klein"],
        "voice": registry.get(d.tts, cfg.library).clone,  # a narrator with presets needs no recording
        "openrouter": any(m.startswith("openrouter/") for m in llms),
        "fal": any(m.startswith("fal/") for m in media),
    }


async def provider_rows(cfg: Settings) -> list[dict]:
    """Each remote provider: is there a key, where it's from, and does the provider accept it."""
    from .providers.fal import Fal
    from .providers.openrouter import OpenRouter

    need = needs(cfg)

    async def one(name: str) -> dict:
        key = get_key(name, fake=cfg.fake_engines)
        row = {
            "name": name,
            "label": LABELS[name],
            "configured": bool(key.value),
            "source": key.source,
            "last4": key.last4,
            "ok": None,
            "detail": "",
            "needed": need[name],
            "usage": None,
        }
        if not key.value:
            row["detail"] = "no key"
            return row
        if name == "openrouter":
            ok, detail, info = await OpenRouter(cfg, key.value).check()
            row["usage"] = {k: info.get(k) for k in ("usage", "limit", "limit_remaining")} if info else None
        else:
            ok, detail = await Fal(cfg, None, key.value).check()
        row["ok"], row["detail"] = ok, detail
        return row

    return list(await asyncio.gather(one("openrouter"), one("fal")))


def _ram() -> tuple[str, str]:
    """(status, detail) for the RAM that klein's CPU offload needs."""
    mem = re.search(r"MemAvailable:\s+(\d+)", Path("/proc/meminfo").read_text())
    if mem is None:
        return "warn", "couldn't read MemAvailable from /proc/meminfo"
    avail = int(mem.group(1)) / 1e6
    if avail < 40:
        return "warn", f"{avail:.0f} GB available; klein's CPU offload wants about 40 GB"
    return "ok", f"{avail:.0f} GB available"


async def run_checks(cfg: Settings) -> list[Check]:
    checks: list[Check] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append(Check(name, status, detail))

    if cfg.fake_engines:
        add("mode", "warn", "LANTERNIST_FAKE_ENGINES=1: every model is replaced by test patterns and tones")

    # GPU and memory
    info = vram()
    if info is None:
        add("gpu", "fail", "no NVIDIA GPU visible through NVML")
    else:
        holders = ", ".join(
            f"{p.used_gb:.1f} GB {p.cmd.split()[0].rsplit('/', 1)[-1] if p.cmd else '?'}"
            for p in sorted(info.procs, key=lambda p: -p.used_gb)[:4]
        )
        add(
            "gpu",
            "ok",
            f"{info.name}, {info.free_gb:.1f} of {info.total_gb:.1f} GB free"
            + (f" (held: {holders}; freed per stage)" if holders else ""),
        )
    add("ram", *_ram())

    # ffmpeg
    if not shutil.which("ffmpeg"):
        add("ffmpeg", "fail", "ffmpeg not on PATH")
    else:
        enc, flt = await asyncio.gather(
            asyncio.to_thread(_out, ["ffmpeg", "-hide_banner", "-encoders"]),
            asyncio.to_thread(_out, ["ffmpeg", "-hide_banner", "-filters"]),
        )
        missing = [f for f in ("xfade", "zoompan", "subtitles", "amix", "adelay") if f" {f} " not in flt]
        ok_enc = cfg.render.encoder in enc
        add(
            "ffmpeg",
            "ok" if ok_enc and not missing else "fail",
            f"encoder {cfg.render.encoder} {'found' if ok_enc else 'MISSING (set render.encoder = libx264)'}"
            + (f"; missing filters: {', '.join(missing)}" if missing else "; filters ok"),
        )
    fonts = await asyncio.to_thread(_out, ["fc-list"]) if shutil.which("fc-list") else ""
    add(
        "fonts",
        "ok" if "Noto Sans" in fonts else "warn",
        "Noto Sans found for subtitles"
        if "Noto Sans" in fonts
        else "Noto Sans not found; subtitles use a fallback font",
    )

    async with httpx.AsyncClient(timeout=5) as client:
        # Ollama
        try:
            tags = (await client.get(f"{cfg.ollama.url}/api/tags")).json()
            names = [m["name"] for m in tags.get("models", [])]
            add(
                "ollama",
                "ok" if cfg.ollama.model in names else "fail",
                f"{cfg.ollama.model} {'present' if cfg.ollama.model in names else 'NOT pulled'} "
                f"({len(names)} models at {cfg.ollama.url})",
            )
        except httpx.HTTPError as e:
            add("ollama", "fail", f"not reachable at {cfg.ollama.url}: {e.__class__.__name__}")

        # ComfyUI + LTX
        try:
            stats = (await client.get(f"{cfg.comfyui.url}/system_stats")).json()
            version = stats.get("system", {}).get("comfyui_version", "?")
            want = {
                "diffusion_models": cfg.engines.ltx.unet,
                "text_encoders": cfg.engines.ltx.text_encoder,
                "vae": cfg.engines.ltx.vae,
                "latent_upscale_models": cfg.engines.ltx.upscaler,
            }
            missing = []
            for folder, name in want.items():
                files = (await client.get(f"{cfg.comfyui.url}/models/{folder}")).json()
                if name not in files:
                    missing.append(name)
            if cfg.engines.ltx.audio_vae not in (await client.get(f"{cfg.comfyui.url}/models/vae")).json():
                missing.append(cfg.engines.ltx.audio_vae)
            nodes = (await client.get(f"{cfg.comfyui.url}/object_info", timeout=30)).json()
            missing_nodes = [n for n in LTX_NODES if n not in nodes]
            bad = missing or missing_nodes
            add(
                "comfyui",
                "fail" if bad else "ok",
                f"ComfyUI {version} at {cfg.comfyui.url}; "
                + (
                    f"missing: {', '.join(missing + missing_nodes)}"
                    if bad
                    else "LTX-2.5 weights and nodes present"
                ),
            )
        except httpx.HTTPError as e:
            add(
                "comfyui",
                "fail",
                f"not reachable at {cfg.comfyui.url}: {e.__class__.__name__}. Start it with: "
                f"cd {cfg.comfyui.root} && .venv/bin/python main.py --listen 127.0.0.1 --port 8199",
            )

    # Worker venvs
    tts, klein = cfg.engines.qwen3tts, cfg.engines.klein
    ok, out = await _py(tts.python, "import qwen_tts, soundfile, torch; print(torch.cuda.is_available())")
    add(
        "qwen3tts",
        "ok" if ok and out.endswith("True") and tts.weights.is_dir() else "fail",
        f"venv {'imports ok' if ok else out}; weights {'found' if tts.weights.is_dir() else 'MISSING'} at {tts.weights}",
    )
    ok, out = await _py(
        klein.python,
        "from diffusers import Flux2KleinPipeline; import torch; print(torch.cuda.is_available())",
    )
    has_w = (klein.weights / "model_index.json").is_file()
    add(
        "klein",
        "ok" if ok and out.endswith("True") and has_w else "fail",
        f"venv {'imports ok' if ok else out}; weights {'found' if has_w else 'MISSING'} at {klein.weights}",
    )

    # Voice and library
    try:
        v = find_voice(cfg, "demo")
        add(
            "voice",
            "ok",
            f"default voice 'demo' at {v.wav}" + ("" if v.text else " (no transcript: embedding-only clone)"),
        )
    except FileNotFoundError as e:
        add("voice", "fail", str(e))
    cfg.library.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(cfg.library).free / 1e9
    add("library", "ok" if free > 20 else "warn", f"{cfg.library}, {free:.0f} GB free")

    # Remote providers
    for row in await provider_rows(cfg):
        where = f" (key from {row['source']}, …{row['last4']})" if row["configured"] else ""
        if not row["configured"]:
            status = "fail" if row["needed"] else "ok"
            detail = (
                "no key, and a default model needs one: add it in Settings"
                if row["needed"]
                else "no key (optional): add one in Settings to use its models"
            )
        else:
            status, detail = ("ok" if row["ok"] else "fail"), row["detail"]
        add(row["name"], status, detail + where)

    # A local engine no default model uses can't stop a render: its problems are warnings.
    need = needs(cfg)
    for c in checks:
        if c.status == "fail" and need.get(c.name) is False and c.name not in ("openrouter", "fal"):
            c.status, c.detail = "warn", f"{c.detail} (not used by the default models)"
    return checks
