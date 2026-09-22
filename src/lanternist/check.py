"""The picture check: a vision model looks at every scene's picture before any video is made from it.

The 22 Sep review decided it. Once each picture was drawn from the portraits of only who is in it,
what still went wrong was a character drawn twice or someone extra walking in (8 of 71 pictures),
and a clip carries its picture's faults into the video, which is where the money goes. Asked who it
sees and how often, a cheap vision model caught all eight with no false alarm (GPT-5.6 Luna, about
$0.0006 a picture). A reflection in a lake is not a second character, nor a fish in it an intruder:
the question says so, after the first lake story tripped it on both.

A picture that fails is drawn again with a new seed, as a re-roll in the editor would, at most
MAX_REDRAWS times (Pipeline.board). A verdict is a cached step: a second board asks nothing, and a
picture that still failed at the end is only flagged, not drawn again.
"""

import asyncio
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from . import llm as llms
from .config import Settings
from .db import to_micros
from .engines import ffmpeg
from .engines.base import Estimate, Item, Maker, OnItem, Output, StepContext, gather_all
from .prompts import members
from .providers.openrouter import OpenRouterError
from .storyboard import Scene, Storyboard
from .writer import inline_schema, json_text

CHECK = "check@2"  # in every verdict's key, with the question: bump it when SYSTEM, Verdict or the picture sent change
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


class CheckError(RuntimeError):
    """The checker couldn't give a verdict on a picture."""


PICK_ANOTHER = "Pick a checker that takes pictures and structured output in Settings, or clear it."
# What OpenRouter answers a model that can't take a picture or a schema. 503 is "no provider can serve
# this request with the required parameters", once the client's retries are spent.
CANT = (400, 404, 503)


def question(sb: Storyboard, scene: Scene) -> str:
    """What the checker is asked about a scene's picture: who should be in it, once each."""
    who = "\n".join(f"- {m.name}: {m.look}" for m in members(sb, scene, "character")) or "- nobody"
    things = "\n".join(f"- {m.name}: {m.look}" for m in members(sb, scene, "object")) or "- none"
    return (
        "This picture was drawn for one shot of an illustrated film. The shot should show exactly these "
        f"characters, each exactly once:\n{who}\n\nIt may also show these objects:\n{things}\n\n"
        f"The shot as written: {scene.visual.strip()}\n\n"
        "List every character you can see, and how many times each appears. A figure cut off at the edge "
        "counts; a reflection in water, glass or a mirror doesn't. Then report: a character shown more "
        "than once; a person who isn't one of the characters, or an animal of the same kind as one of them "
        "(a second fox where the story has one), while other animals in the scenery are fine; a listed "
        "character who is missing; a character drawn clearly the wrong size or age for their description "
        "(an adult where the text says a tiny cub or a small child); and readable letters or words. The "
        "verdict is 'fail' if any of those is found, else 'pass'."
    )


def failing(record: dict) -> str | None:
    """Why a check's step record fails its picture, or None when the picture passed."""
    verdict = record["meta"]
    return verdict["reason"] if verdict["verdict"] == "fail" else None


class Checker(Maker):
    """Asks the checker about each picture; a picture's verdict is its output, kept as JSON. `asked`
    holds the scenes it gave a verdict on in this run, as against verdicts the cache already held."""

    def __init__(self, cfg: Settings, model: str, calls: llms.Calls):
        self.model = self.label = model
        self.llm = llms.make(cfg, model, None, calls)
        self.remote = isinstance(self.llm, llms.OpenRouterLLM)
        self.per_check = 0  # micro-dollars, once `price()` has read the model's prices
        self.asked: set[int] = set()

    async def price(self) -> None:
        """Read what a check costs, before a batch of them: nothing on the local model."""
        if not isinstance(self.llm, llms.OpenRouterLLM):
            return
        try:
            info = await self.llm.info()
        except llms.LLMError as e:  # not in OpenRouter's list of models with structured output
            raise CheckError(
                f"The picture check can't use {self.model}: OpenRouter doesn't list it with structured "
                f"output. {PICK_ANOTHER}"
            ) from e
        except (OpenRouterError, httpx.HTTPError) as e:
            why = str(e).rstrip(".") or type(e).__name__
            raise CheckError(f"The picture check couldn't read {self.model}'s prices: {why}.") from e
        self.per_check = to_micros(llms.token_price(info.get("pricing") or {}, TOKENS))
        self.label = info.get("name") or self.model  # "OpenAI: GPT-5.6 Luna", for the progress

    def estimate(self, items: list[Item]) -> Estimate:
        return Estimate(items=len(items), micros=self.per_check * len(items))

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        sem = asyncio.Semaphore(CHECKS_AT_ONCE)
        schema = inline_schema(Verdict)

        async def one(it: Item) -> None:
            async with sem:
                ctx.phase(it, "working", None)
                picture = ctx.work / f"{it.id}.jpg"
                await ffmpeg.thumbnail(ctx.store.path(it.params["image"]), picture, PICTURE_WIDTH)
                why = f"The picture check with {self.model} couldn't judge scene {it.scene}'s picture"
                try:
                    reply = await self.llm.chat(
                        SYSTEM,
                        it.params["question"],
                        schema=schema,
                        temperature=0.0,
                        name="picture_check",
                        images=[picture.read_bytes()],
                    )
                    verdict = Verdict.model_validate_json(json_text(reply.text))
                except OpenRouterError as e:
                    # The key, credit or a rate limit is no reason to change checkers: those keep their
                    # own advice.
                    advice = f" {PICK_ANOTHER}" if e.status in CANT else ""
                    raise CheckError(f"{why}: {str(e).rstrip('.')}.{advice}") from e
                except llms.LLMError as e:  # Ollama refusing the model or the picture, or no room to answer
                    raise CheckError(f"{why}: {str(e).rstrip('.')}. {PICK_ANOTHER}") from e
                except ValidationError as e:
                    raise CheckError(f"{why}: its answer wasn't a verdict. {PICK_ANOTHER}") from e
                out = ctx.work / f"{it.id}.json"
                out.write_text(verdict.model_dump_json(), encoding="utf-8")
                if it.scene is not None:
                    self.asked.add(it.scene)
                on_item(Output(it, out, verdict.model_dump()))

        async with self.llm.session():
            await gather_all([one(it) for it in items])
