"""A film is a sequence of cached stages, each run as one batch on the engine its story picked.

    board:   narration -> cast sheet + keyframes
    render:  board -> motion for video scenes -> ambience for the silent ones -> one normalised
             clip per scene -> mix

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

from . import check, prompts, registry, text, timing
from . import llm as llms
from .config import Settings
from .db import Database, now
from .engines import catalog, ffmpeg
from .engines.base import (
    CAST_SIZE,
    MAX_REFS,
    PORTRAIT_SIZE,
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
from .storyboard import Scene, Storyboard, next_seed
from .writer import narration_seconds

log = logging.getLogger(__name__)

CLIP = "clip@1"
MIX = "mix@3"  # 2: loudness normalised; 3: cuts are concats, not zero-length crossfades
LABELS = {
    "write": "Writing",
    "narration": "Narration",
    "cast": "Cast sheet",
    "portraits": "Portraits",
    "keyframes": "Pictures",
    "check": "Picture check",
    "motion": "Animation",
    "ambience": "Ambience",
    "clips": "Scene clips",
    "mix": "Final mix",
    "sample": "Voice sample",
}


class BudgetExceeded(RuntimeError):
    """A remote stage would take the story past its budget. Nothing was spent on it; what the story
    made before is cached, so raising the budget carries on from there."""

    def __init__(self, stage: str, need_micros: int, spent_micros: int, budget_micros: int):
        self.stage, self.need, self.spent, self.budget = stage, need_micros, spent_micros, budget_micros
        self.short = spent_micros + need_micros - budget_micros
        super().__init__(
            f"{LABELS.get(stage, stage)} would cost about {usd(need_micros)}, and this story has "
            f"{usd(max(budget_micros - spent_micros, 0))} of its {usd(budget_micros)} budget left: it needs "
            f"{usd(self.short)} more. Raise the story's budget and run it again; nothing made so far is lost."
        )

    def info(self) -> dict:
        return {
            "stage": self.stage,
            "need_micros": self.need,
            "spent_micros": self.spent,
            "budget_micros": self.budget,
            "short_micros": self.short,
        }


def usd(micros: int) -> str:
    """Dollars for a message: cents, or a tenth of a cent below a cent."""
    dollars = micros / 1_000_000
    return f"${dollars:.3f}" if 0 < dollars < 0.01 else f"${dollars:.2f}"


@dataclass
class Event:
    stage: str  # a key of LABELS
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
    # By scene, why the picture check had its picture drawn again: the storyboard now holds its new seed.
    redrawn: dict[int, str] = field(default_factory=dict)
    flagged: dict[int, str] = field(default_factory=dict)  # still failing after the last redraw


@dataclass
class Checked:
    failed: dict[int, str]  # scene: why its picture failed
    asked: set[int]  # the scenes whose verdict was given now, not read from the cache


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


def _scenes(failed: dict[int, str]) -> str:
    return "; ".join(f"scene {n}: {why}" for n, why in failed.items())


def _pid(character: str) -> str:
    return f"portrait-{character}"


def _portraits(sb: Storyboard) -> bool:
    """Whether the story's pictures are drawn from portraits: an imported cast sheet has its own
    layout, so its characters can't be picked out by their place in the row."""
    return sb.portraits and not sb.cast_sheet_prompt


def picture_inputs(sb: Storyboard, sc: Scene) -> tuple:
    """What a scene's picture is drawn from, as the storyboard decides it: whether an edit reached it."""
    m = sb.models
    keyframe = prompts.keyframe(sb, sc, numbered=_numbered(sb, sc))
    return (
        keyframe,
        sb.scene_seed(sc),
        prompts.cast_sheet(sb),
        sb.seed,
        sb.portraits,
        m.image,
        m.image_quality,
    )


def _characters_in(sb: Storyboard, sc: Scene) -> int:
    return sum(c.id in sc.cast for c in sb.characters)


def _numbered(sb: Storyboard, sc: Scene) -> bool:
    """Whether a scene's picture is drawn from the portraits of who is in it, named by number in its
    prompt: past MAX_REFS of them, it's drawn from the whole cast sheet instead."""
    return _portraits(sb) and 0 < _characters_in(sb, sc) <= MAX_REFS


class Pipeline:
    def __init__(
        self,
        cfg: Settings,
        emit: Callable[[Event], None] | None = None,
        db: Database | None = None,
        story_id: str | None = None,
        job_id: str | None = None,
        user_cancelled: Callable[[], bool] = lambda: False,
        budget_micros: int | None = None,
    ):
        self.cfg = cfg
        self.store = Store(cfg.library)
        self._emit = emit or (lambda e: None)
        self.db, self.story_id, self.job_id = db, story_id, job_id
        self.user_cancelled = user_cancelled
        self.budget_micros = budget_micros  # the story's; None checks nothing (the CLI)

    def emit(self, stage: str, status: str, **kw) -> None:
        self._emit(Event(stage, status, **kw))

    # ---------------------------------------------------------------- the models a story uses
    def tts(self, sb: Storyboard) -> TtsEngine:
        return catalog.tts(self.cfg, self.db, sb.models.tts or self.cfg.defaults.tts, sb.voice, sb.language)

    def image(self, sb: Storyboard) -> Engine:
        m = sb.models
        return catalog.image(self.cfg, self.db, m.image or self.cfg.defaults.image, m.image_quality)

    def video(self, sb: Storyboard) -> VideoEngine:
        m = sb.models
        return catalog.video(self.cfg, self.db, m.video or self.cfg.defaults.video, m.video_quality)

    def ambience_engine(self, sb: Storyboard, video: VideoEngine) -> Engine | None:
        """What scores the video scenes: nothing when the video model makes its own sound or it's off."""
        model = sb.models.ambience or self.cfg.defaults.ambience
        if video.entry.audio == "ambience" or model == "none":
            return None
        return catalog.ambience(self.cfg, self.db, model)

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
            if rec := self.cached(it):
                records[it.id] = rec
        pending = [it for it in items if it.id not in records]
        # Each progress row counts its own items: the cast sheet reports apart from the pictures.
        rows = list(dict.fromkeys(it.stage or stage for it in items))
        total = {row: sum((it.stage or stage) == row for it in items) for row in rows}
        done = {row: sum((it.stage or stage) == row for it in items if it.id in records) for row in rows}
        for row in sorted(rows, key=lambda r: r == stage):  # the stage's own row last, as it was
            self.emit(row, "start", done=done[row], total=total[row])
        if pending:
            work = self.store.tmp()
            waited_on = {a for it in pending for a in it.after}

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
                row = it.stage or stage
                self._log_local(maker, row, it, out)
                done[row] += 1
                self.emit(row, "done", scene=it.scene, done=done[row], total=total[row], asset=main)

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
                    stage,
                    "progress",
                    scene=scene,
                    message=message,
                    done=done.get(stage, 0),
                    total=total.get(stage, 0),
                ),
            )
            if bind:
                ctx.bind = lambda it: bind(it, records)
            try:
                if maker.remote:
                    self._check_budget(stage, maker.estimate(pending).micros)
                    if isinstance(maker, Engine) and self.db is not None:
                        await registry.ensure_synced(self.cfg, self.db)
                await maker.run(pending, ctx, on_item)
            finally:
                shutil.rmtree(work, ignore_errors=True)
        for row in rows:
            self.emit(row, "finish", done=total[row], total=total[row])
        return records

    def _check_budget(self, stage: str, need: int) -> None:
        """Stop before a remote stage that would take the story past its budget."""
        if self.budget_micros is None or self.db is None or self.story_id is None:
            return
        spent = self.db.spend_micros(story_id=self.story_id)
        if spent + need > self.budget_micros:
            raise BudgetExceeded(stage, need, spent, self.budget_micros)

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
    def narration_items(self, sb: Storyboard, eng: TtsEngine) -> list[Item]:
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
        if sb.language not in text.LANGUAGES:
            raise ValueError(
                f"stories can't be narrated in '{sb.language}' yet: set the story's language to one of "
                f"{', '.join(text.LANGUAGES)}"
            )
        eng = self.tts(sb)
        languages = eng.entry.languages
        if languages and sb.language not in languages:
            raise ValueError(
                f"narration language '{sb.language}' is not supported by {eng.entry.label} "
                f"(supported: {', '.join(languages)})"
            )
        items = self.narration_items(sb, eng)
        records = await self._stage("narration", eng, items, "audio")
        return [_narration(records[it.id]) for it in items]

    async def sample(self, model: str, voice: str, language: str) -> str:
        """One line spoken by `voice`, to hear it before choosing it; made once, like any narration."""
        eng = catalog.sampler(self.cfg, self.db, model, voice, language)
        item = catalog.sample_item(eng, language)
        return (await self._stage("sample", eng, [item], "audio"))["sample"]["assets"]["audio"]

    # ---------------------------------------------------------------- pictures
    def _cast_key(self, eng: Engine, sb: Storyboard, prompt: str) -> str:
        return eng.key("cast", prompt=prompt, seed=sb.seed, size=list(CAST_SIZE))

    def _portrait_key(self, eng: Engine, prompt: str, seed: int, cast: str) -> str:
        return eng.key("portrait", prompt=prompt, seed=seed, size=list(PORTRAIT_SIZE), refs=[cast])

    def _keyframe_key(self, eng: Engine, prompt: str, seed: int, refs: list[str]) -> str:
        return eng.key("keyframe", prompt=prompt, seed=seed, size=list(keyframe_size(self.cfg)), refs=refs)

    def keyframe_item(
        self, eng: Engine, sb: Storyboard, sc: Scene, refs: list[str], after: tuple[str, ...] = ()
    ) -> Item:
        """A scene's picture, drawn from `refs`: stored assets, and the ids of the items in `after`,
        drawn in the same batch, that it waits on."""
        p, seed = prompts.keyframe(sb, sc, numbered=_numbered(sb, sc)), sb.scene_seed(sc)
        w, h = keyframe_size(self.cfg)
        params = {"prompt": p, "seed": seed, "width": w, "height": h, "refs": refs}
        if after:
            return Item(_sid(sc), None, sc.n, params, after=after)
        return Item(_sid(sc), self._keyframe_key(eng, p, seed, refs), sc.n, params)

    def cast_item(self, eng: Engine, sb: Storyboard) -> Item | None:
        prompt = prompts.cast_sheet(sb)
        if not prompt:
            return None
        w, h = CAST_SIZE
        params = {"prompt": prompt, "seed": sb.seed, "width": w, "height": h, "refs": []}
        return Item("cast", self._cast_key(eng, sb, prompt), None, params, stage="cast")

    def portrait_items(self, eng: Engine, sb: Storyboard, cast: str | None) -> list[Item]:
        """Each character drawn alone from the cast sheet, when the story uses portraits and has more
        than one character (one character's sheet is its portrait). Without `cast` they wait on the sheet."""
        if not _portraits(sb) or len(sb.characters) < 2:
            return []
        w, h = PORTRAIT_SIZE
        items = []
        for c in sb.characters:
            prompt = prompts.portrait(sb, c)
            params = {"prompt": prompt, "seed": sb.seed, "width": w, "height": h, "refs": [cast or "cast"]}
            key = self._portrait_key(eng, prompt, sb.seed, cast) if cast else None
            after = () if cast else ("cast",)
            items.append(Item(_pid(c.id), key, None, params, after=after, stage="portraits"))
        return items

    def faces(self, sb: Storyboard, cast: str | None, records: dict[str, dict]) -> dict[str, str]:
        """Each character's reference, by id: their portrait's asset, or, not drawn yet, its item id."""
        if len(sb.characters) == 1:
            return {sb.characters[0].id: cast or "cast"}
        return {
            c.id: records[_pid(c.id)]["assets"]["image"] if _pid(c.id) in records else _pid(c.id)
            for c in sb.characters
        }

    def scene_refs(self, sb: Storyboard, sc: Scene, cast: str | None, faces: dict[str, str]) -> list[str]:
        """What a scene's picture is drawn from, in a story with portraits: the portraits of who is in
        it, and nothing for a scene with nobody in it; past MAX_REFS of them, the whole cast sheet."""
        if _numbered(sb, sc):
            return [faces[c] for c in sc.cast if c in faces]
        return [cast or "cast"] if _characters_in(sb, sc) else []

    def picture_items(self, eng: Engine, sb: Storyboard) -> tuple[list[Item], list[Item], list[Item]]:
        """The cast sheet, the portraits and every scene's keyframe, as the cache stands: a keyframe
        whose references aren't drawn yet has no key, so it can't be a hit and the estimate counts it."""
        cast_item = self.cast_item(eng, sb)
        sheet = [cast_item] if cast_item else []
        rec = self.cached(cast_item) if cast_item else None
        cast = rec["assets"]["image"] if rec else None
        portraits = self.portrait_items(eng, sb, cast)
        if _portraits(sb):
            drawn = {it.id: r for it in portraits if (r := self.cached(it))}
            faces = self.faces(sb, cast, drawn)
            pending = {"cast", *(it.id for it in portraits if it.id not in drawn)}
            keyframes = []
            for sc in sb.scenes:
                refs = self.scene_refs(sb, sc, cast, faces)
                keyframes.append(
                    self.keyframe_item(eng, sb, sc, refs, tuple(r for r in refs if r in pending))
                )
        elif cast_item and not cast:
            keyframes = [self.keyframe_item(eng, sb, sc, ["cast"], ("cast",)) for sc in sb.scenes]
        else:
            keyframes = [self.keyframe_item(eng, sb, sc, [cast] if cast else []) for sc in sb.scenes]
        return sheet, portraits, keyframes

    def cached(self, it: Item) -> dict | None:
        """The item's step record if the cache holds it; an item without a key yet is never cached."""
        return self.store.get_step(it.key) if it.key else None

    async def draw(self, sb: Storyboard, cast_only: bool = False) -> tuple[str | None, list[str]]:
        """The cast sheet, the portraits and one keyframe per scene, as one batch. An item drawn from a
        picture made in the same batch waits on it, and is keyed once it's stored."""
        eng = self.image(sb)
        sheet, portraits, keyframes = self.picture_items(eng, sb)
        cast = None
        if sheet and (rec := self.cached(sheet[0])):
            cast, sheet = rec["assets"]["image"], []
            self.emit("cast", "cached", asset=cast)
        portrait_ids = {it.id for it in portraits}

        def bind(it: Item, records: dict[str, dict]) -> None:
            p = it.params
            p["refs"] = [records[r]["assets"]["image"] if r in it.after else r for r in p["refs"]]
            it.key = (
                self._portrait_key(eng, p["prompt"], p["seed"], p["refs"][0])
                if it.id in portrait_ids
                else self._keyframe_key(eng, p["prompt"], p["seed"], p["refs"])
            )

        items = sheet + portraits + ([] if cast_only else keyframes)
        records = await self._stage("keyframes", eng, items, "image", bind)
        if "cast" in records:
            cast = records["cast"]["assets"]["image"]
        return cast, [] if cast_only else [records[_sid(sc)]["assets"]["image"] for sc in sb.scenes]

    # ---------------------------------------------------------------- board
    def timeline(self, sb: Storyboard, durations: list[float]) -> timing.Timeline:
        r = self.cfg.render
        continues = [sc.continues for sc in sb.scenes]
        return timing.timeline(durations, r.gap, r.lead_in, r.tail, r.xfade, continues, r.chunk_gap)

    async def board(self, sb: Storyboard) -> Board:
        """Narration and pictures. With a checker, a picture that fails its check is drawn again with a
        new seed, set on its scene in `sb`, which the caller keeps as a new version of the story. Only
        a verdict given in this board redraws: one the cache held was the last word on that picture."""
        narration = await self.narrate(sb)
        cast, keyframes = await self.draw(sb)
        checked = await self.check(sb, keyframes)
        redrawn: dict[int, str] = {}
        for _ in range(check.MAX_REDRAWS):
            again = {n: why for n, why in checked.failed.items() if n in checked.asked}
            if not again:
                break
            for sc in sb.scenes:
                if sc.n in again:
                    sc.seed = next_seed(sb.scene_seed(sc))
            redrawn |= again
            self.emit("check", "progress", message=f"drawing again: {_scenes(again)}")
            cast, keyframes = await self.draw(sb)
            checked = await self.check(sb, keyframes)
        if checked.failed:
            self.emit("check", "progress", message=f"still failing, to look at: {_scenes(checked.failed)}")
        tl = self.timeline(sb, [n.duration for n in narration])
        return Board(narration, cast, keyframes, tl, redrawn, checked.failed)

    # ---------------------------------------------------------------- the picture check
    def check_items(self, sb: Storyboard, keyframes: list[str], model: str) -> list[Item]:
        items = []
        for sc, image in zip(sb.scenes, keyframes, strict=True):
            q = check.question(sb, sc)
            key = step_key("check", engine=check.CHECK, model=model, question=q, image=image)
            items.append(Item(_sid(sc), key, sc.n, {"image": image, "question": q}))
        return items

    async def check(self, sb: Storyboard, keyframes: list[str]) -> Checked:
        """The scenes whose picture the checker fails, with why; nothing when no checker is set."""
        model = self.cfg.defaults.checker
        if not model:
            return Checked({}, set())
        checker = check.Checker(
            self.cfg, model, llms.Calls(self.db, self.story_id, self.job_id, stage="check")
        )
        await checker.price()
        items = self.check_items(sb, keyframes, model)
        records = await self._stage("check", checker, items, "verdict")
        verdicts = {it.scene: records[it.id]["meta"] for it in items if it.scene is not None}
        return Checked({n: v["reason"] for n, v in verdicts.items() if v["verdict"] == "fail"}, checker.asked)

    # ---------------------------------------------------------------- motion
    def motion_items(
        self, sb: Storyboard, tl: timing.Timeline, keyframes: list[str | None], eng: VideoEngine
    ) -> list[Item]:
        """One item per video scene. Without its keyframe (the estimate, before the board) it has no key."""
        items = []
        for i, sc in enumerate(sb.scenes):
            if sc.mode != "video":
                continue
            prompt, seed = prompts.video(sb, sc), sb.video_seed(sc)
            # Unrounded, as it always was: rounding first moves a few local LTX clips by a frame count.
            shots = eng.shots(tl.clip_length(i))
            seconds = round(tl.clip_length(i), 3)
            inputs = {"prompt": prompt, "seed": seed, "keyframe": keyframes[i]}
            key = eng.key("motion", shots=shots, **inputs) if keyframes[i] else None
            items.append(Item(_sid(sc), key, sc.n, {"shots": shots, "seconds": seconds, **inputs}))
        return items

    async def motion(self, sb: Storyboard, board: Board) -> dict[int, str]:
        """Animate every video-mode scene; a slot longer than one generation is chained shots."""
        if not any(sc.mode == "video" for sc in sb.scenes):
            return {}
        eng = self.video(sb)
        items = self.motion_items(sb, board.timeline, list(board.keyframes), eng)
        records = await self._stage("motion", eng, items, "video")
        return {it.scene: records[it.id]["assets"]["video"] for it in items if it.scene is not None}

    # ---------------------------------------------------------------- ambience
    def ambience_items(
        self, sb: Storyboard, motion: list[Item], motions: dict[int, str | None], eng: Engine
    ) -> list[Item]:
        """One item per video scene with a sound line. Without its clip (the estimate) it has no key."""
        by_scene = {sc.n: sc for sc in sb.scenes}
        items = []
        for m in motion:
            sc = by_scene[m.scene] if m.scene is not None else None
            if sc is None or not sc.sound.strip():
                continue
            video = motions.get(sc.n)
            inputs = {
                "prompt": sc.sound.strip(),
                "seed": sb.video_seed(sc),
                "seconds": round(sum(m.params["shots"]), 3),
            }
            key = eng.key("ambience", video=video, **inputs) if video else None
            items.append(Item(_sid(sc), key, sc.n, {"video": video, **inputs}))
        return items

    async def ambience(self, sb: Storyboard, board: Board, motions: dict[int, str]) -> dict[int, str]:
        """A sound bed under each video scene whose model made none; the scored clip replaces its motion."""
        if not motions:
            return motions
        video = self.video(sb)
        eng = self.ambience_engine(sb, video)
        if eng is None:
            return motions
        motion = self.motion_items(sb, board.timeline, list(board.keyframes), video)
        items = self.ambience_items(sb, motion, dict(motions), eng)
        if not items:
            return motions
        records = await self._stage("ambience", eng, items, "video")
        return motions | {it.scene: records[it.id]["assets"]["video"] for it in items if it.scene is not None}

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
            cuts=tl.cuts,
            ambience=r.ambience,
            loudness=r.loudness,
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
        except (FileNotFoundError, ValueError):  # a recording that isn't there, or no such preset
            tts, out["voice_ok"] = None, False
        narration = []
        for it, row in zip(self.narration_items(sb, tts) if tts else [], scenes, strict=False):
            if rec := self.cached(it):
                row["audio"], row["duration"] = rec["assets"]["audio"], rec["meta"]["duration"]
                narration.append(_narration(rec))
        try:
            img = self.image(sb)
        except ValueError:  # the story's picture model left the registry: nothing of it is cached
            return out
        sheet, _, keyframes = self.picture_items(img, sb)
        if sheet and (rec := self.cached(sheet[0])):
            out["cast"] = rec["assets"]["image"]
        for it, row in zip(keyframes, scenes, strict=True):
            rec = self.cached(it)
            row["keyframe"] = rec["assets"]["image"] if rec else None
        if len(narration) == len(sb.scenes):
            tl = self.timeline(sb, [n.duration for n in narration])
            out["total"] = round(tl.total, 2)
            if any(sc.mode == "video" for sc in sb.scenes):
                try:
                    video = self.video(sb)
                except ValueError:  # the story's video model left the registry: none of it is cached
                    return out
                by_scene = {row["n"]: row for row in scenes}
                for it in self.motion_items(sb, tl, [r["keyframe"] for r in scenes], video):
                    rec = self.cached(it)
                    by_scene[it.scene]["motion"] = rec["assets"]["video"] if rec else None
        return out

    # ---------------------------------------------------------------- all of it
    async def render(self, sb: Storyboard, board: Board | None = None) -> Film:
        """The film; from `board` when the caller already made it (and kept what its check changed)."""
        board = board or await self.board(sb)
        motions = await self.ambience(sb, board, await self.motion(sb, board))
        clips = await self.clips(sb, board, motions)
        film = await self.mix(sb, board, clips)
        film.poster = board.keyframes[0] if board.keyframes else None
        return film
