"""Keys, providers and settings through the API, in fake mode."""

import importlib

import pytest
from fastapi.testclient import TestClient

from lanternist import config, keys


@pytest.fixture
def client(tmp_path, monkeypatch):
    toml = tmp_path / "lanternist.toml"
    toml.write_text(f'[paths]\nlibrary = "{tmp_path / "lib"}"\nvoices = ["{tmp_path}"]\n')
    monkeypatch.setenv("LANTERNIST_CONFIG", str(toml))
    monkeypatch.setenv("LANTERNIST_FAKE_ENGINES", "1")
    config.settings.cache_clear()
    import lanternist.api.app as appmod

    appmod = importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        yield c
    config.settings.cache_clear()


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
        "label": "Video model",
        "value": "local/ltx-2.5-22b-nvfp4",
        "source": "default",
    }
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
