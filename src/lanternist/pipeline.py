"""A film is a sequence of cached stages, each batched across all scenes so every model loads once.

    board:   narration (Qwen3-TTS) -> cast sheet + keyframes (klein)
    render:  board -> motion for video scenes (LTX-2.5) -> one normalised clip per scene -> mix

Every step's output is stored under a key hashing everything that decides it, so a second run
is all cache hits and an edit re-runs only the steps it reaches.
"""

import asyncio
import logging
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from . import prompts, text, timing
from .config import Settings
from .engines import fake, ffmpeg
from .engines.ltx import ComfyClient, ensure_running, graph
from .engines.worker import run_worker
from .gpu import lease
from .store import Store, file_sha, step_key
from .storyboard import Storyboard

log = logging.getLogger(__name__)

TTS = "qwen3-tts-1.7b@1"
KLEIN = "flux2-klein-9b@1"
LTX = "ltx-2.5-22b-nvfp4@1"
CLIP = "clip@1"
MIX = "mix@1"
CAST_SIZE = (1024, 1024)
KLEIN_STEPS, KLEIN_GUIDANCE = 4, 1.0


@dataclass
class Event:
    stage: str  # narration | cast | keyframes | motion | clips | mix
    status: str  # start | cached | done | finish | progress
    scene: int | None = None
    done: int = 0
    total: int = 0
    message: str = ""
    asset: str | None = None

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Voice:
    name: str
    wav: Path
    text: str | None
    sha: str


@dataclass
class Narration:
    audio: str
    duration: float
    chunks: list[str]
    chunk_durations: list[float]


@dataclass
class Board:
    narration: list[Narration]
    cast: str | None
    keyframes: list[str]
    timeline: timing.Timeline


@dataclass
class Film:
    film: str
    srt: str | None
    vtt: str | None
    duration: float
    clips: list[str] = field(default_factory=list)
    poster: str | None = None


def find_voice(cfg: Settings, name: str) -> Voice:
    for d in cfg.paths.voices:
        wav = d / f"{name}.wav"
        if wav.is_file():
            txt = wav.with_suffix(".txt")
            transcript = txt.read_text(encoding="utf-8").strip() if txt.is_file() else None
            return Voice(name, wav, transcript or None, file_sha(wav))
    raise FileNotFoundError(
        f"no voice '{name}': looked for {name}.wav in " + ", ".join(str(d) for d in cfg.paths.voices)
    )


def list_voices(cfg: Settings) -> list[dict]:
    seen, out = set(), []
    for d in cfg.paths.voices:
        for wav in sorted(d.glob("*.wav")) if d.is_dir() else []:
            if wav.stem not in seen:
                seen.add(wav.stem)
                out.append(
                    {"name": wav.stem, "path": str(wav), "has_transcript": wav.with_suffix(".txt").is_file()}
                )
    return out


def keyframe_size(cfg: Settings) -> tuple[int, int]:
    # klein wants sides divisible by 16: 1920x1080 is drawn at 1920x1088 and cropped when framed.
    r = cfg.render
    return (r.width + 15) // 16 * 16, (r.height + 15) // 16 * 16


class Pipeline:
    def __init__(self, cfg: Settings, emit: Callable[[Event], None] | None = None):
        self.cfg = cfg
        self.store = Store(cfg.library)
        self._emit = emit or (lambda e: None)

    def emit(self, stage: str, status: str, **kw) -> None:
        self._emit(Event(stage, status, **kw))

    # ---------------------------------------------------------------- narration
    def _tts_key(self, sb: Storyboard, sc, voice: Voice) -> tuple[list[str], str]:
        chunks = text.tts_chunks(sc.text, sb.language)
        return chunks, step_key(
            "tts",
            engine=TTS,
            chunks=chunks,
            language=text.LANGUAGES.get(sb.language),
            voice=voice.sha,
            ref_text=voice.text,
            seed=sb.seed,
            chunk_gap=self.cfg.render.chunk_gap,
        )

    async def narrate(self, sb: Storyboard) -> list[Narration]:
        if sb.language not in text.LANGUAGES:
            raise ValueError(
                f"narration language '{sb.language}' is not supported by Qwen3-TTS "
                f"(supported: {', '.join(text.LANGUAGES)})"
            )
        voice = find_voice(self.cfg, sb.voice)
        language = text.LANGUAGES[sb.language]
        results: dict[int, dict] = {}
        pending = []
        for sc in sb.scenes:
            chunks, key = self._tts_key(sb, sc, voice)
            rec = self.store.get_step(key)
            if rec:
                results[sc.n] = rec
            else:
                pending.append((sc, chunks, key))
        total = len(sb.scenes)
        self.emit("narration", "start", done=len(results), total=total)

        if pending:
            work = self.store.tmp()
            items, keys = [], {}
            for sc, chunks, key in pending:
                item_id = f"s{sc.n:03d}"
                items.append(
                    {"id": item_id, "chunks": chunks, "seed": sb.seed, "out": str(work / f"{item_id}.wav")}
                )
                keys[item_id] = (sc.n, key, chunks)

            def on_event(ev: dict) -> None:
                if ev.get("event") == "loaded":
                    self.emit(
                        "narration",
                        "progress",
                        message=f"model loaded in {ev['secs']}s",
                        done=len(results),
                        total=total,
                    )
                if ev.get("event") != "item":
                    return
                n, key, chunks = keys[ev["id"]]
                asset = self.store.put(Path(ev["out"]))
                results[n] = self.store.put_step(
                    key,
                    {
                        "assets": {"audio": asset},
                        "meta": {
                            "duration": ev["duration"],
                            "chunks": chunks,
                            "chunk_durations": ev["chunk_durations"],
                            "sample_rate": ev["sample_rate"],
                        },
                        "secs": ev.get("secs"),
                    },
                )
                self.emit("narration", "done", scene=n, done=len(results), total=total, asset=asset)

            if self.cfg.fake_engines:
                for item in items:
                    on_event({"event": "item", **fake.tts(item, chunk_gap=self.cfg.render.chunk_gap)})
            else:
                eng = self.cfg.engines.qwen3tts
                job = {
                    "weights": str(eng.weights),
                    "ref_audio": str(voice.wav),
                    "ref_text": voice.text,
                    "language": language,
                    "chunk_gap": self.cfg.render.chunk_gap,
                    "items": items,
                }
                async with lease(self.cfg, "qwen3tts", eng.vram_gb):
                    await run_worker(eng.python, "tts_qwen3.py", job, work, on_event)
            shutil.rmtree(work, ignore_errors=True)

        self.emit("narration", "finish", done=total, total=total)
        out = []
        for sc in sb.scenes:
            rec = results[sc.n]
            out.append(
                Narration(
                    rec["assets"]["audio"],
                    rec["meta"]["duration"],
                    rec["meta"]["chunks"],
                    rec["meta"]["chunk_durations"],
                )
            )
        return out

    # ---------------------------------------------------------------- pictures
    def _cast_key(self, sb: Storyboard, prompt: str) -> str:
        return step_key(
            "cast",
            engine=KLEIN,
            prompt=prompt,
            seed=sb.seed,
            size=list(CAST_SIZE),
            steps=KLEIN_STEPS,
            guidance=KLEIN_GUIDANCE,
        )

    def _keyframe_key(self, prompt: str, seed: int, cast: str | None) -> str:
        return step_key(
            "keyframe",
            engine=KLEIN,
            prompt=prompt,
            seed=seed,
            size=list(keyframe_size(self.cfg)),
            steps=KLEIN_STEPS,
            guidance=KLEIN_GUIDANCE,
            refs=[cast] if cast else [],
        )

    async def draw(self, sb: Storyboard, cast_only: bool = False) -> tuple[str | None, list[str]]:
        """Cast sheet, then one keyframe per scene with the cast sheet as reference. One model load."""
        width, height = keyframe_size(self.cfg)
        work = self.store.tmp()
        items: list[dict] = []
        cast_prompt = prompts.cast_sheet(sb)
        state = {"cast": None}
        keyframes: dict[int, str] = {}

        if cast_prompt:
            rec = self.store.get_step(self._cast_key(sb, cast_prompt))
            if rec:
                state["cast"] = rec["assets"]["image"]
            else:
                items.append(
                    {
                        "id": "cast",
                        "prompt": cast_prompt,
                        "seed": sb.seed,
                        "width": CAST_SIZE[0],
                        "height": CAST_SIZE[1],
                        "refs": [],
                        "out": str(work / "cast.png"),
                    }
                )
        redraw_cast = bool(items)

        scene_prompts = {}
        if not cast_only:
            for sc in sb.scenes:
                p, seed = prompts.keyframe(sb, sc), sb.scene_seed(sc)
                scene_prompts[sc.n] = (p, seed)
                if not redraw_cast:
                    rec = self.store.get_step(self._keyframe_key(p, seed, state["cast"]))
                    if rec:
                        keyframes[sc.n] = rec["assets"]["image"]
                        continue
                # A cast sheet drawn in this job is every keyframe's reference, read from the work dir.
                ref = (
                    [str(work / "cast.png")]
                    if redraw_cast
                    else ([str(self.store.path(state["cast"]))] if state["cast"] else [])
                )
                items.append(
                    {
                        "id": f"s{sc.n:03d}",
                        "prompt": p,
                        "seed": seed,
                        "width": width,
                        "height": height,
                        "refs": ref,
                        "out": str(work / f"s{sc.n:03d}.png"),
                    }
                )

        total = (1 if cast_prompt else 0) + len(scene_prompts)
        done = total - len(items)
        if cast_prompt and not redraw_cast:
            self.emit("cast", "cached", asset=state["cast"])
        self.emit("keyframes", "start", done=done, total=total)

        def on_event(ev: dict) -> None:
            nonlocal done
            if ev.get("event") == "loaded":
                self.emit(
                    "keyframes", "progress", message=f"model loaded in {ev['secs']}s", done=done, total=total
                )
            if ev.get("event") != "item":
                return
            done += 1
            if ev["id"] == "cast":
                # Copied, not moved: the keyframes after it in this job still read it from the work dir.
                state["cast"] = self.store.put(Path(ev["out"]), move=False)
                self.store.put_step(
                    self._cast_key(sb, cast_prompt),
                    {"assets": {"image": state["cast"]}, "secs": ev.get("secs")},
                )
                self.emit("cast", "done", done=done, total=total, asset=state["cast"])
                return
            n = int(ev["id"][1:])
            p, seed = scene_prompts[n]
            asset = self.store.put(Path(ev["out"]))
            self.store.put_step(
                self._keyframe_key(p, seed, state["cast"]),
                {"assets": {"image": asset}, "secs": ev.get("secs")},
            )
            keyframes[n] = asset
            self.emit("keyframes", "done", scene=n, done=done, total=total, asset=asset)

        if items:
            if self.cfg.fake_engines:
                for item in items:
                    on_event({"event": "item", **await fake.image(item)})
            else:
                eng = self.cfg.engines.klein
                job = {
                    "weights": str(eng.weights),
                    "steps": KLEIN_STEPS,
                    "guidance": KLEIN_GUIDANCE,
                    "items": items,
                }
                async with lease(self.cfg, "klein", eng.vram_gb):
                    await run_worker(eng.python, "image_klein.py", job, work, on_event)
        shutil.rmtree(work, ignore_errors=True)
        self.emit("keyframes", "finish", done=total, total=total)
        return state["cast"], [keyframes[sc.n] for sc in sb.scenes] if not cast_only else []

    # ---------------------------------------------------------------- board
    def timeline(self, narration: list[Narration]) -> timing.Timeline:
        r = self.cfg.render
        return timing.timeline([n.duration for n in narration], r.gap, r.lead_in, r.tail, r.xfade)

    async def board(self, sb: Storyboard) -> Board:
        narration = await self.narrate(sb)
        cast, keyframes = await self.draw(sb)
        return Board(narration, cast, keyframes, self.timeline(narration))

    # ---------------------------------------------------------------- motion
    def _motion_key(self, sb: Storyboard, i: int, board: Board) -> tuple[str, str, int, list[int]]:
        m, sc = self.cfg.engines.ltx, sb.scenes[i]
        shots = timing.shot_lengths(board.timeline.clip_length(i), m.max_seconds)
        frames = [timing.ltx_frames(s, m.fps) for s in shots]
        prompt, seed = prompts.video(sb, sc), sb.scene_seed(sc)
        key = step_key(
            "motion",
            engine=LTX,
            prompt=prompt,
            negative=prompts.VIDEO_NEGATIVE,
            seed=seed,
            frames=frames,
            size=[m.width, m.height],
            strength=m.strength,
            fps=m.fps,
            keyframe=board.keyframes[i],
        )
        return key, prompt, seed, frames

    async def motion(self, sb: Storyboard, board: Board) -> dict[int, str]:
        """Animate every video-mode scene. Slots past LTX's 20 s limit become shots chained on last frames."""
        m = self.cfg.engines.ltx
        out: dict[int, str] = {}
        pending = []
        for i, sc in enumerate(sb.scenes):
            if sc.mode != "video":
                continue
            key, prompt, seed, frames = self._motion_key(sb, i, board)
            rec = self.store.get_step(key)
            if rec:
                out[sc.n] = rec["assets"]["video"]
            else:
                pending.append((i, sc, key, prompt, seed, frames))
        total = len(out) + len(pending)
        if not total:
            return out
        self.emit("motion", "start", done=len(out), total=total)
        if pending:
            work = self.store.tmp()
            comfy = ComfyClient(self.cfg.comfyui.url, self.cfg.comfyui.root)
            if not self.cfg.fake_engines:
                await ensure_running(self.cfg.comfyui.url, self.cfg.comfyui.root)
            async with lease(self.cfg, "comfyui", m.vram_gb), httpx.AsyncClient(timeout=120) as client:
                for i, sc, key, prompt, seed, frames in pending:
                    shots = []
                    image = self.store.path(board.keyframes[i])
                    for j, f in enumerate(frames):
                        shot = work / f"s{sc.n:03d}-{j}.mp4"
                        self.emit(
                            "motion",
                            "progress",
                            scene=sc.n,
                            done=len(out),
                            total=total,
                            message=f"scene {sc.n}: shot {j + 1}/{len(frames)}, {f} frames",
                        )
                        if self.cfg.fake_engines:
                            await fake.video(f, m.fps, m.width, m.height, shot)
                        else:
                            name = await comfy.upload(client, image)
                            await comfy.run(
                                client, graph(m, name, prompt, f, seed + j, f"lanternist/s{sc.n:03d}"), shot
                            )
                            comfy.discard("input", *name.rsplit("/", 1))
                        shots.append(shot)
                        if j + 1 < len(frames):
                            image = work / f"s{sc.n:03d}-{j}-last.png"
                            await ffmpeg.last_frame(shot, image)
                    joined = work / f"s{sc.n:03d}.mp4"
                    await ffmpeg.concat(shots, joined)
                    asset = self.store.put(joined)
                    self.store.put_step(key, {"assets": {"video": asset}, "meta": {"frames": frames}})
                    out[sc.n] = asset
                    self.emit("motion", "done", scene=sc.n, done=len(out), total=total, asset=asset)
            shutil.rmtree(work, ignore_errors=True)
        self.emit("motion", "finish", done=total, total=total)
        return out

    # ---------------------------------------------------------------- clips
    async def clips(self, sb: Storyboard, board: Board, motions: dict[int, str]) -> list[str]:
        r, tl = self.cfg.render, board.timeline
        out: list[str | None] = [None] * len(sb.scenes)
        pending = []
        for i, sc in enumerate(sb.scenes):
            length = round(tl.clip_length(i), 3)
            if sc.mode == "video":
                spec = {"mode": "video", "src": motions[sc.n]}
            else:
                spec = {
                    "mode": "still",
                    "src": board.keyframes[i],
                    "camera": ffmpeg.resolve_camera(sc.camera, i),
                }
            key = step_key(
                "clip",
                engine=CLIP,
                length=length,
                size=[r.width, r.height],
                fps=r.fps,
                encoder=r.encoder,
                **spec,
            )
            rec = self.store.get_step(key)
            if rec:
                out[i] = rec["assets"]["video"]
            else:
                pending.append((i, sc, key, length, spec))
        total = len(out)
        done = total - len(pending)
        self.emit("clips", "start", done=done, total=total)
        if pending:
            work = self.store.tmp()
            sem = asyncio.Semaphore(3)

            async def one(i, sc, key, length, spec):
                nonlocal done
                async with sem:
                    dest = work / f"s{sc.n:03d}.mp4"
                    src = self.store.path(spec["src"])
                    if spec["mode"] == "video":
                        await ffmpeg.video_clip(src, length, r, dest)
                    else:
                        await ffmpeg.still_clip(src, length, spec["camera"], r, dest)
                    out[i] = self.store.put(dest)
                    self.store.put_step(key, {"assets": {"video": out[i]}, "meta": {"length": length}})
                    done += 1
                    self.emit("clips", "done", scene=sc.n, done=done, total=total, asset=out[i])

            await asyncio.gather(*(one(*p) for p in pending))
            shutil.rmtree(work, ignore_errors=True)
        self.emit("clips", "finish", done=total, total=total)
        return out

    # ---------------------------------------------------------------- mix
    async def mix(self, sb: Storyboard, board: Board, clips: list[str]) -> Film:
        r, tl = self.cfg.render, board.timeline
        cues = timing.cues(
            [n.chunks for n in board.narration],
            [n.chunk_durations for n in board.narration],
            tl.speech_starts,
            r.chunk_gap,
        )
        wavs = [n.audio for n in board.narration]
        key = step_key(
            "mix",
            engine=MIX,
            clips=clips,
            wavs=wavs,
            speech_starts=tl.speech_starts,
            bounds=tl.bounds,
            xfade=tl.xfade,
            ambience=r.ambience,
            encoder=r.encoder,
            bitrate=r.bitrate,
            subtitles=sb.subtitles,
            cues=[(c.start, c.end, c.text) for c in cues] if sb.subtitles != "off" else [],
        )
        rec = self.store.get_step(key)
        self.emit("mix", "start", done=0, total=1)
        if not rec:
            work = self.store.tmp()
            assets = {}
            srt_path = None
            if sb.subtitles != "off":
                srt_path = work / "film.srt"
                srt_path.write_text(timing.srt(cues), encoding="utf-8")
                vtt_path = work / "film.vtt"
                vtt_path.write_text(timing.vtt(cues), encoding="utf-8")
            film = work / "film.mp4"
            await ffmpeg.mix(
                [self.store.path(c) for c in clips],
                [self.store.path(w) for w in wavs],
                tl,
                r,
                film,
                subtitles=srt_path if sb.subtitles == "burned" else None,
            )
            assets["film"] = self.store.put(film)
            if srt_path:
                assets["srt"] = self.store.put(srt_path)
                assets["vtt"] = self.store.put(vtt_path)
            rec = self.store.put_step(key, {"assets": assets, "meta": {"duration": round(tl.total, 3)}})
            shutil.rmtree(work, ignore_errors=True)
        self.emit("mix", "finish", done=1, total=1, asset=rec["assets"]["film"])
        a = rec["assets"]
        return Film(a["film"], a.get("srt"), a.get("vtt"), rec["meta"]["duration"], clips)

    # ---------------------------------------------------------------- what's already made
    def peek(self, sb: Storyboard) -> dict:
        """What the cache already holds for this storyboard, without running anything."""
        scenes = [
            {"n": sc.n, "audio": None, "duration": None, "keyframe": None, "motion": None} for sc in sb.scenes
        ]
        out = {"cast": None, "scenes": scenes, "total": None, "voice_ok": True}
        try:
            voice = find_voice(self.cfg, sb.voice)
        except FileNotFoundError:
            voice, out["voice_ok"] = None, False
        narration = []
        for sc, row in zip(sb.scenes, scenes):
            rec = self.store.get_step(self._tts_key(sb, sc, voice)[1]) if voice else None
            if rec:
                row["audio"], row["duration"] = rec["assets"]["audio"], rec["meta"]["duration"]
                narration.append(
                    Narration(
                        rec["assets"]["audio"],
                        rec["meta"]["duration"],
                        rec["meta"]["chunks"],
                        rec["meta"]["chunk_durations"],
                    )
                )
        cast_prompt = prompts.cast_sheet(sb)
        if cast_prompt:
            rec = self.store.get_step(self._cast_key(sb, cast_prompt))
            out["cast"] = rec["assets"]["image"] if rec else None
        if out["cast"] or not cast_prompt:
            for sc, row in zip(sb.scenes, scenes):
                rec = self.store.get_step(
                    self._keyframe_key(prompts.keyframe(sb, sc), sb.scene_seed(sc), out["cast"])
                )
                row["keyframe"] = rec["assets"]["image"] if rec else None
        if len(narration) == len(sb.scenes):
            tl = self.timeline(narration)
            out["total"] = round(tl.total, 2)
            if all(r["keyframe"] for r in scenes):
                board = Board(narration, out["cast"], [r["keyframe"] for r in scenes], tl)
                for i, (sc, row) in enumerate(zip(sb.scenes, scenes)):
                    if sc.mode == "video":
                        rec = self.store.get_step(self._motion_key(sb, i, board)[0])
                        row["motion"] = rec["assets"]["video"] if rec else None
        return out

    # ---------------------------------------------------------------- all of it
    async def render(self, sb: Storyboard) -> Film:
        board = await self.board(sb)
        motions = await self.motion(sb, board)
        clips = await self.clips(sb, board, motions)
        film = await self.mix(sb, board, clips)
        film.poster = board.keyframes[0] if board.keyframes else None
        return film
