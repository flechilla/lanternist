"""Image-to-video on fal.

A scene's clip is planned as the cheapest shots the model bills (`timing.plan_shots`). Every shot
after the first starts from the last frame of the one before, and every shot is a step of its own
in the cache, so a scene that fails halfway doesn't pay again for the shots it already has. The
scenes of a stage all run at once, up to fal's concurrency.

The families differ only in how a request names things:

    kling  start_image_url, duration "5", a negative prompt; no seed
    veo    image_url, duration "6s", a negative prompt and a seed
    wan    image_url, duration "5", a negative prompt and a seed (Wan 2.6)
    wan3   start_image_url, duration 5; no seed (Wan 3.0)
    ltx    image_url, duration 6; no seed
    h3     image_url, duration 5 and a seed (MiniMax H3 Max)
"""

from collections.abc import Callable
from decimal import Decimal

from .. import timing
from ..keys import redact
from ..prompts import VIDEO_NEGATIVE
from ..store import step_key
from . import ffmpeg
from .base import Estimate, FalEngine, Item, OnItem, Output, StepContext, VideoEngine, gather_all

IMAGE_FIELD = {"kling": "start_image_url", "wan3": "start_image_url"}
DURATION: dict[str, Callable[[int], str]] = {"kling": str, "wan": str, "veo": lambda s: f"{s}s"}
NEGATIVE = {"kling", "veo", "wan"}  # the families that take a negative prompt


class FalVideo(FalEngine, VideoEngine):
    def plan(self, seconds: float) -> timing.ShotPlan:
        if self.entry.durations is None:
            raise ValueError(f"{self.entry.id} lists no billable durations in the registry")
        return timing.plan_shots(seconds, self.entry.durations.lengths(), self.cfg.render.hold_max)

    def shots(self, seconds: float) -> list[float]:
        return self.plan(seconds).shots

    @property
    def negative(self) -> str | None:
        return VIDEO_NEGATIVE if self.entry.family in NEGATIVE else None

    def key(self, kind: str, **inputs) -> str:
        return step_key(kind, engine=self.engine_id, options=self.options(), negative=self.negative, **inputs)

    def estimate(self, items: list[Item]) -> Estimate:
        est = Estimate()
        for it in items:
            paid = round(sum(it.params["shots"]), 3)
            est = est + Estimate(
                items=1,
                units=Decimal(str(paid)),
                micros=self.micros(paid, self.quality),
                paid_seconds=paid,
                waste_seconds=round(max(paid - it.params["seconds"], 0.0), 3),
            )
        return est

    def arguments(self, item: Item, shot: int, seconds: float, image_url: str) -> dict:
        family = self.entry.family or ""
        whole = round(seconds)
        a: dict = {
            "prompt": item.params["prompt"],
            IMAGE_FIELD.get(family, "image_url"): image_url,
            "duration": DURATION[family](whole) if family in DURATION else whole,
            **self.options(),
        }
        if self.negative:
            a["negative_prompt"] = self.negative
        if self.entry.seed:
            a["seed"] = item.params["seed"] + shot  # as local LTX seeds its chained shots
        return a

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        await gather_all([self.animate(it, ctx, on_item) for it in items])

    async def animate(self, item: Item, ctx: StepContext, on_item: OnItem) -> None:
        shots, n = item.params["shots"], item.scene
        image, image_path = item.params["keyframe"], None
        parts = []
        for j, seconds in enumerate(shots):
            key = step_key("shot", motion=item.key, index=j)
            rec = ctx.store.get_step(key)
            if rec is None:
                if len(shots) > 1:
                    ctx.note(f"scene {n}: shot {j + 1} of {len(shots)}, {seconds:g} s", n)
                url = await self.upload(ctx, image, path=image_path)
                shot = Item(f"{item.id}-{j}", key, n, item.params)
                res = await self.request(
                    ctx,
                    shot,
                    self.arguments(item, j, seconds, url),
                    estimate=self.micros(seconds, self.quality),
                )
                clip = await self.fetch(res.data["video"]["url"], ctx.work / f"{shot.id}.mp4")
                # A model that rewrites its prompt (H3's prompt expansion) says what it made the clip from.
                meta = {"seconds": seconds} | (
                    {"expanded_prompt": redact(res.data["expanded_prompt"])}
                    if res.data.get("expanded_prompt")
                    else {}
                )
                rec = ctx.store.put_step(key, {"assets": {"video": ctx.store.put(clip)}, "meta": meta})
            parts.append(ctx.store.path(rec["assets"]["video"]))
            if j + 1 < len(shots):
                # The next shot starts where this one ends; its frame is named for the shot it came from.
                image, image_path = f"{key}-last.png", ctx.work / f"{item.id}-{j}-last.png"
                await ffmpeg.last_frame(parts[-1], image_path)
        joined = ctx.work / f"{item.id}.mp4"
        await ffmpeg.concat(parts, joined, faststart=True)
        on_item(Output(item, joined, {"shots": shots}))
