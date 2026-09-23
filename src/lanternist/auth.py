"""Who is asking. The local edition has one user, `local`, and no sign-in. The hosted edition signs
people in with WorkOS AuthKit (an email code or Google) and then knows them by a session of our own:
a random token in an HttpOnly cookie, its hash in the database (plans/ACCOUNTS_PLAN.md §1.4).

Routes take the user as `me: Me`, and pass `me.id` to every `Database` method that reads or changes
a row a user owns. In fake mode a test may name the user in a header instead, so tests can act as
two people; and signing in goes through a one-field page and a fake WorkOS.

Writes are safe from other sites twice over: the cookie is SameSite=Lax, and `foreign_write` refuses
a write whose Origin isn't the app's own.
"""

import hashlib
import hmac
import html
import json
import secrets
import time
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .config import Settings
from .db import LOCAL, Database, User
from .keys import platform_secret
from .providers.workos import FAKE_CODE, WorkOS, WorkOSError

FAKE_USER = "X-Lanternist-User"  # fake mode only: the name of the user a test acts as
SESSION = "lanternist_session"  # the cookie
STATE = "lanternist_state"  # the cookie that ties a callback to the sign-in that started it
SESSION_DAYS = 30
STATE_SECONDS = 600  # long enough to find an email code
WEBHOOK_TOLERANCE = 300  # seconds either way, against replayed webhooks

router = APIRouter()  # sign-in and its webhook: the hosted edition only


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _cookie(cfg: Settings, response: Response, name: str, value: str, seconds: int, path: str = "/") -> None:
    response.set_cookie(
        name,
        value,
        max_age=seconds,
        path=path,
        httponly=True,
        samesite="lax",
        secure=cfg.hosted.url.startswith("https://"),
    )


def current_user(request: Request) -> User:
    cfg: Settings = request.app.state.cfg
    db: Database = request.app.state.db
    if not cfg.hosted_edition:
        user = db.user(LOCAL)
        if user is None:  # only a library whose migration didn't run: the app migrates at start
            raise HTTPException(500, "the library has no local user: restart Lanternist to migrate it")
        return user
    if cfg.fake_engines and (name := request.headers.get(FAKE_USER)):
        return db.sign_in(f"fake:{name}", f"{name}@example.com")
    token = request.cookies.get(SESSION)
    if token and (user := db.session_user(_hash(token))):
        return user
    raise HTTPException(401, "sign in first")


Me = Annotated[User, Depends(current_user)]


def foreign_write(cfg: Settings, request: Request) -> bool:
    """A write to the API from a page that isn't ours. The webhooks come from WorkOS, with no cookie,
    and prove themselves by their signature instead."""
    return (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and request.url.path.startswith("/api/")
        and not request.url.path.startswith("/api/webhooks/")
        and request.headers.get("origin") != _origin(cfg.hosted.url)
    )


def _failed(why: str) -> RedirectResponse:
    """Back to the sign-in page, which says why."""
    return RedirectResponse(f"/sign-in?error={quote(why)}", status_code=303)


@router.get("/api/auth/sign-in")
def sign_in(request: Request, screen: str = "sign-in"):
    """To AuthKit's page (or, in fake mode, ours), with a state only this browser holds."""
    cfg: Settings = request.app.state.cfg
    state = secrets.token_urlsafe(24)
    if cfg.fake_engines:
        target = f"/api/auth/fake?state={state}"
    else:
        try:
            target = WorkOS(cfg).sign_in_url(
                f"{cfg.hosted.url.rstrip('/')}/api/auth/callback", state, sign_up=screen == "sign-up"
            )
        except WorkOSError as e:
            return _failed(str(e))
    response = RedirectResponse(target, status_code=303)
    _cookie(cfg, response, STATE, state, STATE_SECONDS, path="/api/auth")
    return response


@router.get("/api/auth/fake", response_class=HTMLResponse)
def fake_sign_in(request: Request, state: str):
    """Fake mode's stand-in for AuthKit's page: sign in as any email."""
    if not request.app.state.cfg.fake_engines:
        raise HTTPException(404)
    return f"""<!doctype html><meta name=viewport content="width=device-width">
<title>Sign in (test mode)</title>
<form action="/api/auth/callback" style="font:16px system-ui;max-width:24rem;margin:15vh auto;padding:0 16px">
<p><b>Test mode.</b> Sign in as anyone; no email is sent.</p>
<input type=hidden name=state value="{html.escape(state)}">
<label>Email <input name=code value="{FAKE_CODE}ann@example.com" style="width:100%;font:inherit"></label>
<p><button>Sign in</button></p></form>"""


@router.get("/api/auth/callback")
async def callback(request: Request, state: str = "", code: str = "", error_description: str = ""):
    """Where AuthKit sends people back: exchange the code, start a session, go to the app."""
    cfg: Settings = request.app.state.cfg
    db: Database = request.app.state.db
    expected = request.cookies.get(STATE)
    if not expected or not hmac.compare_digest(expected, state):
        return _failed("That sign-in link has expired or was opened in another browser. Sign in again.")
    if not code:
        return _failed(error_description or "The sign-in didn't finish. Sign in again.")
    try:
        who = await WorkOS(cfg).authenticate(code)
    except WorkOSError as e:
        return _failed(str(e))
    user = db.sign_in(who.subject, who.email)
    token = secrets.token_urlsafe(32)
    db.start_session(user.id, _hash(token), who.session, SESSION_DAYS)
    response = RedirectResponse("/", status_code=303)
    _cookie(cfg, response, SESSION, token, SESSION_DAYS * 86400)
    response.delete_cookie(STATE, path="/api/auth")
    return response


@router.post("/api/auth/sign-out")
def sign_out(request: Request, response: Response):
    """End the session, and say where to go to end WorkOS's too."""
    cfg: Settings = request.app.state.cfg
    token = request.cookies.get(SESSION)
    ended = request.app.state.db.end_session(_hash(token)) if token else None
    response.delete_cookie(SESSION, path="/")
    if ended and not cfg.fake_engines:
        return {"url": WorkOS(cfg).sign_out_url(ended, cfg.hosted.url)}
    return {"url": "/sign-in"}


def _signed(secret: str, header: str, body: bytes) -> bool:
    """Whether WorkOS signed this body: `t=<ms>, v1=<HMAC-SHA256 of "t.body">`, made recently."""
    parts = dict(p.strip().split("=", 1) for p in header.split(",") if "=" in p)
    stamp, given = parts.get("t", ""), parts.get("v1", "")
    if not stamp.isdigit() or abs(time.time() - int(stamp) / 1000) > WEBHOOK_TOLERANCE:
        return False
    wanted = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(wanted, given)


@router.post("/api/webhooks/workos")
async def workos_webhook(request: Request):
    """Changes WorkOS makes to an account or session between sign-ins. Each handler can run twice."""
    cfg: Settings = request.app.state.cfg
    db: Database = request.app.state.db
    secret = platform_secret("workos_webhook", fake=cfg.fake_engines)
    body = await request.body()
    if not secret or not _signed(secret, request.headers.get("workos-signature", ""), body):
        raise HTTPException(400, "not signed by WorkOS")
    event = json.loads(body)
    kind, data = event.get("event"), event.get("data") or {}
    if kind == "user.updated":
        db.user_updated(data["id"], data.get("email"))
    elif kind == "user.deleted":
        db.user_deleted(data["id"])
    elif kind == "session.revoked":
        db.revoke_session(data["id"])
    return {"ok": True}
