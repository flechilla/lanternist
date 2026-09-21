"""In-process fakes of fal.ai and OpenRouter, served through an httpx transport.

Fake mode (LANTERNIST_FAKE_ENGINES=1) and the tests use these, so the real clients run end to
end with no keys and no network. fal's queue walks IN_QUEUE -> IN_PROGRESS -> COMPLETED and its
results are ffmpeg test media; OpenRouter answers a JSON schema with a sample that fits it.
Tests steer failures through the attributes on FakeFal and FakeOpenRouter.
"""

import asyncio
import itertools
import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..engines import fake as media


def sample(schema: dict):
    """The simplest value that fits a JSON schema."""
    if "enum" in schema:
        return schema["enum"][0]
    for k in ("anyOf", "oneOf"):
        if k in schema:
            return sample(schema[k][0])
    t = schema.get("type")
    if isinstance(t, list):
        return sample({**schema, "type": t[0]})
    if t == "object":
        return {k: sample(v) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [sample(schema.get("items") or {}) for _ in range(max(schema.get("minItems", 1), 1))]
    return {"string": "text", "integer": 1, "number": 1.0, "boolean": False}.get(t)


def _json(data, status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


def _authorized(request: httpx.Request, scheme: str, bad: set[str]) -> bool:
    auth = request.headers.get("authorization", "")
    return auth.startswith(f"{scheme} ") and auth.split(" ", 1)[1] not in bad


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
    billable_units_on: str = "result"          # which response carries X-Fal-Billable-Units: result | status | none
    bad_keys: set[str] = field(default_factory=lambda: {"bad"})
    deprecated: set[str] = field(default_factory=set)
    prices: dict[str, tuple[str, str]] = field(default_factory=dict)   # endpoint -> (unit_price, unit)
    fail_submit: list[tuple[int, dict]] = field(default_factory=list)  # next submits answer these
    fail_result: dict[str, str] = field(default_factory=dict)          # endpoint -> error on completion
    requests: dict[str, FakeRequest] = field(default_factory=dict)
    submits: list[str] = field(default_factory=list)
    cancels: list[str] = field(default_factory=list)
    uploads: list[str] = field(default_factory=list)
    media: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    workdir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="lanternist-fakefal-")))
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    async def handle(self, request: httpx.Request) -> httpx.Response:
        host, path = urlparse(str(request.url)).hostname, request.url.path
        if host == "v3.fal.media" and request.method == "GET":
            body, ctype = self.media.get(str(request.url).split("?")[0], (b"", ""))
            return httpx.Response(200 if body else 404, content=body, headers={"content-type": ctype})
        if host in ("storage.googleapis.com",):
            return httpx.Response(200)
        if host == "v3.fal.media":
            return self._upload(request)
        if not _authorized(request, "Key", self.bad_keys):
            return _json({"detail": "Unauthorized"}, 401)
        if host == "queue.fal.run":
            return await self._queue(request, path.lstrip("/"))
        if host == "rest.fal.ai" and path.endswith("/storage/auth/token"):
            return _json({"token": "fake-token", "token_type": "Bearer", "base_url": "https://v3.fal.media",
                          "expires_at": "2099-01-01T00:00:00+00:00"})
        if host == "rest.fal.ai" and path.endswith("/storage/upload/initiate"):
            name = json.loads(request.content)["file_name"]
            return _json({"upload_url": f"https://storage.googleapis.com/fake/{name}",
                          "file_url": f"https://v3.fal.media/files/gcs/{name}"})
        if host == "api.fal.ai" and path == "/v1/models/pricing":
            return _json({"prices": [self._price(e) for e in request.url.params.get_list("endpoint_id")]})
        if host == "api.fal.ai" and path == "/v1/models":
            return _json({"models": [{"endpoint_id": e, "metadata": {
                "status": "deprecated" if e in self.deprecated else "active", "display_name": e}}
                for e in request.url.params.get_list("endpoint_id")], "has_more": False})
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
                        unit = {"output_second": "seconds", "megapixel": "megapixels", "image": "images",
                                "1k_chars": "1000 characters"}.get(e.price.unit, e.price.unit)
        return {"endpoint_id": endpoint, "unit_price": float(price), "unit": unit, "currency": "USD"}

    def _upload(self, request: httpx.Request) -> httpx.Response:
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return _json({"detail": "no storage token"}, 401)
        name = request.headers.get("x-fal-file-name", "file")
        url = f"https://v3.fal.media/files/uploaded/{next(self._ids)}-{name}"
        self.media[url] = (request.content, request.headers.get("content-type", ""))
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
            rid = f"req-{next(self._ids)}"
            self.requests[rid] = FakeRequest(rid, path, json.loads(request.content or b"{}"))
            self.submits.append(rid)
            return _json({"request_id": rid, "status_url": f"{base}/{path}/requests/{rid}/status",
                          "response_url": f"{base}/{path}/requests/{rid}",
                          "cancel_url": f"{base}/{path}/requests/{rid}/cancel", "queue_position": 0})
        _endpoint, rest = path.split("/requests/", 1)
        rid, _, action = rest.partition("/")
        req = self.requests.get(rid)
        if req is None:
            return _json({"detail": "request not found"}, 404)
        if action == "cancel":
            req.cancelled = True
            self.cancels.append(rid)
            return _json({"status": "CANCELLATION_REQUESTED"}, 202)
        if action == "status":
            req.polls += 1
            if req.polls == 1 and self.polls_before_done:
                return _json({"status": "IN_QUEUE", "queue_position": 0})
            if req.polls <= self.polls_before_done:
                return _json({"status": "IN_PROGRESS", "logs": []})
            if req.endpoint in self.fail_result:
                return _json({"status": "COMPLETED", "error": self.fail_result[req.endpoint],
                              "error_type": "content_policy_violation"})
            await self._make(req)
            headers = {"x-fal-billable-units": str(req.units)} if self.billable_units_on == "status" else None
            return _json({"status": "COMPLETED", "metrics": {"inference_time": 1.5}}, headers=headers)
        if action == "":
            if req.polls <= self.polls_before_done:
                return _json({"detail": "still in progress"}, 400)
            await self._make(req)
            headers = {"x-fal-billable-units": str(req.units)} if self.billable_units_on == "result" else None
            return _json(req.output, headers=headers)
        return _json({"detail": "unknown action"}, 404)

    async def _make(self, req: FakeRequest) -> None:
        """The request's output, as test media on the fake CDN, plus its billable units."""
        if req.output is not None:
            return
        a, ep = req.arguments, req.endpoint
        out = self.workdir / req.id
        if "clone-voice" in ep:
            url = self._store(f"{req.id}.safetensors", b"fake speaker embedding", "application/octet-stream")
            req.output, req.units = {"speaker_embedding": {"url": url}}, 0.5
        elif "image-to-video" in ep or "mmaudio" in ep:
            secs = _seconds(a.get("duration"), 5.0)
            path = out.with_suffix(".mp4")
            await media.video(int(secs * 24), 24, 320, 180, path)
            url = self._store(path.name, path.read_bytes(), "video/mp4")
            req.output, req.units = {"video": {"url": url, "content_type": "video/mp4"}}, secs
        elif any(k in ep for k in ("tts", "speech", "chatterbox")):
            text = a.get("text") or a.get("prompt") or ""
            path = out.with_suffix(".wav")
            await asyncio.to_thread(media.tts, {"id": req.id, "chunks": [text or "hello"], "out": str(path)})
            url = self._store(path.name, path.read_bytes(), "audio/wav")
            req.output, req.units = {"audio": {"url": url, "content_type": "audio/wav"}}, round(len(text) / 1000, 4)
        else:
            size = a.get("image_size")
            w, h = (size["width"], size["height"]) if isinstance(size, dict) else (512, 288)
            path = out.with_suffix(".png")
            await media.image({"id": req.id, "seed": a.get("seed") or 1, "width": w, "height": h, "out": str(path)})
            url = self._store(path.name, path.read_bytes(), "image/png")
            refs = len(a.get("image_urls") or [])
            units = round(w * h / 1e6 + refs, 4) if "klein" in ep else 1.0
            req.output = {"images": [{"url": url, "content_type": "image/png", "width": w, "height": h}],
                          "seed": a.get("seed")}
            req.units = units

    def _store(self, name: str, body: bytes, ctype: str) -> str:
        url = f"https://v3.fal.media/files/fake/{name}"
        self.media[url] = (body, ctype)
        return url


FAKE_STORY = ("TITLE: The Fake Lantern\n\n"
              + "\n\n".join(f"Paragraph {i} tells a small part of the story with enough words to read aloud."
                            for i in range(1, 5)))


@dataclass
class FakeOpenRouter:
    bad_keys: set[str] = field(default_factory=lambda: {"bad"})
    replies: list = field(default_factory=list)      # next answers: a string, or (status, error body)
    chats: list[dict] = field(default_factory=list)
    usage: float = 1.25
    limit: float | None = 10.0
    models: list[dict] = field(default_factory=lambda: [
        {"id": "fake/frontier", "name": "Fake Frontier", "context_length": 200000,
         "pricing": {"prompt": "0.000003", "completion": "0.000015"},
         "supported_parameters": ["structured_outputs", "response_format", "reasoning", "temperature"],
         "reasoning": {"mandatory": False}},
        {"id": "fake/cheap", "name": "Fake Cheap", "context_length": 128000,
         "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
         "supported_parameters": ["structured_outputs", "response_format", "temperature"]}])

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/models") and request.method == "GET":
            want = request.url.params.get("supported_parameters")
            return _json({"data": [m for m in self.models if not want or want in m["supported_parameters"]]})
        if not _authorized(request, "Bearer", self.bad_keys):
            return _json({"error": {"code": 401, "message": "No auth credentials found"}}, 401)
        if path.endswith("/key"):
            return _json({"data": {"label": "fake", "usage": self.usage, "limit": self.limit,
                                   "limit_remaining": None if self.limit is None else self.limit - self.usage,
                                   "is_free_tier": False}})
        if path.endswith("/chat/completions"):
            body = json.loads(request.content)
            self.chats.append(body)
            if self.replies:
                reply = self.replies.pop(0)
                if isinstance(reply, tuple):
                    return _json(reply[1], reply[0])
                text = reply
            elif fmt := body.get("response_format"):
                text = json.dumps(sample(fmt["json_schema"]["schema"]))
            else:
                text = FAKE_STORY
            prompt = sum(len(m.get("content") or "") for m in body["messages"]) // 4
            completion = max(len(text) // 4, 1)
            return _json({"id": f"gen-{len(self.chats)}", "model": body["model"], "provider": "FakeProvider",
                          "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                                    "total_tokens": prompt + completion,
                                    "cost": round(prompt * 3e-6 + completion * 15e-6, 8)}})
        return _json({"error": {"code": 404, "message": f"no route for {path}"}}, 404)


class FakeWorld:
    """Both fakes behind one transport, routed by host."""

    def __init__(self):
        self.fal = FakeFal()
        self.openrouter = FakeOpenRouter()

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "openrouter.ai":
            return await self.openrouter.handle(request)
        return await self.fal.handle(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)
