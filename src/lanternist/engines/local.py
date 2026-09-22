"""The models on this machine, behind the engine interface, plus ffmpeg's two stages.

Each local model runs its whole batch in one load under the GPU lease: Qwen3-TTS and klein as
worker subprocesses in their own venvs, LTX-2.5 through ComfyUI. Their step keys carry exactly the
fields they had before the engine interface, under the same engine ids, so an existing library
stays cached; `test_local_step_keys_are_unchanged` pins them.

In fake mode every one of them makes test media of the right shape and length instead.
"""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from .. import prompts, text, timing
from ..config import Settings
from ..gpu import lease
from ..registry import ModelEntry
from ..store import step_key
from ..voices import Voice
from . import fake, ffmpeg
from .base import (
    Engine,
    Estimate,
    Item,
    Maker,
    OnItem,
    Output,
    StepContext,
    TtsEngine,
    VideoEngine,
    gpu_estimate,
)
from .ltx import ComfyClient, ensure_running, graph
from .worker import run_worker

TTS = "qwen3-tts-1.7b@1"
KLEIN = "flux2-klein-9b@1"
LTX = "ltx-2.5-22b-nvfp4@1"
KLEIN_STEPS, KLEIN_GUIDANCE = 4, 1.0


def _on_worker(
    ctx: StepContext, items: list[Item], made: Callable[[Item, dict], None]
) -> Callable[[dict], None]:
    """A worker's event handler: its load time as a progress line, then `made` for each output."""
    by_id = {it.id: it for it in items}

    def on_event(ev: dict) -> None:
        if ev.get("event") == "loaded":
            ctx.note(f"model loaded in {ev['secs']}s", None)
        elif ev.get("event") == "item":
            made(by_id[ev["id"]], ev)

    return on_event


class LocalQwenTts(TtsEngine):
    """Qwen3-TTS 1.7B, cloning one reference recording for every scene."""

    def __init__(self, cfg: Settings, entry: ModelEntry, voice: Voice, language: str):
        super().__init__(cfg, entry)
        self.voice, self.language = voice, language

    def chunks(self, words: str) -> list[str]:
        return text.tts_chunks(words, self.language)

    def key(self, kind: str, **inputs) -> str:
        return step_key(
            kind,
            engine=TTS,
            language=text.LANGUAGES.get(self.language),
            voice=self.voice.sha,
            ref_text=self.voice.text,
            chunk_gap=self.cfg.render.chunk_gap,
            **inputs,
        )

    def estimate(self, items: list[Item]) -> Estimate:
        return gpu_estimate(self.entry, sum(it.params["seconds"] for it in items), len(items))

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        jobs = [
            {
                "id": it.id,
                "chunks": it.params["chunks"],
                "seed": it.params["seed"],
                "out": str(ctx.work / f"{it.id}.wav"),
            }
            for it in items
        ]

        def made(it: Item, ev: dict) -> None:
            meta = {
                "duration": ev["duration"],
                "chunks": it.params["chunks"],
                "chunk_durations": ev["chunk_durations"],
                "sample_rate": ev["sample_rate"],
            }
            on_item(Output(it, Path(ev["out"]), meta, ev.get("secs")))

        on_event = _on_worker(ctx, items, made)

        if self.cfg.fake_engines:
            for job in jobs:
                on_event({"event": "item", **fake.tts(job, chunk_gap=self.cfg.render.chunk_gap)})
            return
        eng = self.cfg.engines.qwen3tts
        job = {
            "weights": str(eng.weights),
            "ref_audio": str(self.voice.wav),
            "ref_text": self.voice.text,
            "language": text.LANGUAGES[self.language],
            "chunk_gap": self.cfg.render.chunk_gap,
            "items": jobs,
        }
        async with lease(self.cfg, "qwen3tts", eng.vram_gb):
            await run_worker(eng.python, "tts_qwen3.py", job, ctx.work, on_event)


class LocalKlein(Engine):
    """FLUX.2 [klein] 9B: the cast sheet and every keyframe in one load, the cast sheet first."""

    def key(self, kind: str, **inputs) -> str:
        return step_key(kind, engine=KLEIN, steps=KLEIN_STEPS, guidance=KLEIN_GUIDANCE, **inputs)

    def estimate(self, items: list[Item]) -> Estimate:
        return gpu_estimate(self.entry, len(items), len(items))

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        jobs = []
        for it in items:
            p = it.params
            # A cast sheet drawn in this batch is read from the work dir, where the worker puts it.
            refs = (
                [str(ctx.work / f"{it.after}.png")]
                if it.after
                else [str(ctx.store.path(a)) for a in p["refs"]]
            )
            jobs.append(
                {
                    "id": it.id,
                    "prompt": p["prompt"],
                    "seed": p["seed"],
                    "width": p["width"],
                    "height": p["height"],
                    "refs": refs,
                    "out": str(ctx.work / f"{it.id}.png"),
                }
            )

        def made(it: Item, ev: dict) -> None:
            if it.after:
                ctx.bind(it)
            on_item(Output(it, Path(ev["out"]), secs=ev.get("secs")))

        on_event = _on_worker(ctx, items, made)

        if self.cfg.fake_engines:
            for job in jobs:
                on_event({"event": "item", **await fake.image(job)})
            return
        eng = self.cfg.engines.klein
        job = {"weights": str(eng.weights), "steps": KLEIN_STEPS, "guidance": KLEIN_GUIDANCE, "items": jobs}
        async with lease(self.cfg, "klein", eng.vram_gb):
            await run_worker(eng.python, "image_klein.py", job, ctx.work, on_event)


class LocalLtx(VideoEngine):
    """LTX-2.5 through ComfyUI. A slot past its 20 s limit becomes equal shots, each starting from
    the last frame of the one before, cut together into one clip."""

    def shots(self, seconds: float) -> list[float]:
        return timing.shot_lengths(seconds, self.cfg.engines.ltx.max_seconds)

    def frames(self, shots: list[float]) -> list[int]:
        return [timing.ltx_frames(s, self.cfg.engines.ltx.fps) for s in shots]

    def key(self, kind: str, **inputs) -> str:
        m = self.cfg.engines.ltx
        shots = inputs.pop("shots")
        return step_key(
            kind,
            engine=LTX,
            negative=prompts.VIDEO_NEGATIVE,
            frames=self.frames(shots),
            size=[m.width, m.height],
            strength=m.strength,
            fps=m.fps,
            **inputs,
        )

    def estimate(self, items: list[Item]) -> Estimate:
        seconds = sum(sum(it.params["shots"]) for it in items)
        est = gpu_estimate(self.entry, seconds, len(items))
        est.paid_seconds = round(seconds, 3)
        return est

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        m = self.cfg.engines.ltx
        comfy = ComfyClient(self.cfg.comfyui.url, self.cfg.comfyui.root)
        if not self.cfg.fake_engines:
            await ensure_running(self.cfg.comfyui.url, self.cfg.comfyui.root)
        async with lease(self.cfg, "comfyui", m.vram_gb), httpx.AsyncClient(timeout=120) as client:
            for it in items:
                t0 = time.monotonic()
                n, frames = it.scene, self.frames(it.params["shots"])
                shots = []
                image = ctx.store.path(it.params["keyframe"])
                for j, f in enumerate(frames):
                    shot = ctx.work / f"{it.id}-{j}.mp4"
                    ctx.note(f"scene {n}: shot {j + 1}/{len(frames)}, {f} frames", n)
                    if self.cfg.fake_engines:
                        await fake.video(f, m.fps, m.width, m.height, shot)
                    else:
                        name = await comfy.upload(client, image)
                        seed = it.params["seed"] + j
                        await comfy.run(
                            client, graph(m, name, it.params["prompt"], f, seed, f"lanternist/{it.id}"), shot
                        )
                        comfy.discard("input", *name.rsplit("/", 1))
                    shots.append(shot)
                    if j + 1 < len(frames):
                        image = ctx.work / f"{it.id}-{j}-last.png"
                        await ffmpeg.last_frame(shot, image)
                joined = ctx.work / f"{it.id}.mp4"
                await ffmpeg.concat(shots, joined)
                on_item(Output(it, joined, {"frames": frames}, round(time.monotonic() - t0, 1)))


class Clips(Maker):
    """Every scene's normalised clip: a still with its camera move, or a generated clip fitted to its slot."""

    CONCURRENT = 3  # ffmpeg encodes at once; more only queue on the encoder

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        sem = asyncio.Semaphore(self.CONCURRENT)
        r = ctx.cfg.render

        async def one(it: Item) -> None:
            p = it.params
            async with sem:
                dest = ctx.work / f"{it.id}.mp4"
                src = ctx.store.path(p["src"])
                if p["mode"] == "video":
                    await ffmpeg.video_clip(src, p["length"], r, dest)
                else:
                    await ffmpeg.still_clip(src, p["length"], p["camera"], r, dest)
                on_item(Output(it, dest, {"length": p["length"]}))

        await asyncio.gather(*(one(it) for it in items))


class Mix(Maker):
    """The film: the clips crossfaded, the narration laid on top, and the subtitle files."""

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        for it in items:
            p = it.params
            extra = {}
            srt_path = None
            if p["subtitles"] != "off":
                srt_path = ctx.work / "film.srt"
                srt_path.write_text(timing.srt(p["cues"]), encoding="utf-8")
                vtt_path = ctx.work / "film.vtt"
                vtt_path.write_text(timing.vtt(p["cues"]), encoding="utf-8")
                extra = {"srt": srt_path, "vtt": vtt_path}
            film = ctx.work / "film.mp4"
            await ffmpeg.mix(
                [ctx.store.path(c) for c in p["clips"]],
                [ctx.store.path(w) for w in p["wavs"]],
                p["timeline"],
                ctx.cfg.render,
                film,
                subtitles=srt_path if p["subtitles"] == "burned" else None,
            )
            on_item(Output(it, film, {"duration": round(p["timeline"].total, 3)}, extra=extra))
