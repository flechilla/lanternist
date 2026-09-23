"""The two editions: what the hosted one leaves out, and what it offers instead."""

import pytest
from pydantic import ValidationError
from test_api import storyboard

from lanternist import config, registry
from lanternist.config import Settings

PRESET = "Vivian"  # a voice of the hosted tests' narrator (HOSTED_TOML): hosted clones no recording


def test_the_hosted_edition_refuses_models_it_cant_run():
    with pytest.raises(
        ValidationError, match=r"defaults\.tts is local/qwen3-tts-1\.7b, a model on this machine"
    ):
        Settings.model_validate({"edition": "hosted"})
    remote = {
        "tts": "fal/qwen-3-tts-1.7b",
        "image": "fal/flux-2-klein-9b",
        "video": "fal/h3-max-turbo",
    }
    with pytest.raises(ValidationError, match=r"defaults\.writer is empty \(the local Ollama model\)"):
        Settings.model_validate({"edition": "hosted", "defaults": remote})
    with pytest.raises(ValidationError, match=r"defaults\.checker is ollama/qwen3\.8"):
        Settings.model_validate(
            {
                "edition": "hosted",
                "defaults": remote
                | {"writer": "openrouter/openai/gpt-5.6-luna", "checker": "ollama/qwen3.8"},
            }
        )


def test_the_hosted_edition_starts_only_on_models_it_offers(tmp_path, monkeypatch):
    """Chatterbox runs remotely but only clones, so hosted doesn't offer it; nor a picture model as the
    narrator."""
    toml = tmp_path / "lanternist.toml"
    monkeypatch.setenv("LANTERNIST_CONFIG", str(toml))
    for tts in ("fal/chatterbox-multilingual", "fal/flux-2-klein-9b"):
        toml.write_text(
            f'edition = "hosted"\n\n[defaults]\nwriter = "openrouter/openai/gpt-5.6-luna"\ntts = "{tts}"\n'
            'image = "fal/flux-2-klein-9b"\nvideo = "fal/h3-max-turbo"\n\n'
            f'[paths]\nlibrary = "{tmp_path / "lib"}"\n'
        )
        config.settings.cache_clear()
        offered = (
            rf"defaults\.tts is {tts}, which the hosted edition doesn't offer here: pick one of .*qwen-3-tts"
        )
        with pytest.raises(ValueError, match=offered):
            config.settings()
    config.settings.cache_clear()


def test_the_hosted_registry_offers_only_remote_models_licensed_for_sale():
    offered = registry.load(hosted=True)
    assert offered and all(e.remote and e.commercial_use is True for e in offered.values())
    everything = registry.load()
    assert set(everything) - set(offered) == {e.id for e in everything.values() if not e.sellable}
    assert "local/flux2-klein-9b" in everything and "fal/flux-2-klein-9b" in offered


def test_the_local_edition_says_so_and_keeps_its_machines_routes(client):
    assert client.get("/api/options").json()["edition"] == "local"
    assert client.get("/api/providers").status_code == 200
    assert client.get("/api/doctor").status_code == 200


def test_the_hosted_edition_leaves_out_keys_the_doctor_and_recordings(hosted_client):
    c = hosted_client
    assert c.get("/api/options").json()["edition"] == "hosted"
    assert c.get("/api/providers").status_code == 404
    assert c.get("/api/doctor").status_code == 404
    # The web app's catch-all answers GET only, so a write to a missing route is 405.
    assert c.put("/api/providers/fal/key", json={"key": "fal-key-abcdef-1234"}).status_code == 405
    assert c.delete("/api/providers/fal/key").status_code == 405
    upload = {"audio": ("grandma.wav", b"RIFF", "audio/wav")}
    assert c.post("/api/voices", data={"name": "Grandma"}, files=upload).status_code == 405


def test_the_hosted_edition_clones_no_ones_recording(hosted_client):
    """The recordings on the server (the test voices hold "demo") are neither offered, played nor
    cloned: cloning waits for recorded consent."""
    c = hosted_client
    qwen = c.get("/api/voices/catalog", params={"tts": "fal/qwen-3-tts-1.7b"}).json()
    assert qwen["clone"] and qwen["recordings"] == [] and qwen["presets"]
    assert c.get("/api/voices/demo/audio").status_code == 404
    narrators = [m["id"] for m in c.get("/api/models", params={"capability": "tts.speak"}).json()["models"]]
    assert "fal/chatterbox-multilingual" not in narrators  # it only clones
    sid = c.post("/api/stories", json={"storyboard": storyboard(voice="demo")}).json()["story"]["id"]
    r = c.get(f"/api/stories/{sid}/estimate")
    assert r.status_code == 422 and r.json()["detail"].startswith(
        "“demo” isn't one of Qwen3-TTS 1.7B · fal's voices"
    )


def test_the_hosted_pickers_offer_no_model_on_this_machine(hosted_client):
    c = hosted_client
    for capability in ("tts.speak", "image.keyframe", "video.image_to_video"):
        models = c.get("/api/models", params={"capability": capability}).json()["models"]
        assert models and not any(m["local"] for m in models)
    writers = c.get("/api/models").json()
    assert writers["models"] and all(w["provider"] == "openrouter" for w in writers["models"])


def test_a_hosted_story_cant_ask_for_a_local_writer(hosted_client):
    brief = {"idea": "a fox who can't sleep", "writer": "ollama/qwen3.8:latest"}
    r = hosted_client.post("/api/stories", json={"brief": brief})
    assert r.status_code == 422 and "runs on your own machine" in r.json()["detail"]


def test_hosted_settings_are_only_the_story_defaults(hosted_client):
    c = hosted_client
    keys = [r["key"] for r in c.get("/api/settings").json()]
    assert keys and all(k.startswith("defaults.") for k in keys)
    r = c.put("/api/settings", json={"changes": {"fal.max_concurrency": 40}})
    assert r.status_code == 422 and "can't change fal.max_concurrency here" in r.json()["detail"]
    r = c.put("/api/settings", json={"changes": {"defaults.image": "local/flux2-klein-9b"}})
    assert r.json()["detail"] == (
        "defaults.image is local/flux2-klein-9b, a model on this machine, which the hosted edition "
        "doesn't run: pick a remote one"
    )
    assert (
        c.put("/api/settings", json={"changes": {"defaults.image": "fal/nano-banana-2"}}).status_code == 200
    )


def test_a_hosted_story_renders_on_remote_models(hosted_client, wait):
    c = hosted_client
    sid = c.post("/api/stories", json={"storyboard": storyboard(voice=PRESET)}).json()["story"]["id"]
    job = wait(c.post(f"/api/stories/{sid}/render").json()["id"])
    stages = job["progress"]["stages"]
    assert not any(stages[s]["local"] for s in ("narration", "keyframes", "motion"))
    assert job["progress"]["spent_usd"] > 0  # fal's fake bills like fal
    assert c.get(f"/api/assets/{job['result']['film']}").status_code == 200
