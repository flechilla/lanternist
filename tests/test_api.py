"""The API end to end with fake engines: import, board, edit, re-roll, render, download."""


def storyboard(n=3):
    return {
        "title": "Test story",
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
    r = client.get(f"/api/assets/{film}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    assert client.get(f"/api/assets/{job['result']['vtt']}").headers["content-type"].startswith("text/vtt")
    assert client.get("/api/stories").json()[0]["film"]["film"] == film

    assert client.delete(f"/api/stories/{sid}").status_code == 204
    assert client.get(f"/api/stories/{sid}").status_code == 404


def test_a_picture_is_served_small_and_made_once(client, wait, tmp_path):
    sid = client.post("/api/stories", json={"storyboard": storyboard(1)}).json()["story"]["id"]
    wait(client.post(f"/api/stories/{sid}/board").json()["id"])
    picture = client.get(f"/api/stories/{sid}").json()["board"]["scenes"][0]["keyframe"]
    full = client.get(f"/api/assets/{picture}")

    small = client.get(f"/api/assets/{picture}?w=300")
    assert small.status_code == 200 and small.headers["content-type"] == "image/jpeg"
    assert len(small.content) * 5 < len(full.content)
    [kept] = (tmp_path / "lib" / "derived").rglob("*.jpg")
    assert kept.name.endswith("-thumb@1-w768.jpg")
    made = kept.stat().st_mtime_ns
    assert client.get(f"/api/assets/{picture}?w=2000").content == small.content  # the largest there is
    assert kept.stat().st_mtime_ns == made  # served as kept, not made again
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
