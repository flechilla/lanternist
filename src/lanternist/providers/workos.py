"""WorkOS AuthKit, which signs people in to the hosted edition: the address of its sign-in page, the
code exchange when it sends them back, and the address that ends its session on sign-out.

Plain httpx through `providers.transport()`, like fal and OpenRouter, so fake mode signs in against a
fake WorkOS with this same code (plans/ACCOUNTS_PLAN.md §1.4). The pages a browser is sent to are
AuthKit's, or in fake mode the stand-ins in auth.py, at the same paths under /api/auth/fake.
"""

import base64
import binascii
import json
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from ..config import Settings
from ..keys import platform_secret, redact
from . import ProviderError, transport

FAKE_CODE = "fake:"  # fake mode's sign-in page sends fake:<email>, which the fake WorkOS accepts
FAKE_PAGES = "/api/auth/fake"  # where fake mode's stand-ins for AuthKit's pages are


class WorkOSError(ProviderError):
    pass


@dataclass
class Identity:
    """Who WorkOS says signed in."""

    subject: str  # WorkOS's user id
    email: str | None
    session: str | None  # WorkOS's own session, which signing out ends too


def _session_of(access_token: str) -> str | None:
    """The `sid` claim of an access token. Read, not verified: the token came straight from WorkOS, over
    TLS, in answer to a request our API key signed."""
    try:
        payload = access_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("sid")
    except (IndexError, ValueError, binascii.Error):
        return None


class WorkOS:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.url = cfg.workos.api_url.rstrip("/")
        self.pages = FAKE_PAGES if cfg.fake_engines else f"{self.url}/user_management"
        self.client_id = cfg.workos.client_id
        self.key = platform_secret("workos", fake=cfg.fake_engines)
        if not self.key:
            raise WorkOSError("no WorkOS key: set WORKOS_API_KEY where `lanternist serve` runs")
        if not self.client_id and not cfg.fake_engines:
            raise WorkOSError("no WorkOS client id: set [workos] client_id in lanternist.toml")

    def sign_in_url(self, redirect_uri: str, state: str, sign_up: bool = False) -> str:
        """AuthKit's own page, which offers an email code and Google, and comes back with a code."""
        query = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "provider": "authkit",
            "state": state,
            "screen_hint": "sign-up" if sign_up else "sign-in",
        }
        return f"{self.pages}/authorize?{urlencode(query)}"

    def sign_out_url(self, session: str, return_to: str) -> str:
        """Where the browser goes to end WorkOS's session, which would otherwise sign the same person
        straight back in."""
        return f"{self.pages}/sessions/logout?{urlencode({'session_id': session, 'return_to': return_to})}"

    async def authenticate(self, code: str) -> Identity:
        """Exchange the code AuthKit sent back for who signed in."""
        body = {
            "client_id": self.client_id,
            "client_secret": self.key,
            "grant_type": "authorization_code",
            "code": code,
        }
        async with httpx.AsyncClient(transport=transport(self.cfg), timeout=15) as client:
            try:
                r = await client.post(f"{self.url}/user_management/authenticate", json=body)
            except httpx.HTTPError as e:
                raise WorkOSError(
                    f"WorkOS didn't answer ({e.__class__.__name__}): try signing in again"
                ) from None
        if r.status_code != 200:
            try:
                said = r.json().get("error_description") or r.json().get("message")
            except ValueError:
                said = None
            raise WorkOSError(
                redact(f"WorkOS refused the sign-in (HTTP {r.status_code}{f': {said}' if said else ''})"),
                status=r.status_code,
            )
        data = r.json()
        user = data["user"]
        return Identity(user["id"], user.get("email"), _session_of(data.get("access_token", "")))
