"""LTX-2.5 image-to-video through a local ComfyUI, using only its HTTP API.

The graph is the prototype's (animate_ltx.py): a half-resolution pass with the keyframe injected
at strength 0.7 so the model can move away from it, a 2x latent upscale, then a short refine with
the keyframe re-pinned. The model generates its own ambience track alongside the picture.
"""

import asyncio
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import Ltx
from ..prompts import VIDEO_NEGATIVE


class ComfyError(RuntimeError):
    pass


_started: asyncio.subprocess.Process | None = None


async def ensure_running(url: str, root: Path, timeout: float = 180) -> None:
    """Start ComfyUI from `root` if nothing answers at `url`; it then lives as long as this process."""
    global _started
    async with httpx.AsyncClient(timeout=3) as client:
        try:
            (await client.get(f"{url}/system_stats")).raise_for_status()
            return
        except httpx.HTTPError:
            pass
        python = root / ".venv" / "bin" / "python"
        if not (root / "main.py").is_file() or not python.is_file():
            raise ComfyError(f"ComfyUI isn't answering at {url}, and there is no install at {root} to start")
        if _started is None or _started.returncode is not None:
            u = urlparse(url)
            log = open(root / "user" / "lanternist-comfyui.log", "ab") if (root / "user").is_dir() else None  # noqa: SIM115, ASYNC230
            _started = await asyncio.create_subprocess_exec(
                str(python), "main.py", "--listen", u.hostname or "127.0.0.1", "--port", str(u.port or 8188),
                cwd=root, stdout=log or asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.STDOUT)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _started.returncode is not None:
                raise ComfyError(f"ComfyUI exited with code {_started.returncode} while starting")
            try:
                (await client.get(f"{url}/system_stats")).raise_for_status()
                return
            except httpx.HTTPError:
                await asyncio.sleep(2)
        raise ComfyError(f"ComfyUI didn't come up at {url} within {timeout:.0f}s")


def graph(m: Ltx, image: str, text: str, frames: int, seed: int, prefix: str) -> dict:
    fps = m.fps
    return {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": m.unet, "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": m.text_encoder, "type": "ltxv", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": m.vae}},
        "avae": {"class_type": "VAELoader", "inputs": {"vae_name": m.audio_vae}},
        "up": {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": m.upscaler}},
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "pre": {"class_type": "LTXVPreprocess", "inputs": {"image": ["img", 0], "img_compression": 18}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": text}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": VIDEO_NEGATIVE}},
        "cond": {"class_type": "LTXVConditioning", "inputs": {"positive": ["pos", 0], "negative": ["neg", 0], "frame_rate": float(fps)}},
        "vlat": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": m.width // 2, "height": m.height // 2, "length": frames, "batch_size": 1}},
        "i2v1": {"class_type": "LTXVImgToVideoInplace", "inputs": {"vae": ["vae", 0], "image": ["pre", 0], "latent": ["vlat", 0], "strength": m.strength, "bypass": False}},
        "alat": {"class_type": "LTXVEmptyLatentAudio", "inputs": {"frames_number": frames, "frame_rate": fps, "batch_size": 1, "audio_vae": ["avae", 0]}},
        "av1": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["i2v1", 0], "audio_latent": ["alat", 0]}},
        "g1": {"class_type": "LTXVDualCFGGuider", "inputs": {"model": ["unet", 0], "positive": ["cond", 0], "negative": ["cond", 1], "video_cfg": 1.0, "audio_cfg": 1.0}},
        "n1": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "smp1": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},
        "sig1": {"class_type": "ManualSigmas", "inputs": {"sigmas": "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"}},
        "s1": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["n1", 0], "guider": ["g1", 0], "sampler": ["smp1", 0], "sigmas": ["sig1", 0], "latent_image": ["av1", 0]}},
        "sep1": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["s1", 0]}},
        "ups": {"class_type": "LTXVLatentUpsampler", "inputs": {"samples": ["sep1", 0], "upscale_model": ["up", 0], "vae": ["vae", 0]}},
        "i2v2": {"class_type": "LTXVImgToVideoInplace", "inputs": {"vae": ["vae", 0], "image": ["pre", 0], "latent": ["ups", 0], "strength": 1.0, "bypass": False}},
        "av2": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["i2v2", 0], "audio_latent": ["sep1", 1]}},
        "g2": {"class_type": "LTXVDualCFGGuider", "inputs": {"model": ["unet", 0], "positive": ["cond", 0], "negative": ["cond", 1], "video_cfg": 1.0, "audio_cfg": 1.0}},
        "n2": {"class_type": "RandomNoise", "inputs": {"noise_seed": 42}},
        "smp2": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},
        "sig2": {"class_type": "ManualSigmas", "inputs": {"sigmas": "0.85, 0.7250, 0.4219, 0.0"}},
        "s2": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["n2", 0], "guider": ["g2", 0], "sampler": ["smp2", 0], "sigmas": ["sig2", 0], "latent_image": ["av2", 0]}},
        "sep2": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["s2", 0]}},
        "dec": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["sep2", 0], "vae": ["vae", 0], "tile_size": 512, "overlap": 64, "temporal_size": 64, "temporal_overlap": 16}},
        "adec": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["sep2", 1], "audio_vae": ["avae", 0]}},
        "vid": {"class_type": "CreateVideo", "inputs": {"images": ["dec", 0], "audio": ["adec", 0], "fps": float(fps)}},
        "save": {"class_type": "SaveVideo", "inputs": {"video": ["vid", 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"}},
    }


class ComfyClient:
    def __init__(self, url: str, root: Path | None = None):
        self.url = url.rstrip("/")
        self.root = root  # when ComfyUI is local, its input/output copies are removed once we have ours
        self.client_id = uuid.uuid4().hex

    def discard(self, kind: str, subfolder: str, filename: str) -> None:
        if self.root:
            (self.root / kind / subfolder / filename).unlink(missing_ok=True)

    async def upload(self, client: httpx.AsyncClient, path: Path) -> str:
        r = await client.post(f"{self.url}/upload/image",
                              files={"image": (path.name, path.read_bytes(), "image/png")},
                              data={"subfolder": "lanternist", "type": "input", "overwrite": "true"})
        r.raise_for_status()
        d = r.json()
        return f"{d['subfolder']}/{d['name']}" if d.get("subfolder") else d["name"]

    async def run(self, client: httpx.AsyncClient, prompt: dict, out: Path, timeout: float = 1800) -> None:
        r = await client.post(f"{self.url}/prompt", json={"prompt": prompt, "client_id": self.client_id})
        if r.status_code != 200:
            raise ComfyError(f"ComfyUI rejected the graph: {r.text[:2000]}")
        pid = r.json()["prompt_id"]
        deadline = time.monotonic() + timeout
        try:
            while True:
                h = (await client.get(f"{self.url}/history/{pid}")).json()
                if pid in h:
                    break
                if time.monotonic() > deadline:
                    raise ComfyError(f"ComfyUI prompt {pid} timed out")
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            await client.post(f"{self.url}/interrupt")
            raise
        status = h[pid]["status"]
        if status.get("status_str") != "success":
            raise ComfyError(f"ComfyUI prompt failed: {str(status.get('messages'))[-2000:]}")
        for node in h[pid]["outputs"].values():
            for f in node.get("images", []) + node.get("videos", []) + node.get("gifs", []):
                params = {"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")}
                async with client.stream("GET", f"{self.url}/view", params=params) as resp:
                    resp.raise_for_status()
                    with open(out, "wb") as fh:  # noqa: ASYNC230 - streamed to disk chunk by chunk
                        async for chunk in resp.aiter_bytes(1 << 20):
                            fh.write(chunk)
                self.discard(params["type"], params["subfolder"], params["filename"])
                return
        raise ComfyError("ComfyUI finished but returned no video")
