"""Keys, providers and settings through the API, in fake mode."""

import re

from lanternist import keys


def test_providers_work_in_fake_mode_without_keys(client):
    rows = {r["name"]: r for r in client.get("/api/providers").json()}
    assert rows["openrouter"]["source"] == "fake" and rows["openrouter"]["ok"]
    assert rows["openrouter"]["usage"]["limit"] == 10.0
    assert rows["fal"]["ok"] and "value" not in rows["fal"] and not rows["fal"]["needed"]


def test_keys_are_stored_but_never_returned(client):
    r = client.put("/api/providers/fal/key", json={"key": "fal-key-abcdef-1234"})
    assert r.status_code == 200
    row = r.json()
    assert row["source"] == "file" and row["stored_in"] == "file" and row["last4"] == "1234"
    assert (
        "fal-key-abcdef-1234" not in r.text and "fal-key-abcdef-1234" not in client.get("/api/providers").text
    )
    assert keys.get_key("fal").value == "fal-key-abcdef-1234"
    assert client.put("/api/providers/fal/key", json={"key": "two words"}).status_code == 422
    assert client.put("/api/providers/replicate/key", json={"key": "x"}).status_code == 404
    assert client.delete("/api/providers/fal/key").status_code == 204
    assert keys.get_key("fal").value is None


def test_a_rejected_key_shows_as_not_ok(client):
    row = client.put("/api/providers/openrouter/key", json={"key": "bad"}).json()
    assert row["configured"] and row["ok"] is False and "rejected" in row["detail"]


def test_settings_round_trip(client):
    rows = {r["key"]: r for r in client.get("/api/settings").json()}
    assert rows["defaults.video"] == {
        "key": "defaults.video",
        "label": "Video",
        "value": "local/ltx-2.5-22b-nvfp4",
        "source": "default",
        "capability": "video.image_to_video",
        "off": None,
    }
    assert rows["defaults.ambience"]["off"] and rows["defaults.budget_usd"]["capability"] is None
    r = client.put(
        "/api/settings",
        json={"changes": {"defaults.video": "fal/kling-v3-standard", "defaults.budget_usd": 2.5}},
    )
    assert r.status_code == 200
    rows = {x["key"]: x for x in r.json()}
    assert (
        rows["defaults.video"]["value"] == "fal/kling-v3-standard"
        and rows["defaults.video"]["source"] == "app"
    )
    # Now fal is needed by a default model, and the doctor says so.
    fal = next(x for x in client.get("/api/providers").json() if x["name"] == "fal")
    assert fal["needed"]
    bad = client.put("/api/settings", json={"changes": {"defaults.image": "fal/kling-v3-standard"}})
    assert bad.status_code == 422 and "video.image_to_video model" in bad.json()["detail"]
    reset = {
        x["key"]: x for x in client.put("/api/settings", json={"changes": {"defaults.video": None}}).json()
    }
    assert reset["defaults.video"]["source"] == "default"


def test_doctor_lists_providers(client):
    names = {c["name"]: c for c in client.get("/api/doctor").json()}
    assert names["openrouter"]["status"] == "ok" and "key from fake" in names["openrouter"]["detail"]
    assert names["fal"]["status"] == "ok"
    assert names["database"]["status"] == "ok" and re.search(
        r", at revision \d{4}$", names["database"]["detail"]
    )


BRIEF = {"idea": "A cat and a gull.", "minutes": 0.4}


def test_writing_on_openrouter_through_the_api(client, wait):
    created = client.post(
        "/api/stories", json={"brief": {**BRIEF, "writer": "openrouter/fake/frontier", "effort": "low"}}
    ).json()
    job = wait(created["job"]["id"])
    res = job["result"]
    assert res["writer"] == "openrouter/fake/frontier" and res["calls"] == 2 and res["cost_usd"] > 0
    assert any("$" in line for line in job["progress"]["log"])  # the log shows what each pass cost
    story = client.get(f"/api/stories/{created['story']['id']}").json()
    models = story["storyboard"]["models"]
    assert (models["writer"], models["writer_effort"]) == ("openrouter/fake/frontier", "low")
    assert story["writer"] == {
        "id": "openrouter/fake/frontier",
        "model": "fake/frontier",
        "local": False,
        "cost_usd": res["cost_usd"],
    }
    # The finished job now prices this writer from what it measured.
    cat = client.get("/api/models", params={"capability": "writer.chat"}).json()
    frontier = next(m for m in cat["models"] if m["id"] == "openrouter/fake/frontier")
    assert frontier["basis"] == "measured"


def test_the_default_writer_from_settings(client, wait):
    assert client.get("/api/models").json()["default"] == "ollama/qwen3.8:latest"
    client.put("/api/settings", json={"changes": {"defaults.writer": "openrouter/fake/cheap"}})
    assert client.get("/api/models").json()["default"] == "openrouter/fake/cheap"
    job = wait(client.post("/api/stories", json={"brief": BRIEF}).json()["job"]["id"])
    assert job["result"]["writer"] == "openrouter/fake/cheap"
    # The page lists the writer's passes from the snapshot, each counted as it ended.
    write = job["progress"]["stages"]["write"]
    assert write["passes"] == ["Drafting the story", "Planning the scenes"]
    assert (write["done"], write["total"]) == (2, 2)


def test_models_endpoint(client):
    cat = client.get("/api/models").json()
    assert cat["models"][0]["id"] == "ollama/qwen3.8:latest" and cat["providers"]["openrouter"]["configured"]
    pictures = client.get("/api/models", params={"capability": "image.keyframe"}).json()
    assert pictures["default"] == "local/flux2-klein-9b"
    assert all(m["available"] for m in pictures["models"])  # fake mode has a fal key
    assert client.get("/api/models", params={"capability": "music"}).status_code == 404


def test_an_openrouter_writer_needs_a_key(client, monkeypatch):
    monkeypatch.setattr(keys, "get_key", lambda provider, fake=False: keys.Key(provider, None, None))
    r = client.post("/api/stories", json={"brief": {**BRIEF, "writer": "openrouter/fake/frontier"}})
    assert r.status_code == 422 and "OpenRouter key" in r.json()["detail"]
    assert client.post("/api/stories", json={"brief": {**BRIEF, "writer": "gpt"}}).status_code == 422
