"""The writer's LLMs: the local model through Ollama, or any OpenRouter model with structured output.

Both answer `chat(system, user, schema=None, temperature=0.8, images=None) -> Reply`; the picture
check (check.py) sends a picture with its question. `session()` holds the GPU lease for the local
model only, so a story written on OpenRouter never touches the GPU. When a `Calls` log is given,
every call becomes a `step_runs` row (its stage, "write" for the writer) with its tokens, time and,
for OpenRouter, the cost it reports. The model ids are `ollama/<tag>` and `openrouter/<model id>`.
"""

import asyncio
import base64
import logging
import time
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, get_args, override

import httpx

from . import keys
from .config import Settings
from .db import LOCAL, Database, now, to_micros, to_usd
from .gpu import lease
from .providers import transport
from .providers.openrouter import OpenRouter as OpenRouterClient
from .providers.openrouter import OpenRouterError
from .storyboard import Effort

log = logging.getLogger(__name__)

EFFORTS: tuple[Effort, ...] = get_args(Effort)
EFFORT_NAMES: dict[Effort, str] = {
    "none": "Off",
    "minimal": "Minimal",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra high",
    "max": "Max",
}
MAX_TOKENS = 32_000  # room for reasoning plus the longest storyboard; raised once on a "length" stop
FALLBACK_MAX_TOKENS = 16_384


class LLMError(RuntimeError):
    """A writer call failed. `cost_micros` is what it was billed anyway, when it was."""

    def __init__(self, message: str, cost_micros: int | None = None):
        super().__init__(message)
        self.cost_micros = cost_micros


@dataclass
class Reply:
    text: str
    model: str  # the writer id as called, e.g. "openrouter/openai/gpt-5.6-luna"
    tokens_in: int | None = None
    tokens_out: int | None = None  # includes reasoning tokens
    reasoning_tokens: int | None = None
    cost_micros: int | None = None  # what OpenRouter charged; None for local models
    seconds: float = 0.0
    served_by: str | None = None  # OpenRouter's upstream provider
    effort: str | None = None  # the reasoning effort actually sent


def _paid(usages: list[dict]) -> int | None:
    """What OpenRouter charged for these attempts, from their usage; None if none of them says."""
    costs = [to_micros(u["cost"]) for u in usages if u.get("cost") is not None]
    return sum(costs) if costs else None


@dataclass
class Calls:
    """The LLM calls of one job (or of a CLI run, with no job), the writer's or the picture check's,
    logged as step_runs rows."""

    db: Database | None = None
    story_id: str | None = None
    job_id: str | None = None
    stage: str = "write"  # a key of pipeline.LABELS
    replies: list[Reply] = field(default_factory=list)
    owner: str = field(kw_only=True)  # whose calls these are, and so whose spend

    def start(self, llm: "LLM") -> int | None:
        if self.db is None:
            return None
        return self.db.start_run(
            owner_id=self.owner,
            story_id=self.story_id,
            job_id=self.job_id,
            stage=self.stage,
            model_id=llm.id,
            provider=llm.provider,
            status="running",
            started_at=now(),
        )

    def done(self, run_id: int | None, reply: Reply) -> None:
        self.replies.append(reply)
        if run_id is None or self.db is None:
            return
        self.db.update_run(
            run_id,
            status="done",
            finished_at=now(),
            wall_seconds=round(reply.seconds, 2),
            units=(reply.tokens_in or 0) + (reply.tokens_out or 0),
            unit="token",
            cost_micros=reply.cost_micros,
            cost_source="none" if reply.cost_micros is None else "reported",
            meta={
                "tokens_in": reply.tokens_in,
                "tokens_out": reply.tokens_out,
                "reasoning_tokens": reply.reasoning_tokens,
                "served_by": reply.served_by,
                "effort": reply.effort,
            },
        )

    def failed(self, run_id: int | None, error: BaseException, seconds: float) -> None:
        if run_id is None or self.db is None:
            return
        cancelled = isinstance(error, asyncio.CancelledError)
        paid = error.cost_micros if isinstance(error, LLMError) else None
        self.db.update_run(
            run_id,
            status="cancelled" if cancelled else "failed",
            finished_at=now(),
            wall_seconds=round(seconds, 2),
            error=None if cancelled else keys.redact(str(error))[:2000],
            cost_micros=paid,
            cost_source="none" if paid is None else "reported",
        )

    @property
    def cost_micros(self) -> int | None:
        costs = [r.cost_micros for r in self.replies if r.cost_micros is not None]
        return sum(costs) if costs else None

    def summary(self) -> dict:
        """What the job result shows: which writer, what it cost, how many tokens."""
        return {
            "writer": self.replies[-1].model if self.replies else None,
            "cost_usd": to_usd(self.cost_micros),
            "calls": len(self.replies),
            "tokens_in": sum(r.tokens_in or 0 for r in self.replies),
            "tokens_out": sum(r.tokens_out or 0 for r in self.replies),
        }


class LLM:
    id: str
    provider: str

    def __init__(self, calls: Calls | None = None):
        self.calls = calls or Calls(owner=LOCAL)  # with no database it logs nothing, for no one

    def session(self) -> AbstractAsyncContextManager:
        """Held around a whole story, so the local model loads once."""
        return nullcontext()

    async def chat(
        self,
        system: str,
        user: str,
        schema: dict | None = None,
        temperature: float = 0.8,
        name: str = "answer",
        images: list[bytes] | None = None,
    ) -> Reply:
        """`images`: JPEG pictures the model looks at before reading `user`."""
        run_id = self.calls.start(self)
        t0 = time.monotonic()
        try:
            reply = await self._chat(system, user, schema, temperature, name, images or [])
        except BaseException as e:  # a cancel too: the row must not stay "running"
            self.calls.failed(run_id, e, time.monotonic() - t0)
            raise
        reply.seconds = time.monotonic() - t0
        self.calls.done(run_id, reply)
        return reply

    async def _chat(
        self, system: str, user: str, schema: dict | None, temperature: float, name: str, images: list[bytes]
    ) -> Reply:
        raise NotImplementedError


def _b64(image: bytes) -> str:
    return base64.b64encode(image).decode()


class Ollama(LLM):
    provider = "ollama"

    def __init__(self, cfg: Settings, model: str | None = None, calls: Calls | None = None):
        super().__init__(calls)
        self.cfg = cfg
        self.model = model or cfg.ollama.model
        self.id = f"ollama/{self.model}"

    def session(self) -> AbstractAsyncContextManager:
        return lease(self.cfg, "ollama", self.cfg.ollama.vram_gb)

    @override
    async def _chat(
        self, system: str, user: str, schema: dict | None, temperature: float, name: str, images: list[bytes]
    ) -> Reply:
        asked: dict[str, Any] = {"role": "user", "content": user}
        if images:
            asked["images"] = [_b64(i) for i in images]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, asked],
            "stream": False,
            "think": False,
            "keep_alive": "2m",
            "options": {"num_ctx": self.cfg.ollama.num_ctx, "temperature": temperature},
        }
        if schema:
            body["format"] = schema
        async with httpx.AsyncClient(
            transport=transport(self.cfg), timeout=httpx.Timeout(600, connect=10)
        ) as client:
            r = await client.post(f"{self.cfg.ollama.url}/api/chat", json=body)
        if r.status_code != 200:
            raise LLMError(f"Ollama couldn't write with {self.model} (HTTP {r.status_code}): {r.text[:500]}")
        data = r.json()
        return Reply(
            text=data["message"]["content"],
            model=self.id,
            tokens_in=data.get("prompt_eval_count"),
            tokens_out=data.get("eval_count"),
        )


def strict_schema(schema: dict) -> dict:
    """A schema OpenAI-style strict mode accepts: every object closed, every property required, no defaults."""

    def walk(node, in_properties=False):
        if isinstance(node, list):
            return [walk(v) for v in node]
        if not isinstance(node, dict):
            return node
        if in_properties:
            return {k: walk(v) for k, v in node.items()}
        out = {k: walk(v, k == "properties") for k, v in node.items() if k != "default"}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out

    return walk(schema)


def pick_effort(requested: Effort | None, info: dict) -> Effort | None:
    """The effort to send: the requested one, or the nearest the model supports; None leaves the model's default."""
    supported = (info.get("reasoning") or {}).get("supported_efforts") or []
    efforts = [e for e in EFFORTS if e in supported]
    if requested is None or not efforts:
        return None
    if requested in efforts:
        return requested
    want = EFFORTS.index(requested)
    return min(efforts, key=lambda e: (abs(EFFORTS.index(e) - want), -EFFORTS.index(e)))


class OpenRouterLLM(LLM):
    provider = "openrouter"

    def __init__(self, cfg: Settings, model: str, effort: Effort | None = None, calls: Calls | None = None):
        super().__init__(calls)
        self.cfg, self.model, self.effort = cfg, model, effort
        self.id = f"openrouter/{model}"
        self.client = OpenRouterClient(cfg)
        self._info: dict | None = None
        self._endpoints: list[set[str]] | None = None

    async def info(self) -> dict:
        """The model's entry in OpenRouter's list: which parameters it takes, its efforts and limits."""
        if self._info is None:
            listed = {m["id"]: m for m in await self.client.models()}
            if self.model not in listed:
                raise LLMError(
                    f"{self.model} isn't an OpenRouter model with structured output; pick another writer"
                )
            self._info = listed[self.model]
        return self._info

    async def endpoint_params(self) -> list[set[str]]:
        """The parameters each provider of this model takes; one set of the model's union if the list fails."""
        if self._endpoints is None:
            try:
                found = await self.client.endpoints(self.model)
                self._endpoints = [set(e.get("supported_parameters") or []) for e in found]
            except (OpenRouterError, httpx.HTTPError) as e:
                # The union can promise what no single provider takes (it did for Opus 5): say so, in case.
                log.warning(
                    "no provider list for %s (%s); going by the model's own parameters", self.model, e
                )
                self._endpoints = []
            if not self._endpoints:
                self._endpoints = [set((await self.info()).get("supported_parameters") or [])]
        return self._endpoints

    async def _parameters(self, schema: dict | None, reasoning: dict | None) -> set[str]:
        """The optional parameters to send, most needed first. With a schema the request must route to
        one provider that takes all of them; without one, providers ignore what they lack."""
        endpoints = await self.endpoint_params()
        send = {"structured_outputs"} if schema else set()
        for p in ("reasoning", "max_tokens", "temperature"):
            if p == "reasoning" and reasoning is None:
                continue
            if any((send if schema else set()) | {p} <= e for e in endpoints):
                send.add(p)
        return send

    @override
    async def _chat(
        self, system: str, user: str, schema: dict | None, temperature: float, name: str, images: list[bytes]
    ) -> Reply:
        info = await self.info()
        effort = pick_effort(self.effort, info)
        reasoning = (
            None
            if effort is None
            else {"effort": effort}
            if effort == "none"
            else {"effort": effort, "exclude": True}
        )
        send = await self._parameters(schema, reasoning)
        if "reasoning" not in send:
            reasoning = effort = None
        cap = ((info.get("top_provider") or {}).get("max_completion_tokens")) or FALLBACK_MAX_TOKENS
        max_tokens = min(cap, MAX_TOKENS) if "max_tokens" in send else None
        pictures = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_b64(i)}"}} for i in images
        ]
        asked: str | list[dict] = [*pictures, {"type": "text", "text": user}] if pictures else user
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": asked}]
        wasted: list[dict] = []  # usage of attempts that were paid for but wrote nothing
        for attempt in range(2):
            try:
                res = await self.client.chat(
                    self.model,
                    messages,
                    schema=strict_schema(schema) if schema else None,
                    schema_name=name,
                    temperature=temperature if "temperature" in send else None,
                    max_tokens=max_tokens,
                    reasoning=reasoning,
                )
                break
            except OpenRouterError as e:
                if e.type != "length":
                    raise
                wasted.append(e.meta.get("usage") or {})
                # Reasoning ate the whole budget: once more with twice the room, if the model allows it.
                if attempt or max_tokens is None or max_tokens >= cap:
                    raise LLMError(
                        f"{self.model} spent its whole token budget and wrote nothing: "
                        "pick a lower reasoning effort or another writer",
                        cost_micros=_paid(wasted),
                    ) from e
                max_tokens = min(cap, max_tokens * 2)
        usages = [*wasted, res.usage]

        def total(key: str, sub: str | None = None) -> int | None:
            vals = [(u.get(sub) or {}).get(key) if sub else u.get(key) for u in usages]
            return sum(v for v in vals if v is not None) if any(v is not None for v in vals) else None

        return Reply(
            text=res.text,
            model=self.id,
            tokens_in=total("prompt_tokens"),
            tokens_out=total("completion_tokens"),
            reasoning_tokens=total("reasoning_tokens", "completion_tokens_details"),
            cost_micros=_paid(usages),
            served_by=res.provider,
            effort=effort,
        )


def writer_id(cfg: Settings, requested: str | None = "") -> str:
    """The writer to use: the one asked for, else the default from Settings, else the local model."""
    return requested or cfg.defaults.writer or f"ollama/{cfg.ollama.model}"


def parse(writer: str) -> tuple[str, str]:
    """A writer id's provider ("ollama" or "openrouter") and model."""
    provider, _, model = writer.partition("/")
    return provider, model


def _runs_here(cfg: Settings, writer: str | None) -> tuple[str, str]:
    """The writer's provider and model; LLMError for a local writer in the hosted edition, which has
    no Ollama."""
    provider, model = parse(writer_id(cfg, writer))
    if provider == "ollama" and cfg.hosted_edition:
        raise LLMError(
            f"{model} runs on your own machine, which this edition doesn't: pick an OpenRouter writer"
        )
    return provider, model


def make(
    cfg: Settings, writer: str | None = "", effort: Effort | None = None, calls: Calls | None = None
) -> LLM:
    provider, model = _runs_here(cfg, writer)
    if provider == "ollama":
        return Ollama(cfg, model, calls)
    return OpenRouterLLM(cfg, model, effort, calls)


def check_key(cfg: Settings, writer: str | None = "") -> None:
    """Raises LLMError when the writer can't run here, or runs on OpenRouter and there's no key for it."""
    remote = _runs_here(cfg, writer)[0] == "openrouter"
    if remote and not keys.get_key("openrouter", fake=cfg.fake_engines).value:
        raise LLMError("this writer runs on OpenRouter: add an OpenRouter key in Settings first")


# ---------------------------------------------------------------------------------- the writer picker
# Tokens a story takes per minute of narration, both passes and any length revision included, with
# reasoning at the model's default effort. From the Phase B trials on 21 Sep 2026: three 3-minute
# stories per model, in English, Spanish and Portuguese (plans/M2_PLAN.md). Reasoning is most of the output,
# so models differ by 4x; stories written here replace these numbers as they finish.
TRIAL_TOKENS_PER_MINUTE = {
    "openrouter/anthropic/claude-opus-5": {"in": 921, "out": 2613},
    "openrouter/anthropic/claude-sonnet-5": {"in": 939, "out": 6012},
    "openrouter/deepseek/deepseek-v4.1-flash": {"in": 649, "out": 4727},
    "openrouter/google/gemini-3.8-flash": {"in": 384, "out": 7866},
    "openrouter/openai/gpt-5.6-luna": {"in": 507, "out": 1855},
}
TYPICAL_TOKENS_PER_MINUTE = {"in": 700, "out": 2900}  # the median of those 21 trial stories


@dataclass
class Writer:
    """One row of the writer picker."""

    id: str
    label: str
    provider: str
    model: str
    local: bool
    recommended: bool = False
    usd_per_minute: float | None = None  # the estimate, for display
    basis: str = "unknown"  # where its token counts come from: free, measured, trial, typical or unknown
    efforts: list[dict] | None = None  # [{id, name}], lowest first
    default_effort: str | None = None
    price_in: float | None = None  # USD per million tokens, for display
    price_out: float | None = None
    unavailable: bool = False  # the default writer, though neither Ollama nor OpenRouter lists it now


def _price(pricing: dict, key: str) -> Decimal:
    """USD per token, from OpenRouter's decimal strings."""
    return Decimal(str(pricing.get(key) or "0"))


def token_price(pricing: dict, tokens: dict) -> Decimal:
    """USD for this many tokens in and out, at OpenRouter's prices."""
    return _price(pricing, "prompt") * tokens["in"] + _price(pricing, "completion") * tokens["out"]


def per_minute_micros(pricing: dict, tokens: dict) -> int:
    """What a minute of story costs at these prices, for its tokens in and out per minute."""
    return to_micros(token_price(pricing, tokens))


async def catalog(cfg: Settings, db: Database | None = None) -> dict:
    """Every writer the picker offers: local Ollama models (free) first, then the recommended
    OpenRouter models, then the rest; each with a price per minute of story."""
    default = writer_id(cfg)
    measured = db.writer_tokens_per_minute() if db else {}
    status: dict[str, dict[str, Any]] = {
        "ollama": {"ok": True, "error": None},
        "openrouter": {"ok": True, "error": None, "configured": False},
    }

    tags: list[dict] = []
    if not cfg.hosted_edition:  # which has no Ollama
        try:
            async with httpx.AsyncClient(transport=transport(cfg), timeout=5) as client:
                tags = (await client.get(f"{cfg.ollama.url}/api/tags")).json().get("models", [])
        except (httpx.HTTPError, ValueError) as e:
            status["ollama"] = {
                "ok": False,
                "error": f"Ollama isn't reachable at {cfg.ollama.url} ({e.__class__.__name__})",
            }
    rows = [
        Writer(
            id=f"ollama/{t['name']}",
            label=t["name"],
            provider="ollama",
            model=t["name"],
            local=True,
            usd_per_minute=0.0,
            basis="free",
            price_in=0.0,
            price_out=0.0,
        )
        for t in tags
        if "embed" not in t["name"]
    ]

    router = OpenRouterClient(cfg)
    status["openrouter"]["configured"] = bool(router.key)
    try:
        listed = await router.models()
    except (OpenRouterError, httpx.HTTPError) as e:
        listed = []
        status["openrouter"].update(ok=False, error=str(e))
    pinned = {m: i for i, m in enumerate(cfg.openrouter.recommended)}
    remote = []
    for m in listed:
        if ":" in m["id"]:  # :batch runs asynchronously; :free endpoints may keep prompts
            continue
        wid = f"openrouter/{m['id']}"
        pr = m.get("pricing") or {}
        tokens = measured.get(wid) or TRIAL_TOKENS_PER_MINUTE.get(wid) or TYPICAL_TOKENS_PER_MINUTE
        basis = "measured" if wid in measured else "trial" if wid in TRIAL_TOKENS_PER_MINUTE else "typical"
        r = m.get("reasoning") or {}
        efforts = [e for e in EFFORTS if e in (r.get("supported_efforts") or [])]
        remote.append(
            Writer(
                id=wid,
                label=m.get("name") or m["id"],
                provider="openrouter",
                model=m["id"],
                local=False,
                recommended=m["id"] in pinned,
                usd_per_minute=to_usd(per_minute_micros(pr, tokens)),
                basis=basis,
                efforts=[{"id": e, "name": EFFORT_NAMES[e]} for e in efforts] or None,
                default_effort=r.get("default_effort"),
                price_in=float(_price(pr, "prompt") * 1_000_000),
                price_out=float(_price(pr, "completion") * 1_000_000),
            )
        )
    remote.sort(key=lambda w: (not w.recommended, pinned.get(w.model, 0), w.label.lower()))
    rows += remote
    if not any(w.id == default for w in rows):
        # The default isn't listed (Ollama down, or a retired model): still show it, so the picker has it.
        provider, model = parse(default)
        rows.insert(
            0,
            Writer(
                id=default,
                label=model,
                provider=provider,
                model=model,
                local=provider == "ollama",
                unavailable=True,
            ),
        )
    return {"default": default, "models": [asdict(w) for w in rows], "providers": status}
