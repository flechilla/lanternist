"""OpenRouter: chat completions for the writer, the model list, and the key's usage and limit.

Structured output goes out as a strict JSON schema with `provider.require_parameters`, so the
request only routes to providers that honour the schema. Every response carries its cost in
`usage.cost`, which the writer records as the actual cost. `data_collection` from config keeps
prompts away from providers that store them.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings
from ..keys import get_key, redact
from . import ProviderError, backoff, retry_after, transport

log = logging.getLogger(__name__)

MODELS_TTL = 24 * 3600
_models_cache: dict[str, tuple[float, Any]] = {}  # public listings by URL, with the time fetched

FRIENDLY = {
    401: "OpenRouter rejected the key",
    402: "OpenRouter: out of credit or over the key's spending limit",
    403: "OpenRouter refused the request (moderation or a guardrail)",
    408: "OpenRouter timed out",
    429: "OpenRouter rate limit",
    502: "the model's provider is down or returned something invalid",
    503: "no provider can serve this request with the required parameters",
}


class OpenRouterError(ProviderError):
    pass


@dataclass
class ChatResult:
    text: str
    model: str
    cost_usd: float | None
    usage: dict = field(default_factory=dict)
    provider: str | None = None
    generation_id: str | None = None
    finish_reason: str | None = None


def _error(status: int, body: dict | None, fallback: str = "") -> OpenRouterError:
    err = (body or {}).get("error") or {}
    meta = err.get("metadata") or {}
    message = err.get("message") or fallback or "unknown error"
    head = FRIENDLY.get(status, f"OpenRouter error {status}")
    extra = []
    if meta.get("limit_source"):
        extra.append(f"limit: {meta['limit_source']}")
    if meta.get("reasons"):
        extra.append(f"reasons: {', '.join(map(str, meta['reasons']))}")
    retryable = status in (408, 429, 502, 503) or (
        status == 402 and meta.get("limit_source") == "openrouter_in_flight_budget"
    )
    text = f"{head}: {message}" + (f" ({'; '.join(extra)})" if extra else "")
    return OpenRouterError(
        redact(text),
        status=status,
        type=meta.get("error_type") or str(err.get("code", status)),
        retryable=retryable,
        meta=meta,
    )


class OpenRouter:
    def __init__(
        self, cfg: Settings, key: str | None = None, transport_: httpx.AsyncBaseTransport | None = None
    ):
        self.cfg = cfg
        self.key = key or get_key("openrouter", fake=cfg.fake_engines).value
        self._transport = transport_ or transport(cfg)

    def client(self, timeout: float = 600) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=httpx.Timeout(timeout, connect=15))

    def _headers(self, auth: bool = True) -> dict:
        h = {
            "HTTP-Referer": self.cfg.openrouter.referer,
            "X-OpenRouter-Title": self.cfg.openrouter.title,
            "X-Title": self.cfg.openrouter.title,
        }
        if auth:
            if not self.key:
                raise OpenRouterError(
                    "no OpenRouter key: add one in Settings, or run `lanternist keys set openrouter`"
                )
            h["Authorization"] = f"Bearer {self.key}"
        return h

    async def chat(
        self,
        model: str,
        messages: list[dict],
        *,
        schema: dict | None = None,
        schema_name: str = "answer",
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning: dict | None = None,
        tries: int = 3,
    ) -> ChatResult:
        body: dict = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens:
            body["max_tokens"] = max_tokens
        if reasoning is not None:
            body["reasoning"] = reasoning
        provider: dict = {"data_collection": self.cfg.openrouter.data_collection}
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
            provider["require_parameters"] = True
        body["provider"] = provider

        async with self.client() as client:
            for attempt in range(tries):
                try:
                    r = await client.post(
                        f"{self.cfg.openrouter.url}/chat/completions", json=body, headers=self._headers()
                    )
                except httpx.TransportError as e:
                    if attempt + 1 == tries:
                        raise OpenRouterError(
                            f"OpenRouter isn't reachable: {e.__class__.__name__}", retryable=True
                        ) from e
                    await asyncio.sleep(backoff(attempt))
                    continue
                try:
                    data = r.json()
                except ValueError:
                    data = None
                err = None
                if r.status_code >= 400:
                    err = _error(r.status_code, data, r.text[:300])
                    err.retry_after = retry_after(r)
                elif isinstance(data, dict) and data.get("error"):  # failed after the 200 went out
                    err = _error(int((data["error"] or {}).get("code") or 502), data)
                if err is None:
                    return self._result(model, data)
                if not err.retryable or attempt + 1 == tries:
                    raise err
                log.info("%s; retrying", err)
                await asyncio.sleep(backoff(attempt, err.retry_after))
        raise AssertionError("unreachable")

    def _result(self, model: str, data: dict) -> ChatResult:
        choice = (data.get("choices") or [{}])[0]
        if choice.get("error"):
            raise _error(int(choice["error"].get("code") or 502), {"error": choice["error"]})
        text = (choice.get("message") or {}).get("content") or ""
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}
        if not text.strip() and finish == "length":
            # Still paid for: `usage` in the error's meta says what it cost.
            reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            raise OpenRouterError(
                "the model used its whole token budget"
                + (f" on reasoning ({reasoning} tokens)" if reasoning else "")
                + " and wrote nothing; raise max_tokens",
                type="length",
                status=200,
                meta={"usage": usage},
            )
        return ChatResult(
            text=text,
            model=data.get("model") or model,
            cost_usd=usage.get("cost"),
            usage=usage,
            provider=data.get("provider"),
            generation_id=data.get("id"),
            finish_reason=finish,
        )

    async def key_info(self) -> dict:
        """Usage and limit of this key: {usage, limit, limit_remaining, is_free_tier, …}."""
        async with self.client(timeout=20) as client:
            r = await client.get(f"{self.cfg.openrouter.url}/key", headers=self._headers())
        if r.status_code >= 400:
            raise _error(r.status_code, _json(r), r.text[:300])
        return r.json().get("data") or {}

    async def models(self, structured_only: bool = True, refresh: bool = False) -> list[dict]:
        """The public model list (no key needed), cached for a day."""
        params = {"supported_parameters": "structured_outputs"} if structured_only else {}
        return await self._listing(f"{self.cfg.openrouter.url}/models", params, refresh) or []

    async def endpoints(self, model: str, refresh: bool = False) -> list[dict]:
        """The providers serving one model, each with the parameters it takes (no key needed; cached for a day).

        The model list's `supported_parameters` is the union over these, so a request that needs several
        parameters at once (a strict schema and a temperature) must check them here.
        """
        url = f"{self.cfg.openrouter.url}/models/{model}/endpoints"
        return ((await self._listing(url, {}, refresh)) or {}).get("endpoints") or []

    async def _listing(self, url: str, params: dict, refresh: bool) -> Any:
        """The `data` of a public GET, cached for a day: model details change rarely, and it's slow."""
        cache_key = f"{url}?{params}"
        hit = _models_cache.get(cache_key)
        if hit and not refresh and time.time() - hit[0] < MODELS_TTL:
            return hit[1]
        async with self.client(timeout=30) as client:
            r = await client.get(url, params=params, headers=self._headers(auth=False))
        if r.status_code >= 400:
            raise _error(r.status_code, _json(r), r.text[:300])
        data = r.json().get("data")
        _models_cache[cache_key] = (time.time(), data)
        return data

    async def check(self) -> tuple[bool, str, dict]:
        try:
            info = await self.key_info()
        except OpenRouterError as e:
            return False, str(e), {}
        except httpx.HTTPError as e:
            return False, f"OpenRouter isn't reachable: {e.__class__.__name__}", {}
        usage, limit = info.get("usage"), info.get("limit")
        detail = f"key works; used ${usage or 0:.2f}"
        detail += (
            f" of a ${limit:.2f} limit (${info.get('limit_remaining') or 0:.2f} left)"
            if limit
            else ", no limit set on the key"
        )
        return True, detail, info


def _json(r: httpx.Response) -> dict | None:
    try:
        return r.json()
    except ValueError:
        return None
