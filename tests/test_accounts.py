"""Accounts in the hosted edition: each person sees, changes and pays for only their own."""

from fastapi.routing import APIRoute
from test_api import storyboard

from lanternist.auth import FAKE_USER

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
    bob = c.post("/api/stories", json={"storyboard": storyboard(1)}, headers=BOB).json()["story"]["id"]

    assert [s["id"] for s in c.get("/api/stories").json()] == [ann]
    assert [s["id"] for s in c.get("/api/stories", headers=BOB).json()] == [bob]
    assert {j["story_id"] for j in c.get("/api/jobs").json()} == {ann}
    assert c.get("/api/jobs", headers=BOB).json() == []

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
