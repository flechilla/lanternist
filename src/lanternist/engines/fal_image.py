"""Cast sheets and keyframes on fal, in two waves: the cast sheet first, from text, then every
keyframe at once on the model's edit endpoint with the cast sheet as its reference.

The families differ in how a request names its size (a width and height, or an aspect ratio and a
resolution), whether it takes a seed, and how it is priced:

    klein        per megapixel in and out; the cast sheet at the cheaper text-to-image rate
    flux2        per megapixel, references included, rounded up; the first one costs more
    nano_banana  per picture, by resolution
    seedream     per picture, double over 1536x1536, plus each reference after the first
"""

import math
from decimal import Decimal

from ..db import to_micros
from ..providers.fal import FalError
from ..store import step_key
from .base import Estimate, FalEngine, Item, OnItem, Output, StepContext, gather_all

ASPECTS = {
    "1:1": 1.0,
    "4:3": 4 / 3,
    "3:2": 3 / 2,
    "16:9": 16 / 9,
    "21:9": 21 / 9,
    "3:4": 3 / 4,
    "9:16": 9 / 16,
}
REFERENCE_MP = 1.0  # fal resizes reference pictures to about a megapixel before they're counted
LARGE_PIXELS = 1536 * 1536  # Seedream charges double above this


def aspect_ratio(width: int, height: int) -> str:
    return min(ASPECTS, key=lambda k: abs(ASPECTS[k] - width / height))


class FalImage(FalEngine):
    def key(self, kind: str, **inputs) -> str:
        return step_key(kind, engine=self.engine_id, options=self.options(), **inputs)

    def arguments(self, item: Item, refs: list[str]) -> dict:
        p = item.params
        a = {"prompt": p["prompt"], **self.options()}
        if self.entry.family == "nano_banana":
            a["aspect_ratio"] = aspect_ratio(p["width"], p["height"])
        else:
            a["image_size"] = {"width": p["width"], "height": p["height"]}
        if self.entry.seed:
            a["seed"] = p["seed"]
        if refs:
            a["image_urls"] = refs
        return a

    def cost(self, item: Item) -> tuple[Decimal, int]:
        """One picture's billable units and list price, in micro-dollars."""
        p = item.params
        refs = len(p["refs"])
        out_mp = Decimal(p["width"] * p["height"]) / 1_000_000
        in_mp = Decimal(str(REFERENCE_MP)) * refs
        family = self.entry.family
        if family == "klein":
            units = out_mp + in_mp
            return units, self.micros(units, None if refs else "text_to_image")
        if family == "flux2":
            units = Decimal(math.ceil(out_mp + in_mp))
            first = self.entry.price.on().first or self.unit_price()
            return units, to_micros(first + (units - 1) * self.unit_price())
        if family == "seedream":
            large = p["width"] * p["height"] > LARGE_PIXELS
            extra = self.micros(max(refs - 1, 0), "extra_reference")
            return Decimal(1), self.micros(1, "large" if large else None) + extra
        return Decimal(1), self.micros(1, self.quality)

    def estimate(self, items: list[Item]) -> Estimate:
        est = Estimate()
        for it in items:
            units, micros = self.cost(it)
            est = est + Estimate(items=1, units=units, micros=micros)
        return est

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        first = [it for it in items if not it.after]
        later = [it for it in items if it.after]
        await gather_all([self.draw(it, ctx, on_item) for it in first])
        for it in later:
            ctx.bind(it)
        await gather_all([self.draw(it, ctx, on_item) for it in later])

    async def draw(self, item: Item, ctx: StepContext, on_item: OnItem) -> None:
        refs = [await self.upload(ctx, a) for a in item.params["refs"]]
        res = await self.request(
            ctx, item, self.arguments(item, refs), None if refs else "text_to_image", self.cost(item)[1]
        )
        images = res.data.get("images") or []
        what = f"scene {item.scene}'s picture" if item.scene is not None else "the cast sheet"
        if not images:
            raise FalError(f"{self.entry.label} returned no picture for {what}: draw it again")
        if any(res.data.get("has_nsfw_concepts") or []):
            # klein hands back a black picture when its safety checker trips.
            raise FalError(
                f"fal's safety check blanked {what}. Change what the scene shows and draw it again, "
                "or pick another picture model.",
                type="content_policy_violation",
            )
        path = await self.fetch(images[0]["url"], ctx.work / f"{item.id}.png")
        on_item(Output(item, path))
