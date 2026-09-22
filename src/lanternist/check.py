"""The picture check: a vision model looks at every scene's picture before any video is made from it.

The 22 Sep review decided it. Once each picture was drawn from the portraits of only who is in it,
what still went wrong was a character drawn twice or someone extra walking in (8 of 71 pictures),
and a clip carries its picture's faults into the video, which is where the money goes. Asked who it
sees and how often, a cheap vision model caught all eight with no false alarm (GPT-5.6 Luna, about
$0.0006 a picture). A picture that fails is drawn again with a new seed, as a re-roll in the editor
would, at most MAX_REDRAWS times (Pipeline.board). A verdict is a cached step, so a second board
asks nothing.
"""

import asyncio
from typing import Literal

from pydantic import BaseModel, Field

from . import llm as llms
from .config import Settings
from .db import to_micros
from .engines import ffmpeg
from .engines.base import Item, Maker, OnItem, Output, StepContext, gather_all
from .prompts import members
from .storyboard import Scene, Storyboard
from .writer import inline_schema, json_text

CHECK = "check@1"  # in every verdict's key: bump it when the question changes
MAX_REDRAWS = 2
PICTURE_WIDTH = 1024  # what the model is shown: enough to count faces, and few tokens
CHECKS_AT_ONCE = 4
TOKENS = {"in": 1500, "out": 500}  # one check, for its price: the picture, the question and the verdict

SYSTEM = (
    "You check the pictures drawn for an illustrated film against what each shot should show. Look "
    "literally, and report only what you can see."
)


class Seen(BaseModel):
    who: str
    count: int


class Verdict(BaseModel):
    seen: list[Seen] = Field(description="every person and animal in the picture, grouped by who they are")
    duplicated: list[str] = Field(description="characters shown more than once")
    unexpected: list[str] = Field(description="people or animals who aren't among the characters")
    missing: list[str] = Field(description="characters who should be there and aren't")
    wrong_size: list[str] = Field(
        description="characters clearly the wrong size or age for their description"
    )
    text: bool = Field(description="readable letters or words appear")
    verdict: Literal["pass", "fail"]
    reason: str = Field(description="one sentence: what's wrong, or that all is well")


def question(sb: Storyboard, scene: Scene) -> str:
    """What the checker is asked about a scene's picture: who should be in it, once each."""
    who = "\n".join(f"- {m.name}: {m.look}" for m in members(sb, scene, "character")) or "- nobody"
    things = "\n".join(f"- {m.name}: {m.look}" for m in members(sb, scene, "object")) or "- none"
    return (
        "This picture was drawn for one shot of an illustrated film. The shot should show exactly these "
        f"characters, each exactly once:\n{who}\n\nIt may also show these objects:\n{things}\n\n"
        f"The shot as written: {scene.visual.strip()}\n\n"
        "List every person and animal you can see, grouped by who they are, with how many times each "
        "appears (a reflection or a figure cut off at the edge counts). Then report: anyone who appears "
        "more than once; any person or animal who isn't one of the characters above; any listed character "
        "who is missing; any character drawn clearly the wrong size or age for their description (an adult "
        "where the text says a tiny cub or a small child); and whether readable letters or words appear. "
        "The verdict is 'fail' if any of those is found, else 'pass'."
    )


class Checker(Maker):
    """Asks the checker about each picture; a picture's verdict is its output, kept as JSON."""

    def __init__(self, cfg: Settings, model: str, calls: llms.Calls):
        self.llm = llms.make(cfg, model, None, calls)
        self.remote = self.llm.provider == "openrouter"

    async def estimate_micros(self, checks: int) -> int:
        """What `checks` pictures cost to check: nothing on the local model."""
        if not isinstance(self.llm, llms.OpenRouterLLM):
            return 0
        pricing = (await self.llm.info()).get("pricing") or {}
        return checks * to_micros(llms.token_price(pricing, TOKENS))

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        sem = asyncio.Semaphore(CHECKS_AT_ONCE)
        schema = inline_schema(Verdict)

        async def one(it: Item) -> None:
            async with sem:
                picture = ctx.work / f"{it.id}.jpg"
                await ffmpeg.thumbnail(ctx.store.path(it.params["image"]), picture, PICTURE_WIDTH)
                reply = await self.llm.chat(
                    SYSTEM,
                    it.params["question"],
                    schema=schema,
                    temperature=0.0,
                    name="picture_check",
                    images=[picture.read_bytes()],
                )
                verdict = Verdict.model_validate_json(json_text(reply.text))
                out = ctx.work / f"{it.id}.json"
                out.write_text(verdict.model_dump_json(), encoding="utf-8")
                on_item(Output(it, out, verdict.model_dump()))

        async with self.llm.session():
            await gather_all([one(it) for it in items])
