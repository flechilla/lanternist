"""fal.ai: the queue API for every media model, plus uploads, downloads, pricing and the catalog.

A request's life, as a `step_runs` row:

    submitted  POST queue.fal.run/<endpoint>; the row keeps request_id and the three URLs fal returns
    running    the status URL says IN_PROGRESS
    done       COMPLETED; the result is fetched at once (large results expire in about an hour)
    failed     fal said no, or a restart found the request too old to pick up again
    cancelled  the user cancelled; we sent PUT cancel_url

The row is written *before* polling starts, so a server restart polls the same request again
instead of paying for a new one. A shutdown leaves requests running at fal; only a user's cancel
cancels them.

Every request and upload carries an expiry: fal keeps media public and forever by default.
The API key goes only to fal's own API hosts, never to the CDN a result is downloaded from.
"""

import asyncio
import json
import logging
import mimetypes
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx

from ..config import Settings
from ..db import Database, now, to_micros
from ..keys import get_key, redact
from . import ProviderError, backoff, retry_after, transport

log = logging.getLogger(__name__)

RESUME_WINDOW = timedelta(minutes=50)  # results over 1 MB expire about an hour after completion
_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


class FalError(ProviderError):
    pass


@dataclass
class RunSpec:
    """Who a request is for and how to price it; becomes the request's `step_runs` row."""

    stage: str
    model_id: str
    story_id: str | None = None
    job_id: str | None = None
    scene: int | None = None
    step_key: str | None = None
    unit: str | None = None
    unit_price: Decimal | None = None  # USD per billable unit, to compute the cost
    estimate_micros: int | None = None
    user_cancelled: Callable[[], bool] = field(default=lambda: False)


@dataclass
class FalResult:
    data: dict
    request_id: str
    run_id: int
    billable_units: float | None
    cost_micros: int | None
    resumed: bool = False


def _error(r: httpx.Response, what: str) -> FalError:
    try:
        body = r.json()
    except ValueError:
        body = {"detail": r.text[:500]}
    detail = body.get("detail") if isinstance(body, dict) else body
    etype = r.headers.get("x-fal-error-type") or (body.get("error_type") if isinstance(body, dict) else None)
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        d = detail[0]
        where = ".".join(str(x) for x in d.get("loc", []) if x != "body")
        etype = etype or d.get("type")
        msg = f"{d.get('msg', 'invalid input')}" + (f" (field {where})" if where else "")
    else:
        msg = str(detail or body)[:500]
    retryable = r.status_code == 429 or r.status_code >= 500
    return FalError(
        redact(f"fal {what} failed with {r.status_code}{f' {etype}' if etype else ''}: {msg}"),
        status=r.status_code,
        type=etype,
        retryable=retryable,
        retry_after=retry_after(r),
    )


class Fal:
    def __init__(
        self,
        cfg: Settings,
        db: Database | None,
        key: str | None = None,
        transport_: httpx.AsyncBaseTransport | None = None,
    ):
        self.cfg, self.db = cfg, db  # db may be None for calls that log nothing (check, pricing)
        self.key = key or get_key("fal", fake=cfg.fake_engines).value
        if not self.key:
            raise FalError("no fal key: add one in Settings, or run `lanternist keys set fal`")
        self._transport = transport_ or transport(cfg)
        self._token: dict | None = None
        self.poll_start = 0.05 if cfg.fake_engines or transport_ else 1.0

    # plumbing ---------------------------------------------------------------------------------
    def client(self, timeout: float = 60) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport, timeout=httpx.Timeout(timeout, connect=15), follow_redirects=True
        )

    def _auth(self) -> dict:
        return {"Authorization": f"Key {self.key}"}

    def _lifecycle(self, hours: float) -> str:
        return json.dumps({"expiration_duration_seconds": int(hours * 3600)})

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if loop not in _semaphores:
            _semaphores[loop] = asyncio.Semaphore(self.cfg.fal.max_concurrency)
        return _semaphores[loop]

    async def _call(
        self, client: httpx.AsyncClient, method: str, url: str, what: str, tries: int = 5, **kw
    ) -> httpx.Response:
        """One API call, retried on rate limits, server errors and dropped connections."""
        for attempt in range(tries):
            try:
                r = await client.request(method, url, **kw)
            except httpx.TransportError as e:
                if attempt + 1 == tries:
                    raise FalError(f"fal {what} failed: {e.__class__.__name__}: {e}", retryable=True) from e
                await asyncio.sleep(backoff(attempt))
                continue
            if r.status_code < 400:
                return r
            err = _error(r, what)
            if not err.retryable or attempt + 1 == tries:
                raise err
            log.info("fal %s: %s; retrying", what, err)
            await asyncio.sleep(backoff(attempt, err.retry_after))
        raise AssertionError("unreachable")

    # the queue --------------------------------------------------------------------------------
    async def submit(
        self, client: httpx.AsyncClient, endpoint: str, arguments: dict, ttl_hours: float | None = None
    ) -> dict:
        headers = self._auth() | {
            "X-Fal-Object-Lifecycle-Preference": self._lifecycle(ttl_hours or self.cfg.fal.media_ttl_hours)
        }
        r = await self._call(
            client, "POST", f"{self.cfg.fal.queue_url}/{endpoint}", "submit", json=arguments, headers=headers
        )
        d = r.json()
        return {
            "request_id": d["request_id"],
            "status": d["status_url"],
            "response": d["response_url"],
            "cancel": d["cancel_url"],
        }

    async def poll(
        self,
        client: httpx.AsyncClient,
        urls: dict,
        run_id: int | None = None,
        on_status: Callable[[str, dict], None] | None = None,
        timeout: float = 3600,
    ) -> httpx.Response:
        """Wait for COMPLETED; returns the final status response."""
        deadline = time.monotonic() + timeout
        delay, running = self.poll_start, False
        while True:
            r = await self._call(client, "GET", urls["status"], "status check", headers=self._auth())
            d = r.json()
            status = d.get("status")
            if status == "COMPLETED":
                if d.get("error"):
                    raise FalError(
                        redact(f"fal request failed: {d.get('error_type') or 'error'}: {d['error']}"),
                        type=d.get("error_type"),
                    )
                return r
            if status == "IN_PROGRESS" and not running:
                running = True
                if run_id:
                    self.db.update_run(run_id, status="running")
            if on_status:
                on_status(status or "?", d)
            if time.monotonic() > deadline:
                raise FalError(f"fal request still {status} after {timeout / 60:.0f} minutes", type="timeout")
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 5.0 if self.poll_start >= 1 else 0.2)

    async def result(self, client: httpx.AsyncClient, urls: dict) -> httpx.Response:
        return await self._call(client, "GET", urls["response"], "result", headers=self._auth())

    async def cancel(self, client: httpx.AsyncClient, urls: dict) -> None:
        r = await client.put(urls["cancel"], headers=self._auth())
        if r.status_code not in (200, 202, 400, 404):  # 400: already completed; 404: gone
            log.warning("fal cancel returned %s: %s", r.status_code, r.text[:200])

    async def run(
        self,
        endpoint: str,
        arguments: dict,
        spec: RunSpec,
        on_status: Callable[[str, dict], None] | None = None,
        ttl_hours: float | None = None,
        timeout: float = 3600,
    ) -> FalResult:
        """Submit (or resume) one request, wait for it, fetch its result, and log it in step_runs."""
        async with self._semaphore(), self.client() as client:
            run_id, urls, request_id, resumed = await self._start(
                client, endpoint, arguments, spec, ttl_hours
            )
            t0 = time.monotonic()
            try:
                final = await self.poll(client, urls, run_id, on_status, timeout)
                r = await self.result(client, urls)
            except asyncio.CancelledError:
                if spec.user_cancelled():
                    await asyncio.shield(self._cancel_run(client, run_id, urls))
                raise  # a shutdown leaves the request running at fal, to be resumed
            except FalError as e:
                if e.type == "timeout":
                    await self._cancel_run(client, run_id, urls, status="failed", error=str(e))
                else:
                    self.db.update_run(
                        run_id,
                        status="failed",
                        error=str(e),
                        finished_at=now(),
                        wall_seconds=round(time.monotonic() - t0, 2),
                    )
                raise
            data = r.json()
            units = _billable_units(r) or _billable_units(final)
            cost = (
                to_micros(Decimal(str(units)) * spec.unit_price)
                if units is not None and spec.unit_price is not None
                else None
            )
            run = self.db.get_run(run_id)
            meta = dict(run.meta or {}) | {
                "billable_units_from": "result"
                if _billable_units(r) is not None
                else "status"
                if _billable_units(final) is not None
                else None,
                "inference_time": (final.json().get("metrics") or {}).get("inference_time"),
            }
            self.db.update_run(
                run_id,
                status="done",
                units=units,
                cost_micros=cost,
                cost_source="computed" if cost is not None else "none",
                wall_seconds=round(time.monotonic() - t0, 2),
                meta=meta,
                finished_at=now(),
            )
            return FalResult(data, request_id, run_id, units, cost, resumed)

    async def _start(self, client, endpoint, arguments, spec, ttl_hours) -> tuple[int, dict, str, bool]:
        if spec.step_key and (open_ := self.db.open_run(spec.step_key, "fal")):
            if open_.urls and now() - open_.created_at < RESUME_WINDOW:
                log.info("resuming fal request %s for step %s", open_.request_id, spec.step_key[:12])
                return open_.id, open_.urls, open_.request_id, True
            self.db.update_run(
                open_.id,
                status="failed",
                error="expired before a restart could pick it up",
                finished_at=now(),
            )
        sub = await self.submit(client, endpoint, arguments, ttl_hours)
        urls = {k: sub[k] for k in ("status", "response", "cancel")}
        run_id = self.db.start_run(
            story_id=spec.story_id,
            job_id=spec.job_id,
            scene=spec.scene,
            stage=spec.stage,
            step_key=spec.step_key,
            model_id=spec.model_id,
            provider="fal",
            status="submitted",
            request_id=sub["request_id"],
            urls=urls,
            unit=spec.unit,
            estimate_micros=spec.estimate_micros,
            meta={"endpoint": endpoint},
            started_at=now(),
        )
        return run_id, urls, sub["request_id"], False

    async def _cancel_run(
        self, client, run_id: int, urls: dict, status: str = "cancelled", error: str | None = None
    ) -> None:
        try:
            await self.cancel(client, urls)
        except httpx.HTTPError as e:
            log.warning("couldn't cancel the fal request: %s", e)
        self.db.update_run(run_id, status=status, error=error, finished_at=now())

    # files ------------------------------------------------------------------------------------
    async def _storage_token(self, client: httpx.AsyncClient) -> dict:
        if self._token and self._token["_until"] > time.time():
            return self._token
        r = await self._call(
            client,
            "POST",
            f"{self.cfg.fal.rest_url}/storage/auth/token",
            "upload token",
            params={"storage_type": "fal-cdn-v3"},
            json={},
            headers=self._auth(),
        )
        token = r.json()
        try:
            until = datetime.fromisoformat(str(token.get("expires_at"))).timestamp() - 60
        except ValueError:
            until = time.time() + 300
        self._token = token | {"_until": until}
        return self._token

    async def upload(self, path: Path, asset: str | None = None, ttl_hours: float | None = None) -> str:
        """Put a local file on fal's storage; returns its URL. Reused while it has 10+ minutes left."""
        asset = asset or path.name
        if url := self.db.upload_url("fal", asset):
            return url
        hours = ttl_hours or self.cfg.fal.media_ttl_hours
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        lifecycle = self._lifecycle(hours)
        data = path.read_bytes()
        async with self.client(timeout=300) as client:
            try:
                token = await self._storage_token(client)
                r = await self._call(
                    client,
                    "POST",
                    f"{token['base_url'].rstrip('/')}/files/upload",
                    "upload",
                    content=data,
                    headers={
                        "Authorization": f"{token['token_type']} {token['token']}",
                        "Content-Type": ctype,
                        "X-Fal-File-Name": path.name,
                        "X-Fal-Object-Lifecycle": lifecycle,
                        "X-Fal-Object-Lifecycle-Preference": lifecycle,
                    },
                )
                url = r.json()["access_url"]
            except (FalError, KeyError) as e:
                log.info("fal CDN upload failed (%s); trying the storage fallback", e)
                r = await self._call(
                    client,
                    "POST",
                    f"{self.cfg.fal.rest_url}/storage/upload/initiate",
                    "upload",
                    params={"storage_type": "gcs"},
                    headers=self._auth(),
                    json={"file_name": path.name, "content_type": ctype},
                )
                d = r.json()
                await self._call(
                    client, "PUT", d["upload_url"], "upload", content=data, headers={"Content-Type": ctype}
                )
                url = d["file_url"]
        self.db.save_upload("fal", asset, url, now() + timedelta(hours=hours))
        return url

    async def download(self, url: str, dest: Path) -> Path:
        """Fetch a result file. No API key: result URLs are public CDN links."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self.client(timeout=600) as client:
            for attempt in range(4):
                try:
                    async with client.stream("GET", url) as r:
                        if r.status_code >= 400:
                            raise FalError(
                                f"downloading a fal result failed with {r.status_code}",
                                status=r.status_code,
                                retryable=r.status_code >= 500,
                            )
                        with open(dest, "wb") as f:  # noqa: ASYNC230 - streamed chunk by chunk
                            async for chunk in r.aiter_bytes(1 << 20):
                                f.write(chunk)
                    return dest
                except (httpx.TransportError, FalError) as e:
                    if isinstance(e, FalError) and not e.retryable or attempt == 3:
                        raise
                    await asyncio.sleep(backoff(attempt))
        return dest

    # platform ---------------------------------------------------------------------------------
    async def pricing(self, endpoints: list[str]) -> dict[str, dict]:
        """Today's base price per endpoint: {endpoint: {unit_price, unit, currency}}.

        fal answers 404 for a whole batch when any endpoint in it has no price, so a failed batch
        is asked again one endpoint at a time and the unpriced ones are left out."""
        out: dict[str, dict] = {}

        async def ask(client, chunk: list[str]) -> None:
            r = await self._call(
                client,
                "GET",
                f"{self.cfg.fal.api_url}/v1/models/pricing",
                "pricing",
                params=[("endpoint_id", e) for e in chunk],
                headers=self._auth(),
            )
            for p in r.json().get("prices", []):
                out[p["endpoint_id"]] = p

        async with self.client() as client:
            for i in range(0, len(endpoints), 20):
                chunk = endpoints[i : i + 20]
                try:
                    await ask(client, chunk)
                except FalError as e:
                    if e.status != 404:
                        raise
                    for one in chunk if len(chunk) > 1 else []:
                        try:
                            await ask(client, [one])
                        except FalError as e1:
                            if e1.status != 404:
                                raise
        return out

    async def catalog(self, endpoints: list[str]) -> dict[str, dict]:
        """Catalog metadata per endpoint, including status: active or deprecated."""
        out: dict[str, dict] = {}
        async with self.client() as client:
            for i in range(0, len(endpoints), 20):
                chunk = endpoints[i : i + 20]
                r = await self._call(
                    client,
                    "GET",
                    f"{self.cfg.fal.api_url}/v1/models",
                    "catalog",
                    params=[("endpoint_id", e) for e in chunk],
                    headers=self._auth(),
                )
                for m in r.json().get("models", []):
                    out[m["endpoint_id"]] = m.get("metadata") or {}
        return out

    async def check(self) -> tuple[bool, str]:
        """Is the key accepted? One pricing lookup, which needs a valid key."""
        try:
            prices = await self.pricing(["fal-ai/flux-2/klein/9b"])
        except FalError as e:
            if e.status in (401, 403):
                return False, "fal rejected the key"
            return False, str(e)
        except httpx.HTTPError as e:
            return False, f"fal isn't reachable: {e.__class__.__name__}"
        return True, "key works" + (" (pricing API answers)" if prices else "")


def _billable_units(r: httpx.Response) -> float | None:
    try:
        return float(r.headers["x-fal-billable-units"])
    except (KeyError, ValueError):
        return None
