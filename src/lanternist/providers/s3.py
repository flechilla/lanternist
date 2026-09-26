"""Cloudflare R2, through its S3 API: where the hosted edition keeps every file (plans/STORAGE_PLAN.md).

Plain httpx through `providers.transport()`, like fal, OpenRouter and WorkOS, so fake mode stores files
in a fake S3 with this same code (invariant 8). Requests are signed with AWS Signature Version 4, written
here rather than taken from botocore: its signer reads the clock itself, and an address that stays the
same for an hour must be signed at the top of the hour. AWS's published examples pin the signing.

    put, get, read, head, delete   one object
    keys, delete_prefix            everything under a prefix (ListObjectsV2, DeleteObjects)
    presign                        a GET the browser can use without our key

Keys are addressed path-style, <endpoint>/<bucket>/<key>, which R2 accepts and fake mode can serve.
"""

import asyncio
import base64
import hashlib
import hmac
import html
import logging
import re
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from ..config import Settings
from ..keys import platform_secret, redact
from . import ProviderError, backoff, retry_after, transport

log = logging.getLogger(__name__)

ALGORITHM = "AWS4-HMAC-SHA256"
UNSIGNED = "UNSIGNED-PAYLOAD"  # what a presigned URL signs in place of a body it can't know
EMPTY = hashlib.sha256(b"").hexdigest()
FAKE_S3 = "/api/fake/s3"  # fake mode's endpoint: the app serves the fake there, so a browser reaches it
KEYS = "set R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY where `lanternist serve` runs"
CHUNK = 1 << 20


class S3Error(ProviderError):
    pass


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def _enc(text: str, safe: str = "-_.~") -> str:
    """Percent-encoding as SigV4 wants it: everything but the unreserved characters (and `safe`)."""
    return quote(text, safe=safe)


def _stamp(at: datetime) -> str:
    return f"{at:%Y%m%dT%H%M%SZ}"


@dataclass(frozen=True)
class Signer:
    """AWS Signature Version 4, as S3 and R2 check it."""

    key_id: str
    secret: str
    region: str = "auto"  # R2's only region

    def scope(self, at: datetime) -> str:
        return f"{at:%Y%m%d}/{self.region}/s3/aws4_request"

    def signature(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        headers: dict[str, str],
        payload: str,
        at: datetime,
    ) -> str:
        """`path` as sent, percent-encoded; `headers` the signed ones, by lowercase name; `payload` the
        body's SHA-256, or UNSIGNED."""
        names = sorted(headers)
        canonical = "\n".join(
            [
                method,
                path,
                "&".join(f"{k}={v}" for k, v in sorted((_enc(k), _enc(v)) for k, v in query.items())),
                "".join(f"{n}:{' '.join(headers[n].split())}\n" for n in names),
                ";".join(names),
                payload,
            ]
        )
        text = "\n".join(
            [ALGORITHM, _stamp(at), self.scope(at), hashlib.sha256(canonical.encode()).hexdigest()]
        )
        key = _hmac(f"AWS4{self.secret}".encode(), f"{at:%Y%m%d}")
        for part in (self.region, "s3", "aws4_request"):
            key = _hmac(key, part)
        return hmac.new(key, text.encode(), hashlib.sha256).hexdigest()


def attachment(name: str) -> str:
    """A Content-Disposition that saves the file as `name`, UTF-8 included, with an ASCII fallback."""
    plain = re.sub(r'[^\x20-\x7e]|["\\]', "_", name)
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{_enc(name)}"


def _tags(xml: str, name: str) -> list[str]:
    """The text of every <name> element. R2's answers are small and flat, and these few fields are all
    we read of them."""
    return [html.unescape(v) for v in re.findall(rf"<{name}>(.*?)</{name}>", xml, flags=re.DOTALL)]


def _error(r: httpx.Response, what: str) -> S3Error:
    code = next(iter(_tags(r.text, "Code")), "")
    said = next(iter(_tags(r.text, "Message")), "")
    hint = f": check the R2 token, and that it may use this bucket ({KEYS})" if r.status_code == 403 else ""
    return S3Error(
        redact(
            f"R2 refused to {what} (HTTP {r.status_code}{f' {code}' if code else ''}{f': {said}' if said else ''}){hint}"
        ),
        status=r.status_code,
        type=code or None,
        retryable=r.status_code == 429 or r.status_code >= 500,
        retry_after=retry_after(r),
    )


class S3:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        fake = cfg.fake_engines
        endpoint = f"{cfg.hosted.url.rstrip('/')}{FAKE_S3}" if fake else cfg.storage.endpoint.rstrip("/")
        self.bucket = cfg.storage.bucket or ("lanternist-fake" if fake else "")
        if not endpoint or not self.bucket:
            raise S3Error(
                "no R2 bucket: set [storage] endpoint (https://<account id>.r2.cloudflarestorage.com) "
                "and bucket in lanternist.toml"
            )
        key_id, secret = platform_secret("r2_key_id", fake=fake), platform_secret("r2", fake=fake)
        if not key_id or not secret:
            raise S3Error(f"no R2 keys: {KEYS}")
        self.signer = Signer(key_id, secret)
        parts = urlsplit(endpoint)
        self.origin, self.host = f"{parts.scheme}://{parts.netloc}", parts.netloc
        self.root = f"{parts.path}/{self.bucket}"

    # plumbing ---------------------------------------------------------------------------------
    def client(self, timeout: float = 120) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport(self.cfg), timeout=httpx.Timeout(timeout, connect=15))

    def path(self, key: str) -> str:
        """The URL path of an object, as sent and as signed; the bucket's own for an empty key."""
        return f"{self.root}/{_enc(key, safe='/-_.~')}" if key else self.root

    def _url(self, path: str, query: dict[str, str]) -> str:
        qs = "&".join(f"{_enc(k)}={_enc(v)}" for k, v in query.items())
        return f"{self.origin}{path}{f'?{qs}' if qs else ''}"

    def _signed(
        self, method: str, path: str, query: dict[str, str], headers: dict[str, str], payload: str
    ) -> dict[str, str]:
        at = datetime.now(UTC)
        signed = {"host": self.host, "x-amz-content-sha256": payload, "x-amz-date": _stamp(at)}
        signed |= {k.lower(): v for k, v in headers.items()}
        sig = self.signer.signature(method, path, query, signed, payload, at)
        auth = (
            f"{ALGORITHM} Credential={self.signer.key_id}/{self.signer.scope(at)}, "
            f"SignedHeaders={';'.join(sorted(signed))}, Signature={sig}"
        )
        return {k: v for k, v in signed.items() if k != "host"} | {"authorization": auth}

    async def _call(
        self,
        client: httpx.AsyncClient,
        method: str,
        key: str,
        what: str,
        query: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        stream: Callable[[], AsyncIterator[bytes]] | None = None,
        payload: str | None = None,
        tries: int = 5,
    ) -> httpx.Response:
        """One request, signed afresh for each try and retried on rate limits, server errors and dropped
        connections. A body is `body`, or `stream()` with its SHA-256 as `payload`. A 404 comes back as
        it is, for the caller to read as "no such object"."""
        path, query = self.path(key), query or {}
        digest = payload or hashlib.sha256(body).hexdigest()
        for attempt in range(tries):
            sent = self._signed(method, path, query, headers or {}, digest)
            try:
                r = await client.request(
                    method, self._url(path, query), headers=sent, content=stream() if stream else body
                )
            except httpx.TransportError as e:
                if attempt + 1 == tries:
                    raise S3Error(
                        f"R2 didn't answer ({e.__class__.__name__}) to {what}", retryable=True
                    ) from e
                await asyncio.sleep(backoff(attempt))
                continue
            if r.status_code < 400 or r.status_code == 404:
                return r
            err = _error(r, what)
            if not err.retryable or attempt + 1 == tries:
                raise err
            log.info("R2 %s: %s; retrying", what, err)
            await asyncio.sleep(backoff(attempt, err.retry_after))
        raise AssertionError("unreachable")

    # one object -------------------------------------------------------------------------------
    async def put(self, key: str, src: Path, sha256: str, content_type: str, cache_control: str) -> None:
        """Upload a file, streamed. `sha256` is its content's, which R2 checks the body against."""
        size = src.stat().st_size
        headers = {"content-type": content_type, "cache-control": cache_control, "content-length": str(size)}

        async def body() -> AsyncIterator[bytes]:
            with open(src, "rb") as f:  # noqa: ASYNC230 - read chunk by chunk as the upload goes
                while chunk := f.read(CHUNK):
                    yield chunk

        async with self.client(timeout=600) as client:
            r = await self._call(
                client, "PUT", key, f"store {key}", headers=headers, stream=body, payload=sha256
            )
        if r.status_code == 404:
            raise self._no_bucket()

    def _no_bucket(self) -> S3Error:
        return S3Error(f"R2 has no bucket {self.bucket}: create it, or fix [storage] bucket", status=404)

    async def get(self, key: str, dest: Path) -> bool:
        """Download an object to `dest`, whole or not at all; False when there's no such object."""
        path = self.path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # A name of its own: two jobs may fetch the same file at once, and each replaces it whole.
        part = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.part")
        try:
            async with self.client(timeout=600) as client:
                for attempt in range(5):
                    sent = self._signed("GET", path, {}, {}, EMPTY)
                    try:
                        async with client.stream("GET", self._url(path, {}), headers=sent) as r:
                            if r.status_code == 404:
                                return False
                            if r.status_code >= 400:
                                await r.aread()
                                err = _error(r, f"fetch {key}")
                                if not err.retryable or attempt == 4:
                                    raise err
                                await asyncio.sleep(backoff(attempt, err.retry_after))
                                continue
                            with open(part, "wb") as f:  # noqa: ASYNC230 - written chunk by chunk as it arrives
                                async for chunk in r.aiter_bytes(CHUNK):
                                    f.write(chunk)
                        part.replace(dest)
                        return True
                    except httpx.TransportError as e:
                        if attempt == 4:
                            raise S3Error(
                                f"R2 didn't answer ({e.__class__.__name__}) to fetching {key}", retryable=True
                            ) from e
                        await asyncio.sleep(backoff(attempt))
        finally:
            part.unlink(missing_ok=True)  # after a failure; a finished download has taken its place
        raise AssertionError("unreachable")

    async def read(self, key: str) -> bytes | None:
        """A small object's bytes, such as subtitles; None when there's no such object."""
        async with self.client() as client:
            r = await self._call(client, "GET", key, f"fetch {key}")
        return None if r.status_code == 404 else r.content

    async def head(self, key: str) -> int | None:
        """An object's size, or None when there's no such object."""
        async with self.client() as client:
            r = await self._call(client, "HEAD", key, f"look for {key}")
        return None if r.status_code == 404 else int(r.headers.get("content-length", 0))

    async def delete(self, key: str) -> None:
        async with self.client() as client:
            await self._call(client, "DELETE", key, f"delete {key}")

    # a prefix ---------------------------------------------------------------------------------
    async def keys(self, prefix: str) -> list[str]:
        """Every key under `prefix`, a page of up to 1,000 at a time."""
        found: list[str] = []
        query = {"list-type": "2", "prefix": prefix}
        async with self.client() as client:
            while True:
                r = await self._call(client, "GET", "", f"list {prefix}", query=query)
                if r.status_code == 404:
                    raise self._no_bucket()
                found += _tags(r.text, "Key")
                token = next(iter(_tags(r.text, "NextContinuationToken")), None)
                if "<IsTruncated>true</IsTruncated>" not in r.text or not token:
                    return found
                query = {**query, "continuation-token": token}

    async def delete_prefix(self, prefix: str) -> int:
        """Delete everything under `prefix`, 1,000 keys a request; how many there were."""
        keys = await self.keys(prefix)
        async with self.client() as client:
            for i in range(0, len(keys), 1000):
                objects = "".join(
                    f"<Object><Key>{html.escape(k, quote=False)}</Key></Object>" for k in keys[i : i + 1000]
                )
                body = f"<Delete><Quiet>true</Quiet>{objects}</Delete>".encode()
                md5 = base64.b64encode(hashlib.md5(body).digest()).decode()  # noqa: S324 - S3 asks for it; not for security
                r = await self._call(
                    client,
                    "POST",
                    "",
                    f"delete under {prefix}",
                    query={"delete": ""},
                    headers={"content-md5": md5},
                    body=body,
                )
                # A 200 can still name keys it kept, one <Error> each.
                if kept := _tags(r.text, "Error"):
                    key, code = _tags(kept[0], "Key")[0], _tags(kept[0], "Code")[0]
                    raise S3Error(
                        f"R2 kept {len(kept)} of the files under {prefix} ({key}: {code}): delete them again",
                        type=code,
                    )
        return len(keys)

    # for the browser --------------------------------------------------------------------------
    def presign(self, key: str, at: datetime, seconds: int, disposition: str | None = None) -> str:
        """A GET of `key` that works from `at` for `seconds`, with no key: what the browser is sent to.
        Signed at a time the caller picks, so the same hour gives the same address."""
        path = self.path(key)
        query = {
            "X-Amz-Algorithm": ALGORITHM,
            "X-Amz-Credential": f"{self.signer.key_id}/{self.signer.scope(at)}",
            "X-Amz-Date": _stamp(at),
            "X-Amz-Expires": str(seconds),
            "X-Amz-SignedHeaders": "host",
        }
        if disposition:
            query["response-content-disposition"] = disposition
        query["X-Amz-Signature"] = self.signer.signature(
            "GET", path, query, {"host": self.host}, UNSIGNED, at
        )
        return self._url(path, query)
