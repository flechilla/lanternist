"""The API end to end with fake engines: import, board, edit, re-roll, render, download."""

import importlib
import time

import pytest
from fastapi.testclient import TestClient

from lanternist import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "demo.wav").write_bytes(b"RIFF fake")
    toml = tmp_path / "lanternist.toml"
    toml.write_text(f'[paths]\nlibrary = "{tmp_path / "lib"}"\nvoices = ["{voices}"]\n')
    monkeypatch.setenv("LANTERNIST_CONFIG", str(toml))
    monkeypatch.setenv("LANTERNIST_FAKE_ENGINES", "1")
    config.settings.cache_clear()
    import lanternist.api.app as appmod

    appmod = importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        yield c
    config.settings.cache_clear()


def storyboard(n=3):
    return {"title": "Test story", "cast": [{"id": "a", "name": "Ann", "look": "girl in a red coat"}],
            "scenes": [{"n": i, "narration": [{"text": f"Scene {i} says a few words out loud."}],
                        "visual": f"picture {i}", "cast": ["a"], "mode": "video" if i == 2 else "still"}
                       for i in range(1, n + 1)]}


def wait(client, job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            assert job["status"] == "done", job["error"]
            return job
        time.sleep(0.2)
    raise TimeoutError(job_id)


def test_story_lifecycle(client):
    assert client.get("/api/health").json()["fake_engines"] is True
    opts = client.get("/api/options").json()
    assert any(v["name"] == "demo" for v in opts["voices"]) and opts["styles"]

    created = client.post("/api/stories", json={"storyboard": storyboard()}).json()
    sid = created["story"]["id"]
    story = client.get(f"/api/stories/{sid}").json()
    assert story["version"] == 1 and story["board"]["scenes"][0]["keyframe"] is None

    wait(client, client.post(f"/api/stories/{sid}/board").json()["id"])
    board = client.get(f"/api/stories/{sid}").json()["board"]
    assert board["cast"] and all(s["keyframe"] and s["audio"] for s in board["scenes"])

    # A stale save is refused; a current one makes version 2.
    sb = client.get(f"/api/stories/{sid}").json()["storyboard"]
    assert client.put(f"/api/stories/{sid}", json={"storyboard": sb, "base_version": 0}).status_code == 409
    sb["scenes"][0]["visual"] = "a new picture"
    assert client.put(f"/api/stories/{sid}", json={"storyboard": sb, "base_version": 1}).json()["version"] == 2
    after = client.get(f"/api/stories/{sid}").json()["board"]["scenes"]
    assert after[0]["keyframe"] is None and after[1]["keyframe"] == board["scenes"][1]["keyframe"]

    # Re-rolling a scene makes a version with a new seed and redraws it.
    rr = client.post(f"/api/stories/{sid}/scenes/2/reroll").json()
    wait(client, rr["job"]["id"])
    story = client.get(f"/api/stories/{sid}").json()
    assert story["version"] == 3 and story["storyboard"]["scenes"][1]["seed"] is not None

    job = wait(client, client.post(f"/api/stories/{sid}/render").json()["id"])
    film = job["result"]["film"]
    stages = job["progress"]["stages"]
    assert {"narration", "keyframes", "motion", "clips", "mix"} <= set(stages)
    r = client.get(f"/api/assets/{film}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    assert client.get(f"/api/assets/{job['result']['vtt']}").headers["content-type"].startswith("text/vtt")
    assert client.get("/api/stories").json()[0]["film"]["film"] == film

    assert client.delete(f"/api/stories/{sid}").status_code == 204
    assert client.get(f"/api/stories/{sid}").status_code == 404
