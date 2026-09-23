"""The API end to end with fake engines: import, board, edit, re-roll, render, download."""

import json

from lanternist.db import LOCAL


def storyboard(n=3, voice="demo"):
    """A storyboard to import; `voice` is a recording in the test voices, or a narrator's preset."""
    return {
        "title": "Test story",
        "voice": voice,
        "cast": [{"id": "a", "name": "Ann", "look": "girl in a red coat"}],
        "scenes": [
            {
                "n": i,
                "narration": [{"text": f"Scene {i} says a few words out loud."}],
                "visual": f"picture {i}",
                "cast": ["a"],
                "mode": "video" if i == 2 else "still",
            }
            for i in range(1, n + 1)
        ],
    }


def test_story_lifecycle(client, wait):
    assert client.get("/api/health").json()["fake_engines"] is True
    opts = client.get("/api/options").json()
    assert opts["styles"] and opts["languages"]
    voices = client.get("/api/voices/catalog", params={"language": "en"}).json()
    assert [r["name"] for r in voices["recordings"]] == ["demo"]

    created = client.post("/api/stories", json={"storyboard": storyboard()}).json()
    sid = created["story"]["id"]
    story = client.get(f"/api/stories/{sid}").json()
    assert story["version"] == 1 and story["board"]["scenes"][0]["keyframe"] is None
    assert story["board"]["scenes"][0]["line"] == "Scene 1 says a few words out loud."
    assert story["writer"] is None  # imported: nobody here wrote it

    wait(client.post(f"/api/stories/{sid}/board").json()["id"])
    board = client.get(f"/api/stories/{sid}").json()["board"]
    assert board["cast"] and all(s["keyframe"] and s["audio"] for s in board["scenes"])

    # A stale save is refused; a current one makes version 2.
    sb = client.get(f"/api/stories/{sid}").json()["storyboard"]
    assert client.put(f"/api/stories/{sid}", json={"storyboard": sb, "base_version": 0}).status_code == 409
    sb["scenes"][0]["visual"] = "a new picture"
    assert (
        client.put(f"/api/stories/{sid}", json={"storyboard": sb, "base_version": 1}).json()["version"] == 2
    )
    after = client.get(f"/api/stories/{sid}").json()["board"]["scenes"]
    assert after[0]["keyframe"] is None and after[1]["keyframe"] == board["scenes"][1]["keyframe"]

    # Re-rolling a scene makes a version with a new seed and redraws it.
    rr = client.post(f"/api/stories/{sid}/scenes/2/reroll").json()
    wait(rr["job"]["id"])
    story = client.get(f"/api/stories/{sid}").json()
    assert story["version"] == 3 and story["storyboard"]["scenes"][1]["seed"] is not None

    job = wait(client.post(f"/api/stories/{sid}/render").json()["id"])
    film = job["result"]["film"]
    stages = job["progress"]["stages"]
    assert {"narration", "keyframes", "motion", "clips", "mix"} <= set(stages)
    # Every scene's steps, as the page reads them: made in this render, or served from the board's cache.
    scenes = job["progress"]["scenes"]
    assert scenes["2"]["motion"]["state"] == "done" and scenes["2"]["motion"]["asset"]
    assert all(steps["clips"]["state"] == "done" for steps in scenes.values())
    assert scenes["1"]["narration"]["state"] == "cached" and "motion" not in scenes["1"]  # a still
    assert job["progress"]["spent_usd"] == 0 and stages["keyframes"]["doing"] == "Painting the scenes"
    # What makes each stage, and whether it's this machine: the page doesn't guess.
    assert (stages["clips"]["model"], stages["clips"]["local"]) == ("ffmpeg", True)
    assert stages["keyframes"]["model"] == "FLUX.2 [klein] 9B" and job["progress"]["sheet"] is True
    r = client.get(f"/api/assets/{film}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    assert client.get(f"/api/assets/{job['result']['vtt']}").headers["content-type"].startswith("text/vtt")
    listed = client.get("/api/stories").json()[0]
    assert listed["film"]["film"] == film and listed["progress"] is None  # nothing running

    assert client.delete(f"/api/stories/{sid}").status_code == 204
    assert client.get(f"/api/stories/{sid}").status_code == 404


def test_a_picture_is_served_small_and_made_once(client, wait, tmp_path):
    sid = client.post("/api/stories", json={"storyboard": storyboard(1)}).json()["story"]["id"]
    wait(client.post(f"/api/stories/{sid}/board").json()["id"])
    picture = client.get(f"/api/stories/{sid}").json()["board"]["scenes"][0]["keyframe"]
    full = client.get(f"/api/assets/{picture}")

    small = client.get(f"/api/assets/{picture}?w=500")
    assert small.status_code == 200 and small.headers["content-type"] == "image/jpeg"
    assert len(small.content) * 5 < len(full.content)
    [kept] = (tmp_path / "lib" / "derived").rglob("*.jpg")
    assert kept.name.endswith("-thumb@1-w768.jpg")
    made = kept.stat().st_mtime_ns
    assert client.get(f"/api/assets/{picture}?w=2000").content == small.content  # the largest there is
    assert kept.stat().st_mtime_ns == made  # served as kept, not made again
    assert len(client.get(f"/api/assets/{picture}?w=300").content) < len(small.content)  # a reel's slide
    assert "immutable" not in small.headers["cache-control"]

    film = wait(client.post(f"/api/stories/{sid}/render").json()["id"])["result"]["film"]
    assert client.get(f"/api/assets/{film}?w=300").status_code == 422
    assert client.get(f"/api/assets/{picture}?w=0").status_code == 422


def test_a_picture_that_cant_be_read_says_so(client, tmp_path):
    broken = "0" * 64 + ".png"
    path = tmp_path / "lib" / "assets" / "00" / broken
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a picture")
    r = client.get(f"/api/assets/{broken}?w=300")
    assert r.status_code == 500 and "Draw its scene again" in r.json()["detail"]


def test_two_saves_of_one_version_conflict(client, lands_first):
    """Two saves from the same version at the same moment (two tabs): the second is refused, rather than
    both becoming version 2."""
    import lanternist.api.app as appmod  # the app the client runs, on the test's own database

    sid = client.post("/api/stories", json={"storyboard": storyboard()}).json()["story"]["id"]
    sb = client.get(f"/api/stories/{sid}").json()["storyboard"]
    lands_first(
        appmod.db, lambda: appmod.db.save_edit(LOCAL, sid, sb | {"title": "Saved first"}, 1, "other tab")
    )
    second = {"storyboard": sb | {"title": "Saved second"}, "base_version": 1}
    refused = client.put(f"/api/stories/{sid}", json=second)
    assert refused.status_code == 409 and "changed since version 1" in refused.json()["detail"]
    story = client.get(f"/api/stories/{sid}").json()
    assert [v["version"] for v in story["versions"]] == [2, 1]
    assert story["storyboard"]["title"] == "Saved first"


def test_progress_streams_a_job_to_its_end(client):
    sid = client.post("/api/stories", json={"storyboard": storyboard(1)}).json()["story"]["id"]
    job = client.post(f"/api/stories/{sid}/cast").json()
    with client.stream("GET", f"/api/jobs/{job['id']}/events") as r:
        snaps = [
            json.loads(line.removeprefix("data: ")) for line in r.iter_lines() if line.startswith("data: ")
        ]
    assert snaps[-1]["id"] == job["id"] and snaps[-1]["status"] == "done"
    with client.stream("GET", "/api/jobs/gone/events") as r:
        assert r.read().decode() == "event: gone\ndata: {}\n\n"
