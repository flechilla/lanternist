"""Accounts in the hosted edition: each person sees, changes and pays for only their own."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi.routing import APIRoute
from test_api import storyboard

from lanternist import keys, providers
from lanternist.auth import FAKE_USER, SESSION
from lanternist.config import Settings
from lanternist.db import LOCAL
from lanternist.providers.workos import WorkOS

BOB = {FAKE_USER: "bob"}
IDS = ("{story_id}", "{job_id}", "{asset}")
GONE = "event: gone\ndata: {}\n\n"  # what the progress stream says of a job that isn't there

# How to call each route that takes an id, as someone who doesn't own it.
CALLS: dict[tuple[str, str], dict] = {
    ("GET", "/api/stories/{story_id}"): {},
    ("PUT", "/api/stories/{story_id}"): {"json": {"storyboard": storyboard(), "base_version": 1}},
    ("DELETE", "/api/stories/{story_id}"): {},
    ("GET", "/api/stories/{story_id}/estimate"): {},
    ("PUT", "/api/stories/{story_id}/budget"): {"json": {"usd": 100}},
    ("POST", "/api/stories/{story_id}/scenes/{n}/rewrite"): {"json": {"instruction": "shorter"}},
    ("POST", "/api/stories/{story_id}/scenes/{n}/reroll"): {},
    ("POST", "/api/stories/{story_id}/scenes/{n}/retake"): {},
    ("POST", "/api/stories/{story_id}/cast/reroll"): {},
    ("POST", "/api/stories/{story_id}/{kind}"): {},
    ("GET", "/api/jobs/{job_id}"): {},
    ("POST", "/api/jobs/{job_id}/cancel"): {},
    ("GET", "/api/jobs/{job_id}/events"): {},
    ("GET", "/api/assets/{asset}"): {},
}


def test_another_users_ids_answer_404(hosted_client, wait):
    c = hosted_client
    sid = c.post("/api/stories", json={"storyboard": storyboard()}).json()["story"]["id"]
    job = wait(c.post(f"/api/stories/{sid}/render").json()["id"])
    ids = {"story_id": sid, "job_id": job["id"], "asset": job["result"]["film"], "n": 2, "kind": "board"}

    routes = {
        (method, r.path)
        for r in c.app.routes
        if isinstance(r, APIRoute) and any(i in r.path for i in IDS)
        for method in r.methods
    }
    assert routes == set(CALLS), "a route that takes an id needs its line in CALLS"
    for (method, path), kwargs in CALLS.items():
        r = c.request(method, path.format(**ids), headers=BOB, **kwargs)
        if path.endswith("/events"):
            assert r.text == GONE
        else:
            assert r.status_code == 404, (method, path, r.text)

    story = c.get(f"/api/stories/{sid}").json()  # ann's story is as she left it
    assert story["version"] == 1 and story["budget"]["default"]
    assert c.get(f"/api/jobs/{job['id']}").json()["status"] == "done"


def test_two_users_see_only_their_own(hosted_client, wait):
    c = hosted_client
    ann = c.post("/api/stories", json={"storyboard": storyboard()}).json()["story"]["id"]
    wait(c.post(f"/api/stories/{ann}/board").json()["id"])
    brief = {"idea": "a fox who can't sleep", "writer": "openrouter/fake/frontier"}
    written = c.post("/api/stories", json={"brief": brief}, headers=BOB).json()
    wait(written["job"]["id"], headers=BOB)  # bob's writer runs as bob
    bob = written["story"]["id"]

    assert [s["id"] for s in c.get("/api/stories").json()] == [ann]
    assert [s["id"] for s in c.get("/api/stories", headers=BOB).json()] == [bob]
    assert {j["story_id"] for j in c.get("/api/jobs").json()} == {ann}
    assert {j["story_id"] for j in c.get("/api/jobs", headers=BOB).json()} == {bob}

    c.put("/api/settings", json={"changes": {"defaults.image": "fal/nano-banana-2"}})
    image = {r["key"]: r["value"] for r in c.get("/api/settings", headers=BOB).json()}["defaults.image"]
    assert image == "fal/flux-2-klein-9b"  # bob keeps the default

    assert c.get("/api/stories", headers={FAKE_USER: ""}).status_code == 401  # no one signed in


def test_each_user_pays_for_their_own_cache(hosted_client, wait):
    c = hosted_client
    ann = c.post("/api/stories", json={"storyboard": storyboard()}).json()["story"]["id"]
    first = wait(c.post(f"/api/stories/{ann}/board").json()["id"])
    bob = c.post("/api/stories", json={"storyboard": storyboard()}, headers=BOB).json()["story"]["id"]
    second = wait(c.post(f"/api/stories/{bob}/board", headers=BOB).json()["id"], headers=BOB)

    # The same pictures, made again for bob and paid for by him, in his own folder.
    for job in (first, second):
        assert all(s["keyframes"]["state"] == "done" for s in job["progress"]["scenes"].values())
        assert job["progress"]["spent_usd"] > 0
    lib = c.app.state.cfg.library
    assert len(list((lib / "u").iterdir())) == 2


# ------------------------------------------------------------------------------------ sign-in
def signed_out(c):
    """The hosted client as a browser: no test header, only what its cookies say."""
    c.headers.pop(FAKE_USER)
    return c


def sign_in(c, email: str = "ann@example.com") -> None:
    to_page = c.get("/api/auth/sign-in", follow_redirects=False)
    state = parse_qs(urlsplit(to_page.headers["location"]).query)["state"][0]
    assert "Test mode" in c.get(to_page.headers["location"]).text
    back = c.get(
        "/api/auth/callback", params={"state": state, "code": f"fake:{email}"}, follow_redirects=False
    )
    assert back.status_code == 303 and back.headers["location"] == "/"


def test_signing_in_starts_a_session_that_the_progress_stream_uses(hosted_client):
    c = signed_out(hosted_client)
    assert c.get("/api/me").status_code == 401
    to_page = c.get("/api/auth/sign-in", follow_redirects=False)
    assert "HttpOnly" in to_page.headers["set-cookie"] and "Path=/api/auth" in to_page.headers["set-cookie"]
    sign_in(c)
    cookie = next(k for k in c.cookies.jar if k.name == SESSION)
    assert cookie.has_nonstandard_attr("HttpOnly") and not cookie.secure  # http://testserver
    assert c.get("/api/me").json()["email"] == "ann@example.com"
    sent = providers.fake_world().workos.authenticated[-1]
    assert sent == {
        "client_id": "",
        "client_secret": "fake-workos-secret",
        "grant_type": "authorization_code",
        "code": "fake:ann@example.com",
    }

    sid = c.post("/api/stories", json={"storyboard": storyboard(1)}).json()["story"]["id"]
    job = c.post(f"/api/stories/{sid}/cast").json()
    with c.stream("GET", f"/api/jobs/{job['id']}/events") as r:
        assert '"status": "done"' in r.read().decode()

    assert c.post("/api/auth/sign-out").json() == {"url": "/sign-in"}
    assert c.get("/api/me").status_code == 401


def test_a_callback_this_browser_didnt_start_is_refused(hosted_client):
    c = signed_out(hosted_client)
    c.get("/api/auth/sign-in", follow_redirects=False)
    r = c.get(
        "/api/auth/callback",
        params={"state": "forged", "code": "fake:eve@example.com"},
        follow_redirects=False,
    )
    assert r.headers["location"].startswith("/sign-in?error=That%20sign-in%20link%20has%20expired")
    assert SESSION not in c.cookies and c.get("/api/me").status_code == 401


def test_a_code_workos_refuses_says_so(hosted_client):
    c = signed_out(hosted_client)
    to_page = c.get("/api/auth/sign-in", follow_redirects=False)
    state = parse_qs(urlsplit(to_page.headers["location"]).query)["state"][0]
    r = c.get("/api/auth/callback", params={"state": state, "code": "stolen"}, follow_redirects=False)
    assert unquote(r.headers["location"]) == (
        "/sign-in?error=WorkOS refused the sign-in (HTTP 400: The code is invalid.)"
    )


def test_a_write_from_another_site_is_refused(hosted_client):
    c = hosted_client
    story = {"storyboard": storyboard(1)}
    assert c.post("/api/stories", json=story, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/stories", json=story, headers={"Origin": ""}).status_code == 403
    assert (
        c.get("/api/stories", headers={"Origin": "https://evil.example"}).status_code == 200
    )  # reads are fine
    assert c.post("/api/stories", json=story).status_code == 201


def test_sessions_end_when_they_expire_or_the_account_goes(db):
    ann = db.sign_in("user_ann", "ann@example.com")
    db.start_session(ann.id, "live", None, days=30)
    db.start_session(ann.id, "old", None, days=-1)
    assert db.session_user("live").id == ann.id and db.session_user("old") is None
    db.user_deleted("user_ann")
    assert db.session_user("live") is None and db.user(ann.id).deleted_at is not None


WEBHOOK_SECRET = "whsec_test_0123456789"


def webhook(c, event: dict, at: float | None = None, secret: str = WEBHOOK_SECRET):
    body = json.dumps(event).encode()
    stamp = str(int((at or time.time()) * 1000))
    sig = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    headers = {"WorkOS-Signature": f"t={stamp}, v1={sig}", "Origin": "", "Content-Type": "application/json"}
    return c.post("/api/webhooks/workos", content=body, headers=headers)


def test_workos_webhooks_count_only_when_signed(hosted_client, monkeypatch):
    monkeypatch.setenv("WORKOS_WEBHOOK_SECRET", WEBHOOK_SECRET)
    c = signed_out(hosted_client)
    sign_in(c)
    user_id = "user_ann_example_com"  # the fake WorkOS's id for ann@example.com
    renamed = {"event": "user.updated", "data": {"id": user_id, "email": "ann@new.example.com"}}

    assert webhook(c, renamed, secret="not-the-secret").status_code == 400
    assert webhook(c, renamed, at=time.time() - 3600).status_code == 400  # replayed an hour later
    assert webhook(c, renamed).status_code == 200
    assert c.get("/api/me").json()["email"] == "ann@new.example.com"

    assert webhook(c, {"event": "session.revoked", "data": {"id": "session_1"}}).status_code == 200
    assert c.get("/api/me").status_code == 401
    sign_in(c)
    assert webhook(c, {"event": "user.deleted", "data": {"id": user_id}}).status_code == 200
    assert c.get("/api/me").status_code == 401


def test_the_hosted_editions_secrets_are_scrubbed(monkeypatch):
    monkeypatch.setenv("WORKOS_API_KEY", "sk_test_workos_abcdef1234")
    assert keys.redact("rejected sk_test_workos_abcdef1234") == "rejected <workos secret …1234>"


def test_the_workos_addresses_carry_what_authkit_needs():
    cfg = Settings.model_validate({"workos": {"client_id": "client_01ABC"}})
    workos = WorkOS(cfg.model_copy(update={"fake_engines": True}))
    url = urlsplit(workos.sign_in_url("https://app.example/api/auth/callback", "s1", sign_up=True))
    assert url.path == "/user_management/authorize" and parse_qs(url.query) == {
        "client_id": ["client_01ABC"],
        "redirect_uri": ["https://app.example/api/auth/callback"],
        "response_type": ["code"],
        "provider": ["authkit"],
        "state": ["s1"],
        "screen_hint": ["sign-up"],
    }
    out = urlsplit(workos.sign_out_url("session_9", "https://app.example"))
    assert parse_qs(out.query) == {"session_id": ["session_9"], "return_to": ["https://app.example"]}


def test_the_local_edition_has_no_sign_in(client):
    assert client.get("/api/me").json()["id"] == LOCAL
    assert client.get("/api/auth/sign-in", follow_redirects=False).status_code == 404
