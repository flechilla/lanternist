"""In-process fakes of fal.ai, OpenRouter, Ollama, WorkOS and R2, served through an httpx transport.

Fake mode (LANTERNIST_FAKE_ENGINES=1) and the tests use these, so the real clients run end to
end with no keys and no network. fal's queue walks IN_QUEUE -> IN_PROGRESS -> COMPLETED and its
results are ffmpeg test media; OpenRouter and Ollama answer a JSON schema with a sample that fits
it (a storyboard gets one scene per numbered paragraph), and plain prompts with a short story.
Tests steer failures through the attributes on FakeFal and FakeOpenRouter. WorkOS signs in anyone
whose code is `fake:<email>`, which the fake sign-in page makes. R2 checks every signature, as the real
one does; the app serves it at FAKE_S3 so a browser can follow a presigned URL to it.

fal's requests and media, and R2's objects, live in files under the world's root (`<library>/fake/`
in fake mode), since the hosted edition runs `serve` and `worker` as two processes: the API serves a
file the worker stored, and a second worker polls the first one's request. The steering stays in
memory, in the process a test runs in.
"""

import asyncio
import base64
import hashlib
import hmac
import html
import json
import mimetypes
import os
import re
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlparse

import httpx

from ..engines import fake as media
from ..keys import platform_secret
from .s3 import FAKE_S3, UNSIGNED, Signer
from .workos import FAKE_CODE


def sample(schema: dict, lengths: dict[str, int] | None = None):
    """The simplest value that fits a JSON schema; `lengths` sizes the arrays of the named properties."""
    lengths = lengths or {}
    if "enum" in schema:
        return schema["enum"][0]
    for k in ("anyOf", "oneOf"):
        if k in schema:
            return sample(schema[k][0], lengths)
    t = schema.get("type")
    if isinstance(t, list):
        return sample({**schema, "type": t[0]}, lengths)
    if t == "object":
        out = {}
        for k, v in (schema.get("properties") or {}).items():
            if v.get("type") == "array" and k in lengths:
                out[k] = [sample(v.get("items") or {}, lengths) for _ in range(lengths[k])]
            else:
                out[k] = sample(v, lengths)
        return out
    if t == "array":
        return [sample(schema.get("items") or {}, lengths) for _ in range(max(schema.get("minItems", 1), 1))]
    return (
        {"string": "text", "integer": 1, "number": 1.0, "boolean": False}.get(t)
        if isinstance(t, str)
        else None
    )


def text_of(message: dict) -> str:
    """A chat message's words: its content, or the text parts of content that also holds pictures."""
    content = message.get("content") or ""
    return content if isinstance(content, str) else " ".join(p.get("text", "") for p in content)


def answer(messages: list[dict], schema: dict | None) -> str:
    """What the fake LLMs reply: a schema sample (one scene per '[n]' paragraph), else a short story."""
    if schema is None:
        return FAKE_STORY
    prompt = text_of(messages[-1]) if messages else ""
    paragraphs = len(re.findall(r"^\[\d+\]\s", prompt, flags=re.MULTILINE))
    return json.dumps(sample(schema, {"scenes": paragraphs} if paragraphs else None))


def _json(data, status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


def _authorized(request: httpx.Request, scheme: str, bad: set[str]) -> bool:
    auth = request.headers.get("authorization", "")
    return auth.startswith(f"{scheme} ") and auth.split(" ", 1)[1] not in bad


def _write(path: Path, body: bytes) -> None:
    """Write a file another process may be reading: all of it, or none of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    part.write_bytes(body)
    os.replace(part, path)


def _seconds(value, default: float = 5.0) -> float:
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(value)) if value is not None else None
    return float(m.group(1)) if m else default


@dataclass
class FakeRequest:
    id: str
    endpoint: str
    arguments: dict
    polls: int = 0
    cancelled: bool = False
    output: dict | None = None
    units: float | None = None


@dataclass
class FakeFal:
    polls_before_done: int = 2
    billable_units_on: str = "result"  # which response carries X-Fal-Billable-Units: result | status | none
    bad_keys: set[str] = field(default_factory=lambda: {"bad"})
    deprecated: set[str] = field(default_factory=set)
    prices: dict[str, tuple[str, str]] = field(default_factory=dict)  # endpoint -> (unit_price, unit)
    unpriced: set[str] = field(
        default_factory=set
    )  # asking for any of these 404s the whole batch, as fal does
    fail_submit: list[tuple[int, dict]] = field(default_factory=list)  # next submits answer these
    fail_result: dict[str, str] = field(default_factory=dict)  # endpoint -> error on completion
    # When set, a request for a finished result waits for it: a test cancels once fal has billed.
    result_gate: asyncio.Event | None = None
    result_asked: asyncio.Event = field(default_factory=asyncio.Event)
    # What this process sent, in order; the requests themselves are files, shared by every process.
    submits: list[str] = field(default_factory=list)
    cancels: list[str] = field(default_factory=list)
    uploads: list[str] = field(default_factory=list)
    root: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="lanternist-fakefal-")))

    @property
    def requests(self) -> dict[str, FakeRequest]:
        """Every request submitted on this root, by any process, as it is now."""
        found = sorted((self.root / "requests").glob("*.json"))
        return {p.stem: FakeRequest(**json.loads(p.read_text())) for p in found}

    def request(self, rid: str) -> FakeRequest | None:
        path = self.root / "requests" / f"{rid}.json"
        return FakeRequest(**json.loads(path.read_text())) if path.is_file() else None

    def save(self, req: FakeRequest) -> None:
        _write(self.root / "requests" / f"{req.id}.json", json.dumps(asdict(req)).encode())

    def medium(self, url: str) -> bytes | None:
        """What the fake CDN serves at `url`."""
        path = self.root / "media" / urlparse(url).path.lstrip("/")
        return path.read_bytes() if path.is_file() else None

    async def handle(self, request: httpx.Request) -> httpx.Response:
        host, path = urlparse(str(request.url)).hostname, request.url.path
        if host == "v3.fal.media" and request.method == "GET":
            body = self.medium(str(request.url))
            ctype = mimetypes.guess_type(request.url.path)[0] or "application/octet-stream"
            return httpx.Response(200 if body else 404, content=body or b"", headers={"content-type": ctype})
        if host == "storage.googleapis.com":
            return httpx.Response(200)
        if host == "v3.fal.media":
            return self._upload(request)
        if not _authorized(request, "Key", self.bad_keys):
            return _json({"detail": "Unauthorized"}, 401)
        if host == "queue.fal.run":
            return await self._queue(request, path.lstrip("/"))
        if host == "rest.fal.ai" and path.endswith("/storage/auth/token"):
            return _json(
                {
                    "token": "fake-token",
                    "token_type": "Bearer",
                    "base_url": "https://v3.fal.media",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                }
            )
        if host == "rest.fal.ai" and path.endswith("/storage/upload/initiate"):
            name = json.loads(request.content)["file_name"]
            return _json(
                {
                    "upload_url": f"https://storage.googleapis.com/fake/{name}",
                    "file_url": f"https://v3.fal.media/files/gcs/{name}",
                }
            )
        if host == "api.fal.ai" and path == "/v1/models/pricing":
            wanted = request.url.params.get_list("endpoint_id")
            if self.unpriced & set(wanted):
                return _json({"error": {"type": "not_found", "message": "Endpoint(s) not found"}}, 404)
            return _json({"prices": [self._price(e) for e in wanted]})
        if host == "api.fal.ai" and path == "/v1/models":
            return _json(
                {
                    "models": [
                        {
                            "endpoint_id": e,
                            "metadata": {
                                "status": "deprecated" if e in self.deprecated else "active",
                                "display_name": e,
                            },
                        }
                        for e in request.url.params.get_list("endpoint_id")
                    ],
                    "has_more": False,
                }
            )
        return _json({"detail": f"fake fal has no route for {request.method} {request.url}"}, 404)

    def _price(self, endpoint: str) -> dict:
        from .. import registry

        if endpoint in self.prices:
            price, unit = self.prices[endpoint]
        else:
            price, unit = "0.01", "units"
            for e in registry.load().values():
                for role, ep in e.all_endpoints().items():
                    if ep == endpoint and e.price.usd is not None:
                        price = str(e.price.tiers.get(role, e.price.usd) if role else e.price.usd)
                        unit = {
                            "output_second": "seconds",
                            "megapixel": "megapixels",
                            "image": "images",
                            "1k_chars": "1000 characters",
                        }.get(e.price.unit, e.price.unit)
        return {"endpoint_id": endpoint, "unit_price": float(price), "unit": unit, "currency": "USD"}

    def _upload(self, request: httpx.Request) -> httpx.Response:
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return _json({"detail": "no storage token"}, 401)
        name = request.headers.get("x-fal-file-name", "file")
        url = self._store(f"{uuid.uuid4().hex[:12]}-{name}", request.content, folder="uploaded")
        self.uploads.append(url)
        return _json({"access_url": url})

    async def _queue(self, request: httpx.Request, path: str) -> httpx.Response:
        base = "https://queue.fal.run"
        if "/requests/" not in path:
            if request.method != "POST":
                return _json({"detail": "method not allowed"}, 405)
            if self.fail_submit:
                status, body = self.fail_submit.pop(0)
                return _json(body, status, {"retry-after": "0"} if status == 429 else None)
            rid = f"req-{uuid.uuid4().hex[:12]}"
            self.save(FakeRequest(rid, path, json.loads(request.content or b"{}")))
            self.submits.append(rid)
            return _json(
                {
                    "request_id": rid,
                    "status_url": f"{base}/{path}/requests/{rid}/status",
                    "response_url": f"{base}/{path}/requests/{rid}",
                    "cancel_url": f"{base}/{path}/requests/{rid}/cancel",
                    "queue_position": 0,
                }
            )
        _endpoint, rest = path.split("/requests/", 1)
        rid, _, action = rest.partition("/")
        req = self.request(rid)
        if req is None:
            return _json({"detail": "request not found"}, 404)
        if action == "cancel":
            req.cancelled = True
            self.save(req)
            self.cancels.append(rid)
            return _json({"status": "CANCELLATION_REQUESTED"}, 202)
        if action == "status":
            req.polls += 1
            self.save(req)
            if req.polls == 1 and self.polls_before_done:
                return _json({"status": "IN_QUEUE", "queue_position": 0})
            if req.polls <= self.polls_before_done:
                return _json({"status": "IN_PROGRESS", "logs": []})
            if req.endpoint in self.fail_result:
                return _json(
                    {
                        "status": "COMPLETED",
                        "error": self.fail_result[req.endpoint],
                        "error_type": "content_policy_violation",
                    }
                )
            await self._make(req)
            headers = {"x-fal-billable-units": str(req.units)} if self.billable_units_on == "status" else None
            return _json({"status": "COMPLETED", "metrics": {"inference_time": 1.5}}, headers=headers)
        if action == "":
            if req.polls <= self.polls_before_done:
                return _json({"detail": "still in progress"}, 400)
            self.result_asked.set()
            if self.result_gate:
                await self.result_gate.wait()
            await self._make(req)
            headers = {"x-fal-billable-units": str(req.units)} if self.billable_units_on == "result" else None
            return _json(req.output, headers=headers)
        return _json({"detail": "unknown action"}, 404)

    async def _make(self, req: FakeRequest) -> None:
        """The request's output, as test media on the fake CDN, plus its billable units."""
        if req.output is not None:
            return
        a, ep = req.arguments, req.endpoint
        out = self.root / "work" / req.id
        out.parent.mkdir(parents=True, exist_ok=True)
        if "clone-voice" in ep:
            url = self._store(f"{req.id}.safetensors", b"fake speaker embedding")
            req.output, req.units = {"speaker_embedding": {"url": url}}, 0.5
        elif "image-to-video" in ep or "mmaudio" in ep:
            secs = _seconds(a.get("duration"), 5.0)
            path = out.with_suffix(".mp4")
            await media.video(int(secs * 24), 24, 320, 180, path)
            url = self._store(path.name, path.read_bytes())
            req.output, req.units = {"video": {"url": url, "content_type": "video/mp4"}}, secs
            if a.get("prompt_expansion_mode", "disabled") != "disabled":
                req.output["expanded_prompt"] = f"Shot: {a['prompt']}"
        elif any(k in ep for k in ("tts", "speech", "chatterbox")):
            text = a.get("text") or a.get("prompt") or ""
            path = out.with_suffix(".wav")
            await asyncio.to_thread(media.tts, {"id": req.id, "chunks": [text or "hello"], "out": str(path)})
            url = self._store(path.name, path.read_bytes())
            req.output, req.units = (
                {"audio": {"url": url, "content_type": "audio/wav"}},
                round(len(text) / 1000, 4),
            )
        else:
            size = a.get("image_size")
            w, h = (size["width"], size["height"]) if isinstance(size, dict) else (512, 288)
            path = out.with_suffix(".png")
            await media.image(
                {"id": req.id, "seed": a.get("seed") or 1, "width": w, "height": h, "out": str(path)}
            )
            url = self._store(path.name, path.read_bytes())
            refs = len(a.get("image_urls") or [])
            units = round(w * h / 1e6 + refs, 4) if "klein" in ep else 1.0
            req.output = {
                "images": [{"url": url, "content_type": "image/png", "width": w, "height": h}],
                "seed": a.get("seed"),
            }
            req.units = units
        self.save(req)

    def _store(self, name: str, body: bytes, folder: str = "fake") -> str:
        _write(self.root / "media" / "files" / folder / name, body)
        return f"https://v3.fal.media/files/{folder}/{name}"


FAKE_STORY = "TITLE: The Fake Lantern\n\n" + "\n\n".join(
    f"Paragraph {i} tells a small part of the story with enough words to read aloud." for i in range(1, 5)
)


@dataclass
class FakeOpenRouter:
    bad_keys: set[str] = field(default_factory=lambda: {"bad"})
    # Next answers: a string (the content), a dict (the whole 200 body), or (status, error body).
    replies: list = field(default_factory=list)
    chats: list[dict] = field(default_factory=list)
    usage: float = 1.25
    limit: float | None = 10.0
    endpoints_down: bool = False  # the per-model provider lists answer 503
    models: list[dict] = field(
        default_factory=lambda: [
            {
                "id": "fake/frontier",
                "name": "Fake Frontier",
                "context_length": 200000,
                "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                "supported_parameters": [
                    "structured_outputs",
                    "response_format",
                    "reasoning",
                    "temperature",
                    "max_tokens",
                ],
                "top_provider": {"max_completion_tokens": 128000},
                "reasoning": {
                    "mandatory": False,
                    "supported_efforts": ["max", "high", "medium", "low", "none"],
                    "default_effort": "medium",
                },
            },
            {
                "id": "fake/reasoner",
                "name": "Fake Reasoner",
                "context_length": 400000,
                "pricing": {"prompt": "0.000001", "completion": "0.000005"},
                "supported_parameters": ["structured_outputs", "response_format", "reasoning", "max_tokens"],
                "reasoning": {
                    "mandatory": True,
                    "supported_efforts": ["high", "medium", "low"],
                    "default_effort": "high",
                },
            },
            {
                "id": "fake/reasoner:batch",
                "name": "Fake Reasoner (batch)",
                "context_length": 400000,
                "pricing": {"prompt": "0.0000005", "completion": "0.0000025"},
                "supported_parameters": ["structured_outputs", "response_format", "reasoning"],
            },
            {
                "id": "fake/cheap",
                "name": "Fake Cheap",
                "context_length": 128000,
                "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
                "supported_parameters": ["structured_outputs", "response_format", "temperature"],
            },
        ]
    )

    def endpoints(self, model_id: str) -> list[list[str]] | None:
        """A model's providers, as the parameters each takes: its "endpoints" if given, else one taking all."""
        model = next((x for x in self.models if x["id"] == model_id), None)
        return None if model is None else model.get("endpoints") or [model["supported_parameters"]]

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if m := re.search(r"/models/(.+)/endpoints$", path):
            if self.endpoints_down:
                return _json({"error": {"code": 503, "message": "unavailable"}}, 503)
            params = self.endpoints(m.group(1))
            if params is None:
                return _json({"error": {"code": 404, "message": "model not found"}}, 404)
            return _json(
                {
                    "data": {
                        "id": m.group(1),
                        "endpoints": [
                            {"provider_name": f"Fake {i}", "supported_parameters": ps}
                            for i, ps in enumerate(params)
                        ],
                    }
                }
            )
        if path.endswith("/models") and request.method == "GET":
            want = request.url.params.get("supported_parameters")
            return _json({"data": [m for m in self.models if not want or want in m["supported_parameters"]]})
        if not _authorized(request, "Bearer", self.bad_keys):
            return _json({"error": {"code": 401, "message": "No auth credentials found"}}, 401)
        if path.endswith("/key"):
            return _json(
                {
                    "data": {
                        "label": "fake",
                        "usage": self.usage,
                        "limit": self.limit,
                        "limit_remaining": None if self.limit is None else self.limit - self.usage,
                        "is_free_tier": False,
                    }
                }
            )
        if path.endswith("/chat/completions"):
            body = json.loads(request.content)
            self.chats.append(body)
            if (body.get("provider") or {}).get("require_parameters"):
                # Like OpenRouter: one provider must take every parameter sent, or nothing serves it.
                sent = {p for p in ("temperature", "max_tokens", "reasoning") if p in body}
                sent |= {"structured_outputs"} if "response_format" in body else set()
                if not any(sent <= set(ps) for ps in self.endpoints(body["model"]) or []):
                    return _json(
                        {
                            "error": {
                                "code": 404,
                                "message": "No endpoints found that can handle the requested parameters.",
                            }
                        },
                        404,
                    )
            if self.replies:
                reply = self.replies.pop(0)
                if isinstance(reply, tuple):
                    return _json(reply[1], reply[0])
                if isinstance(reply, dict):
                    return _json(reply)
                text = reply
            else:
                fmt = body.get("response_format")
                text = answer(body["messages"], fmt["json_schema"]["schema"] if fmt else None)
            prompt = sum(len(text_of(m)) for m in body["messages"]) // 4
            completion = max(len(text) // 4, 1)
            return _json(
                {
                    "id": f"gen-{len(self.chats)}",
                    "model": body["model"],
                    "provider": "FakeProvider",
                    "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": prompt,
                        "completion_tokens": completion,
                        "total_tokens": prompt + completion,
                        "cost": round(prompt * 3e-6 + completion * 15e-6, 8),
                    },
                }
            )
        return _json({"error": {"code": 404, "message": f"no route for {path}"}}, 404)


@dataclass
class FakeOllama:
    models: list[str] = field(default_factory=lambda: ["qwen3.8:latest", "nomic-embed-text:latest"])
    chats: list[dict] = field(default_factory=list)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _json({"models": [{"name": m} for m in self.models]})
        body = json.loads(request.content)
        self.chats.append(body)
        text = answer(body["messages"], body.get("format"))
        return _json(
            {
                "model": body["model"],
                "message": {"role": "assistant", "content": text},
                "done": True,
                "prompt_eval_count": sum(len(text_of(m)) for m in body["messages"]) // 4,
                "eval_count": max(len(text) // 4, 1),
            }
        )


def fake_token(claims: dict) -> str:
    """An access token shaped like WorkOS's: a JWT with these claims, and no real signature."""

    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.signature"


@dataclass
class FakeWorkOS:
    authenticated: list[dict] = field(default_factory=list)  # every code exchange, as sent

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or request.url.path != "/user_management/authenticate":
            return _json({"message": "not found"}, 404)
        body = json.loads(request.content)
        self.authenticated.append(body)
        code = body.get("code", "")
        if body.get("grant_type") != "authorization_code" or not code.startswith(FAKE_CODE):
            return _json({"error": "invalid_grant", "error_description": "The code is invalid."}, 400)
        email = code.removeprefix(FAKE_CODE)
        user = {"object": "user", "id": f"user_{re.sub(r'[^a-z0-9]', '_', email.lower())}", "email": email}
        sid = f"session_{len(self.authenticated)}"
        return _json(
            {"user": user, "access_token": fake_token({"sid": sid}), "refresh_token": "fake-refresh"}
        )


def _s3_error(status: int, code: str, message: str) -> httpx.Response:
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Error><Code>{code}</Code><Message>{message}</Message></Error>'
    return httpx.Response(status, headers={"content-type": "application/xml"}, content=xml.encode())


def _when(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


@dataclass
class FakeS3:
    """R2's S3 API, path-style under FAKE_S3: objects in files under `root`, beside the headers each was
    stored with, with each signature, payload hash and expiry checked as R2 checks them, so a request
    signed wrong fails here too."""

    root: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="lanternist-fakes3-")))
    page: int = 1000  # keys per list page; a test makes it small to see the paging
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    fail: list[int] = field(default_factory=list)  # the next requests answer these statuses (0: as usual)
    undeletable: dict[str, str] = field(
        default_factory=dict
    )  # key -> the <Error> code a DeleteObjects keeps it with
    pace: float = 0.0  # seconds a GET of an object takes, so a test sees how many run at once
    most_at_once: int = 0  # the most GETs of objects that were running together
    _running: int = 0
    requests: list[str] = field(default_factory=list)  # "PUT <key>", in order, sent by this process

    def file(self, bucket: str, key: str) -> Path:
        return self.root / "objects" / bucket / key

    def meta(self, bucket: str, key: str) -> dict[str, str]:
        """The headers an object was stored with."""
        path = self.root / "meta" / bucket / f"{key}.json"
        return json.loads(path.read_text()) if path.is_file() else {}

    def keys(self, bucket: str, prefix: str = "") -> list[str]:
        base = self.root / "objects" / bucket
        found = (str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()) if base.is_dir() else ()
        return sorted(k for k in found if k.startswith(prefix) and not Path(k).name.startswith("."))

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.raw_path.decode().split("?", 1)[0])
        bucket, _, key = path.removeprefix(f"{FAKE_S3}/").partition("/")
        query = dict(parse_qsl(request.url.query.decode(), keep_blank_values=True))
        body = await request.aread()
        self.requests.append(f"{request.method} {key}")
        if refused := self._refused(request, path, query, body):
            return refused
        if self.fail and (status := self.fail.pop(0)):
            return _s3_error(status, "InternalError", "a fake failure")
        if not key:
            if request.method == "POST" and "delete" in query:
                errors = ""
                for gone in (html.unescape(k) for k in re.findall(r"<Key>(.*?)</Key>", body.decode())):
                    if code := self.undeletable.get(gone):
                        errors += f"<Error><Key>{html.escape(gone)}</Key><Code>{code}</Code></Error>"
                    else:
                        self.file(bucket, gone).unlink(missing_ok=True)
                return httpx.Response(200, content=f"<DeleteResult>{errors}</DeleteResult>".encode())
            return self._list(bucket, query)
        target = self.file(bucket, key)
        if request.method == "PUT":
            kept = {h: request.headers[h] for h in ("content-type", "cache-control") if h in request.headers}
            _write(self.root / "meta" / bucket / f"{key}.json", json.dumps(kept).encode())
            _write(target, body)
            return httpx.Response(200)
        if request.method == "DELETE":
            target.unlink(missing_ok=True)
            return httpx.Response(204)
        if not target.is_file():
            return _s3_error(404, "NoSuchKey", "The specified key does not exist.")
        self._running += 1
        self.most_at_once = max(self.most_at_once, self._running)
        await asyncio.sleep(self.pace)
        self._running -= 1
        data = target.read_bytes()
        headers = {"accept-ranges": "bytes", **self.meta(bucket, key)}
        for name in ("content-disposition", "content-type", "cache-control"):
            if f"response-{name}" in query:
                headers[name] = query[f"response-{name}"]
        status = 200
        if m := re.fullmatch(r"bytes=(\d+)-(\d*)", request.headers.get("range", "")):
            first, last = int(m[1]), min(int(m[2]) if m[2] else len(data) - 1, len(data) - 1)
            headers["content-range"] = f"bytes {first}-{last}/{len(data)}"
            data, status = data[first : last + 1], 206
        headers["content-length"] = str(len(data))
        return httpx.Response(status, headers=headers, content=b"" if request.method == "HEAD" else data)

    def _refused(
        self, request: httpx.Request, path: str, query: dict[str, str], body: bytes
    ) -> httpx.Response | None:
        """Why R2 would refuse the request's signature, or None when it's good."""
        key_id = platform_secret("r2_key_id", fake=True) or ""
        signer = Signer(key_id, platform_secret("r2", fake=True) or "")
        if "X-Amz-Signature" in query:  # a presigned URL
            given = query["X-Amz-Signature"]
            signed = {k: v for k, v in query.items() if k != "X-Amz-Signature"}
            credential, at = (
                signed.get("X-Amz-Credential", "").split("/")[0],
                _when(signed.get("X-Amz-Date", "")),
            )
            names, payload = signed.get("X-Amz-SignedHeaders", "").split(";"), UNSIGNED
            if at and self.now() > at + timedelta(seconds=int(signed.get("X-Amz-Expires", "0"))):
                return _s3_error(403, "AccessDenied", "Request has expired")
        else:
            m = re.fullmatch(
                r"AWS4-HMAC-SHA256 Credential=([^/]+)/[^,]+, SignedHeaders=([^,]+), Signature=(\w+)",
                request.headers.get("authorization", ""),
            )
            if not m:
                return _s3_error(403, "AccessDenied", "Access Denied")
            credential, names, given, signed = m[1], m[2].split(";"), m[3], query
            at, payload = (
                _when(request.headers.get("x-amz-date", "")),
                request.headers.get("x-amz-content-sha256", ""),
            )
        if credential != key_id:
            return _s3_error(403, "InvalidAccessKeyId", "The AWS Access Key Id you provided does not exist.")
        if at is None or any(n not in request.headers for n in names):
            return _s3_error(403, "AccessDenied", "Access Denied")
        headers = {n: request.headers[n] for n in names}
        want = signer.signature(request.method, quote(path, safe="/-_.~"), signed, headers, payload, at)
        if not hmac.compare_digest(want, given):
            return _s3_error(
                403, "SignatureDoesNotMatch", "The request signature we calculated does not match."
            )
        if payload != UNSIGNED and payload != hashlib.sha256(body).hexdigest():
            return _s3_error(
                400, "XAmzContentSHA256Mismatch", "The body does not match x-amz-content-sha256."
            )
        return None

    def _list(self, bucket: str, query: dict[str, str]) -> httpx.Response:
        after = query.get("continuation-token", "")
        keys = [k for k in self.keys(bucket, query.get("prefix", "")) if k > after]
        page, more = keys[: self.page], len(keys) > self.page
        contents = "".join(f"<Contents><Key>{html.escape(k, quote=False)}</Key></Contents>" for k in page)
        token = (
            f"<NextContinuationToken>{html.escape(page[-1], quote=False)}</NextContinuationToken>"
            if more
            else ""
        )
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult><Name>{bucket}</Name>'
            f"<KeyCount>{len(page)}</KeyCount><IsTruncated>{str(more).lower()}</IsTruncated>{token}{contents}"
            "</ListBucketResult>"
        )
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=xml.encode())


class FakeTransport(httpx.MockTransport):
    """The fakes' transport. A test can hold a client's close open (`FakeWorld.close_gate`), since
    closing awaits, and a cancel can land there."""

    def __init__(self, world: "FakeWorld"):
        super().__init__(world.handle)
        self.world = world

    async def aclose(self) -> None:
        if (gate := self.world.close_gate) is not None:
            self.world.closing.set()
            await gate.wait()


class FakeWorld:
    """The fakes behind one transport, routed by host and path, keeping their state under `root`: every
    world on the same root sees the same fal requests and R2 objects."""

    def __init__(self, root: Path | None = None):
        root = root or Path(tempfile.mkdtemp(prefix="lanternist-fakes-"))
        self.fal = FakeFal(root=root / "fal")
        self.openrouter = FakeOpenRouter()
        self.ollama = FakeOllama()
        self.workos = FakeWorkOS()
        self.s3 = FakeS3(root=root / "s3")
        self.close_gate: asyncio.Event | None = None
        self.closing = asyncio.Event()

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith(FAKE_S3):
            return await self.s3.handle(request)
        if request.url.host == "openrouter.ai":
            return await self.openrouter.handle(request)
        if request.url.host == "api.workos.com":
            return await self.workos.handle(request)
        if request.url.path in ("/api/chat", "/api/tags"):
            return await self.ollama.handle(request)
        return await self.fal.handle(request)

    def transport(self) -> httpx.MockTransport:
        return FakeTransport(self)
