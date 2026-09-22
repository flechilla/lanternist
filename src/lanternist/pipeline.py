"""A film is a sequence of cached stages, each run as one batch on the engine its story picked.

    board:   narration -> cast sheet + keyframes
    render:  board -> motion for video scenes -> one normalised clip per scene -> mix

Every step's output is stored under a key hashing everything that decides it, so a second run
is all cache hits and an edit re-runs only the steps it reaches. A stage asks its engine
(engines/) only for what the cache lacks: a local engine loads its model once for the batch under
the GPU lease, a remote one runs the items concurrently and never touches the GPU.
"""

import logging
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from . import prompts, registry, timing
from .config import Settings
from .db import Database, now
from .engines import catalog, ffmpeg
from .engines.base import (
    CAST_SIZE,
    Engine,
    Item,
    Maker,
    Output,
    StepContext,
    TtsEngine,
    VideoEngine,
    keyframe_size,
)
from .engines.local import Clips, Mix
from .store import Store, step_key
from .storyboard import Scene, Storyboard
from .writer import narration_seconds

log = logging.getLogger(__name__)

CLIP = "clip@1"
MIX = "mix@1"


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


def _narration(rec: dict) -> Narration:
    m = rec["meta"]
    return Narration(rec["assets"]["audio"], m["duration"], m["chunks"], m["chunk_durations"])


def _sid(sc: Scene) -> str:
    return f"s{sc.n:03d}"


class Pipeline:
    def __init__(
        self,
        cfg: Settings,
        emit: Callable[[Event], None] | None = None,
        db: Database | None = None,
        story_id: str | None = None,
        job_id: str | None = None,
        user_cancelled: Callable[[], bool] = lambda: False,
    ):
        self.cfg = cfg
        self.store = Store(cfg.library)
        self._emit = emit or (lambda e: None)
        self.db, self.story_id, self.job_id = db, story_id, job_id
        self.user_cancelled = user_cancelled

    def emit(self, stage: str, status: str, **kw) -> None:
        self._emit(Event(stage, status, **kw))

    # ---------------------------------------------------------------- the models a story uses
    def tts(self, sb: Storyboard) -> TtsEngine:
        return catalog.tts(self.cfg, self.db, self.cfg.defaults.tts, sb.voice, sb.language)

    def image(self, sb: Storyboard) -> Engine:
        m = sb.models
        return catalog.image(self.cfg, self.db, m.image or self.cfg.defaults.image, m.image_quality)

    def video(self) -> VideoEngine:
        return catalog.video(self.cfg, self.db, self.cfg.defaults.video)

    # ---------------------------------------------------------------- one stage
    async def _stage(
        self,
        stage: str,
        maker: Maker,
        items: list[Item],
        asset: str,
        bind: Callable[[Item, dict[str, dict]], None] | None = None,
    ) -> dict[str, dict]:
        """Serve what the cache holds, make the rest as one batch, and store each output as it lands.
        Returns every item's step record, by item id."""
        records: dict[str, dict] = {}
        for it in items:
            if it.key and (rec := self.store.get_step(it.key)):
                records[it.id] = rec
        pending = [it for it in items if it.id not in records]
        total = len(items)
        self.emit(stage, "start", done=len(records), total=total)
        if pending:
            work = self.store.tmp()
            waited_on = {it.after for it in pending if it.after}

            def on_item(out: Output) -> None:
                it = out.item
                if it.key is None:
                    raise RuntimeError(f"{it.id} came back before its key was bound")
                # Copied, not moved, when a later item in this batch still reads it from the work dir.
                main = self.store.put(out.path, move=it.id not in waited_on)
                assets = {asset: main} | {k: self.store.put(p) for k, p in out.extra.items()}
                records[it.id] = self.store.put_step(
                    it.key, {"assets": assets, "meta": out.meta, "secs": out.secs}
                )
                self._log_local(maker, it.stage or stage, it, out)
                self.emit(
                    it.stage or stage, "done", scene=it.scene, done=len(records), total=total, asset=main
                )

            ctx = StepContext(
                self.cfg,
                self.store,
                work,
                stage,
                self.db,
                self.story_id,
                self.job_id,
                self.user_cancelled,
                note=lambda message, scene: self.emit(
                    stage, "progress", scene=scene, message=message, done=len(records), total=total
                ),
            )
            if bind:
                ctx.bind = lambda it: bind(it, records)
            try:
                if maker.remote and self.db is not None:
                    await registry.ensure_synced(self.cfg, self.db)
                await maker.run(pending, ctx, on_item)
            finally:
                shutil.rmtree(work, ignore_errors=True)
        self.emit(stage, "finish", done=total, total=total)
        return records

    def _log_local(self, maker: Maker, stage: str, it: Item, out: Output) -> None:
        """A step_runs row for each step a local model made: what it cost is GPU time, not money."""
        if maker.remote or not maker.model_id or self.db is None:
            return
        self.db.start_run(
            story_id=self.story_id,
            job_id=self.job_id,
            scene=it.scene,
            stage=stage,
            step_key=it.key,
            model_id=maker.model_id,
            provider="local",
            status="done",
            gpu_seconds=out.secs,
            wall_seconds=out.secs,
            finished_at=now(),
        )

    # ---------------------------------------------------------------- narration
    def _narration_items(self, sb: Storyboard, eng: TtsEngine) -> list[Item]:
        items = []
        for sc in sb.scenes:
            chunks = eng.chunks(sc.text)
            items.append(
                Item(
                    _sid(sc),
                    eng.key("tts", chunks=chunks, seed=sb.seed),
                    sc.n,
                    {"chunks": chunks, "seed": sb.seed, "seconds": narration_seconds(sc.text, sb.language)},
                )
            )
        return items

    async def narrate(self, sb: Storyboard) -> list[Narration]:
        eng = self.tts(sb)
        languages = eng.entry.languages
        if languages and sb.language not in languages:
            raise ValueError(
                f"narration language '{sb.language}' is not supported by {eng.entry.label} "
                f"(supported: {', '.join(languages)})"
            )
        items = self._narration_items(sb, eng)
        records = await self._stage("narration", eng, items, "audio")
        return [_narration(records[it.id]) for it in items]

    # ---------------------------------------------------------------- pictures
    def _cast_key(self, eng: Engine, sb: Storyboard, prompt: str) -> str:
        return eng.key("cast", prompt=prompt, seed=sb.seed, size=list(CAST_SIZE))

    def _keyframe_key(self, eng: Engine, prompt: str, seed: int, cast: str | None) -> str:
        return eng.key(
            "keyframe",
            prompt=prompt,
            seed=seed,
            size=list(keyframe_size(self.cfg)),
            refs=[cast] if cast else [],
        )

    def _keyframe_item(self, eng: Engine, sb: Storyboard, sc: Scene, cast: str | None, after: bool) -> Item:
        p, seed = prompts.keyframe(sb, sc), sb.scene_seed(sc)
        w, h = keyframe_size(self.cfg)
        params = {"prompt": p, "seed": seed, "width": w, "height": h, "refs": [cast] if cast else []}
        if after:
            return Item(_sid(sc), None, sc.n, params, after="cast")
        return Item(_sid(sc), self._keyframe_key(eng, p, seed, cast), sc.n, params)

    async def draw(self, sb: Storyboard, cast_only: bool = False) -> tuple[str | None, list[str]]:
        """Cast sheet, then one keyframe per scene with the cast sheet as reference, as one batch."""
        eng = self.image(sb)
        cast_prompt = prompts.cast_sheet(sb)
        cast: str | None = None
        items: list[Item] = []
        if cast_prompt:
            key = self._cast_key(eng, sb, cast_prompt)
            rec = self.store.get_step(key)
            if rec:
                cast = rec["assets"]["image"]
                self.emit("cast", "cached", asset=cast)
            else:
                w, h = CAST_SIZE
                params = {"prompt": cast_prompt, "seed": sb.seed, "width": w, "height": h, "refs": []}
                items.append(Item("cast", key, None, params, stage="cast"))
        redraw = bool(items)
        if not cast_only:
            # Keyframes drawn after a new cast sheet key on it, so none of them can be a cache hit yet.
            items += [self._keyframe_item(eng, sb, sc, cast, after=redraw) for sc in sb.scenes]

        def bind(it: Item, records: dict[str, dict]) -> None:
            new_cast = records["cast"]["assets"]["image"]
            it.params["refs"] = [new_cast]
            it.key = self._keyframe_key(eng, it.params["prompt"], it.params["seed"], new_cast)

        records = await self._stage("keyframes", eng, items, "image", bind)
        if "cast" in records:
            cast = records["cast"]["assets"]["image"]
        return cast, [] if cast_only else [records[_sid(sc)]["assets"]["image"] for sc in sb.scenes]

    # ---------------------------------------------------------------- board
    def timeline(self, narration: list[Narration]) -> timing.Timeline:
        r = self.cfg.render
        return timing.timeline([n.duration for n in narration], r.gap, r.lead_in, r.tail, r.xfade)

    async def board(self, sb: Storyboard) -> Board:
        narration = await self.narrate(sb)
        cast, keyframes = await self.draw(sb)
        return Board(narration, cast, keyframes, self.timeline(narration))

    # ---------------------------------------------------------------- motion
    def _motion_items(self, sb: Storyboard, board: Board, eng: VideoEngine) -> list[Item]:
        items = []
        for i, sc in enumerate(sb.scenes):
            if sc.mode != "video":
                continue
            prompt, seed = prompts.video(sb, sc), sb.scene_seed(sc)
            shots = eng.shots(board.timeline.clip_length(i))
            inputs = {"prompt": prompt, "seed": seed, "keyframe": board.keyframes[i]}
            items.append(
                Item(_sid(sc), eng.key("motion", shots=shots, **inputs), sc.n, {"shots": shots, **inputs})
            )
        return items

    async def motion(self, sb: Storyboard, board: Board) -> dict[int, str]:
        """Animate every video-mode scene; a slot longer than one generation is chained shots."""
        if not any(sc.mode == "video" for sc in sb.scenes):
            return {}
        eng = self.video()
        items = self._motion_items(sb, board, eng)
        records = await self._stage("motion", eng, items, "video")
        return {it.scene: records[it.id]["assets"]["video"] for it in items if it.scene is not None}

    # ---------------------------------------------------------------- clips
    def _clip_items(self, sb: Storyboard, board: Board, motions: dict[int, str]) -> list[Item]:
        r, tl = self.cfg.render, board.timeline
        items = []
        for i, sc in enumerate(sb.scenes):
            length = round(tl.clip_length(i), 3)
            if sc.mode == "video":
                spec: dict = {"mode": "video", "src": motions[sc.n]}
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
            items.append(Item(_sid(sc), key, sc.n, {"length": length, **spec}))
        return items

    async def clips(self, sb: Storyboard, board: Board, motions: dict[int, str]) -> list[str]:
        items = self._clip_items(sb, board, motions)
        records = await self._stage("clips", Clips(), items, "video")
        return [records[it.id]["assets"]["video"] for it in items]

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
        params = {"clips": clips, "wavs": wavs, "timeline": tl, "cues": cues, "subtitles": sb.subtitles}
        rec = (await self._stage("mix", Mix(), [Item("film", key, None, params)], "film"))["film"]
        a = rec["assets"]
        return Film(a["film"], a.get("srt"), a.get("vtt"), rec["meta"]["duration"], clips)

    # ---------------------------------------------------------------- what's already made
    def peek(self, sb: Storyboard) -> dict:
        """What the cache already holds for this storyboard, without running anything."""
        scenes: list[dict[str, Any]] = [
            {"n": sc.n, "audio": None, "duration": None, "keyframe": None, "motion": None} for sc in sb.scenes
        ]
        out: dict = {"cast": None, "scenes": scenes, "total": None, "voice_ok": True}
        try:
            tts: TtsEngine | None = self.tts(sb)
        except FileNotFoundError:
            tts, out["voice_ok"] = None, False
        narration = []
        for it, row in zip(self._narration_items(sb, tts) if tts else [], scenes, strict=False):
            rec = self.store.get_step(it.key) if it.key else None
            if rec:
                row["audio"], row["duration"] = rec["assets"]["audio"], rec["meta"]["duration"]
                narration.append(_narration(rec))
        try:
            img = self.image(sb)
        except ValueError:  # the story's picture model left the registry: nothing of it is cached
            return out
        cast_prompt = prompts.cast_sheet(sb)
        if cast_prompt:
            rec = self.store.get_step(self._cast_key(img, sb, cast_prompt))
            out["cast"] = rec["assets"]["image"] if rec else None
        if out["cast"] or not cast_prompt:
            for sc, row in zip(sb.scenes, scenes, strict=True):
                it = self._keyframe_item(img, sb, sc, out["cast"], after=False)
                rec = self.store.get_step(it.key) if it.key else None
                row["keyframe"] = rec["assets"]["image"] if rec else None
        if len(narration) == len(sb.scenes):
            tl = self.timeline(narration)
            out["total"] = round(tl.total, 2)
            if all(r["keyframe"] for r in scenes) and any(sc.mode == "video" for sc in sb.scenes):
                board = Board(narration, out["cast"], [r["keyframe"] for r in scenes], tl)
                by_scene = {row["n"]: row for row in scenes}
                for it in self._motion_items(sb, board, self.video()):
                    rec = self.store.get_step(it.key) if it.key else None
                    by_scene[it.scene]["motion"] = rec["assets"]["video"] if rec else None
        return out

    # ---------------------------------------------------------------- all of it
    async def render(self, sb: Storyboard) -> Film:
        board = await self.board(sb)
        motions = await self.motion(sb, board)
        clips = await self.clips(sb, board, motions)
        film = await self.mix(sb, board, clips)
        film.poster = board.keyframes[0] if board.keyframes else None
        return film
