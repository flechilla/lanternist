"""Ambience on fal, for clips from video models that make no sound of their own.

MMAudio v2 watches the scene's clip and reads its sound line, and returns the clip with a sound bed
muxed in. Only its sound is kept: it is laid under our own copy of the picture, so the clip we cut
is never re-encoded, nor trimmed to the 30 s MMAudio can score (a longer clip goes quiet after it).
"""

from decimal import Decimal

from ..store import step_key
from . import ffmpeg
from .base import Estimate, FalEngine, Item, OnItem, Output, StepContext, gather_all

NEGATIVE = "speech, talking, voices, singing, music"  # the narration goes on top
MAX_SECONDS = 30.0
MAX_SEED = 65535


class FalMmaudio(FalEngine):
    def key(self, kind: str, **inputs) -> str:
        return step_key(kind, engine=self.engine_id, options=self.options(), negative=NEGATIVE, **inputs)

    def estimate(self, items: list[Item]) -> Estimate:
        est = Estimate()
        for it in items:
            seconds = min(it.params["seconds"], MAX_SECONDS)
            est = est + Estimate(items=1, units=Decimal(str(seconds)), micros=self.micros(seconds))
        return est

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        await gather_all([self.score(it, ctx, on_item) for it in items])

    async def score(self, item: Item, ctx: StepContext, on_item: OnItem) -> None:
        p = item.params
        seconds = min(p["seconds"], MAX_SECONDS)
        arguments = {
            "video_url": await self.upload(ctx, p["video"]),
            "prompt": p["prompt"],
            "negative_prompt": NEGATIVE,
            "seed": p["seed"] % (MAX_SEED + 1),
            "duration": seconds,
            **self.options(),
        }
        res = await self.request(ctx, item, arguments, estimate=self.micros(seconds))
        scored = await self.fetch(res.data["video"]["url"], ctx.work / f"{item.id}-scored.mp4")
        out = ctx.work / f"{item.id}.mp4"
        await ffmpeg.mux_audio(ctx.store.path(p["video"]), scored, out)
        on_item(Output(item, out, {"seconds": seconds}))
