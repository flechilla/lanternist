"""Phase A data: the 0002 migration, step runs, prices, settings, uploads, keys and the registry."""

import sqlite3
import stat
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command

from lanternist import keys, prefs, registry
from lanternist.config import Defaults, Paths, Settings
from lanternist.db import Database, Job, StepRun, Story, now, to_micros, to_usd
from lanternist.engines import local as local_engines

REAL_DB = Path.home() / "Lanternist" / "lanternist.db"


def counts(path: Path) -> dict:
    c = sqlite3.connect(path)
    try:
        return {
            t: c.execute(f"select count(*) from {t}").fetchone()[0]
            for t in ("stories", "story_versions", "jobs")
        }
    finally:
        c.close()


# ------------------------------------------------------------------------------------ migration
def test_migration_keeps_mvp_rows(tmp_path):
    d = Database(tmp_path / "old.db")
    command.upgrade(d.alembic_config(), "0001")
    with sqlite3.connect(tmp_path / "old.db") as c:
        c.execute("insert into stories values ('s1','luna','Luna','es',1,'2026-09-01','2026-09-01')")
        c.execute(
            "insert into story_versions (story_id, version, storyboard, note, created_at) "
            "values ('s1', 1, '{\"title\": \"Luna\"}', 'written', '2026-09-01')"
        )
        c.execute(
            "insert into jobs values ('j1','s1',1,'render','done','{}','{}','{\"film\": \"x.mp4\"}',"
            "null,'2026-09-01',null,null)"
        )
    before = counts(tmp_path / "old.db")
    d.migrate()
    assert counts(tmp_path / "old.db") == before
    with d.session() as s:
        assert s.get(Story, "s1").budget_micros is None and s.get(Job, "j1").estimate is None
        assert s.get(Job, "j1").result == {"film": "x.mp4"}
    command.downgrade(d.alembic_config(), "0001")
    assert counts(tmp_path / "old.db") == before
    command.upgrade(d.alembic_config(), "head")
    assert counts(tmp_path / "old.db") == before


def test_migration_0003_keeps_jobs_and_allows_ones_without_a_story(tmp_path):
    d = Database(tmp_path / "old.db")
    command.upgrade(d.alembic_config(), "0002")
    with sqlite3.connect(tmp_path / "old.db") as c:
        c.execute(
            "insert into stories (id, slug, title, language, version, created_at, updated_at) values ('s1','luna','Luna','es',1,'2026-09-01','2026-09-01')"
        )
        c.execute(
            "insert into jobs (id, story_id, version, kind, status, params, progress, created_at) "
            "values ('j1','s1',1,'render','done','{}','{}','2026-09-01')"
        )
    before = counts(tmp_path / "old.db")
    d.migrate()
    assert counts(tmp_path / "old.db") == before
    with d.session() as s:
        assert s.get(Job, "j1").story_id == "s1"
        s.add(Job(id="j2", story_id=None, kind="sample", params={}, progress={}))
        s.commit()
    command.downgrade(d.alembic_config(), "0002")
    assert counts(tmp_path / "old.db") == before  # the sample went; the story's job stayed


def test_models_match_the_migrations(db):
    """A column added to db.py without a migration (or the other way round) fails here."""
    command.check(db.alembic_config())
    command.downgrade(db.alembic_config(), "base")
    command.upgrade(db.alembic_config(), "head")


@pytest.mark.skipif(not REAL_DB.is_file(), reason="no library database on this machine")
def test_migration_on_a_copy_of_the_real_library(tmp_path):
    copy = tmp_path / "copy.db"
    src = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    dst = sqlite3.connect(copy)
    src.backup(dst)
    src.close()
    dst.close()
    before = counts(copy)
    Database(copy).migrate()
    assert counts(copy) == before


def test_deleting_a_story_keeps_what_it_cost(db):
    with db.session() as s:
        s.add(Story(id="s1", slug="a", title="A", version=0))
        s.flush()
        s.add(Job(id="j1", story_id="s1", kind="render", params={}, progress={}))
        s.commit()
    db.start_run(
        story_id="s1",
        job_id="j1",
        stage="motion",
        model_id="fal/x",
        provider="fal",
        status="done",
        cost_micros=to_micros("0.42"),
        cost_source="computed",
    )
    assert db.spend_micros(story_id="s1") == 420_000
    with db.session() as s:
        s.query(Job).filter_by(story_id="s1").delete()
        s.delete(s.get(Story, "s1"))
        s.commit()
    with db.session() as s:
        run = s.query(StepRun).one()
        assert run.story_id is None and run.job_id is None and run.cost_micros == 420_000
    assert db.spend_micros() == 420_000


# ------------------------------------------------------------------------------------ helpers
def test_money_is_integer_micros():
    assert to_micros("0.084") * 14 == to_micros("1.176")
    assert to_micros(0.1) == 100_000 and to_usd(1_500_000) == 1.5 and to_usd(None) is None


def test_prices_are_recorded_only_when_they_change(db):
    assert db.record_price("fal/kling", "output_second", "0.084", "fal_pricing_api")
    assert not db.record_price("fal/kling", "output_second", "0.0840", "fal_pricing_api")
    assert db.record_price("fal/kling", "output_second", "0.084", "fal_pricing_api", status="deprecated")
    assert db.record_price("fal/kling", "output_second", "0.09", "fal_pricing_api", status="deprecated")
    latest = db.latest_prices()["fal/kling"]
    assert latest.unit_price == "0.09" and latest.status == "deprecated"


def test_uploads_are_reused_until_close_to_expiry(db):
    db.save_upload("fal", "abc.png", "https://cdn/abc.png", now() + timedelta(hours=1))
    assert db.upload_url("fal", "abc.png") == "https://cdn/abc.png"
    db.save_upload("fal", "abc.png", "https://cdn/abc2.png", now() + timedelta(minutes=5))
    assert db.upload_url("fal", "abc.png") is None
    assert db.upload_url("openrouter", "abc.png") is None


def test_open_run_finds_only_unfinished_requests(db):
    db.start_run(stage="motion", model_id="m", provider="fal", status="done", step_key="k")
    assert db.open_run("k", "fal") is None
    rid = db.start_run(
        stage="motion", model_id="m", provider="fal", status="submitted", step_key="k", urls={"status": "s"}
    )
    assert db.open_run("k", "fal").id == rid
    db.update_run(rid, status="running")
    assert db.open_run("k", "fal").id == rid and db.open_run("k", "local") is None


# ------------------------------------------------------------------------------------ settings
def test_settings_precedence(tmp_path, db, monkeypatch):
    toml = tmp_path / "lanternist.toml"
    toml.write_text("[defaults]\nbudget_usd = 8.0\n")
    monkeypatch.setenv("LANTERNIST_CONFIG", str(toml))
    cfg = Settings(paths=Paths(library=tmp_path / "lib"), defaults=Defaults(budget_usd=8.0))
    rows = {r["key"]: r for r in prefs.describe(cfg, db)}
    assert rows["defaults.budget_usd"]["source"] == "file" and rows["defaults.budget_usd"]["value"] == 8.0
    assert rows["defaults.video"]["source"] == "default"

    prefs.update(cfg, db, {"defaults.budget_usd": 3.5, "defaults.video": "fal/kling-v3-standard"})
    eff = prefs.effective(cfg, db)
    assert eff.defaults.budget_usd == 3.5 and eff.defaults.video == "fal/kling-v3-standard"
    assert {r["key"]: r["source"] for r in prefs.describe(cfg, db)}["defaults.budget_usd"] == "app"

    prefs.update(cfg, db, {"defaults.budget_usd": None})
    assert prefs.effective(cfg, db).defaults.budget_usd == 8.0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"paths.library": "/tmp"}, "can't change"),
        ({"defaults.video": "fal/flux-2-klein-9b"}, "image.keyframe model"),
        ({"defaults.tts": "fal/nope"}, "no model"),
        ({"defaults.writer": "gpt"}, "an LLM is"),
        ({"fal.max_concurrency": 0}, "concurrency"),
        ({"defaults.budget_usd": "lots"}, "budget_usd"),
    ],
)
def test_settings_are_validated(tmp_path, db, change, message):
    cfg = Settings(paths=Paths(library=tmp_path / "lib"))
    with pytest.raises(ValueError, match=message):
        prefs.update(cfg, db, change)
    assert db.saved_settings() == {}


# ------------------------------------------------------------------------------------ keys
def test_keys_come_from_env_then_file(monkeypatch):
    assert keys.get_key("fal").value is None
    assert keys.set_key("fal", "  abcd-1234-efgh-5678 ") == "file"
    k = keys.get_key("fal")
    assert (k.value, k.source, k.last4) == ("abcd-1234-efgh-5678", "file", "5678")
    assert stat.S_IMODE(keys.secrets_file().stat().st_mode) == 0o600
    monkeypatch.setenv("FAL_KEY", "from-the-environment")
    assert keys.get_key("fal").source == "env"
    monkeypatch.delenv("FAL_KEY")
    keys.clear_key("fal")
    assert keys.get_key("fal").value is None
    assert keys.get_key("fal", fake=True).source == "fake"
    with pytest.raises(ValueError, match="doesn't look like an API key"):
        keys.set_key("fal", "has spaces in it")
    with pytest.raises(ValueError, match="unknown provider"):
        keys.get_key("replicate")


def test_redact_hides_keys():
    keys.set_key("openrouter", "sk-or-v1-secretsecret9999")
    assert keys.redact("401 for sk-or-v1-secretsecret9999") == "401 for <openrouter key …9999>"
    assert keys.redact(None) is None


# ------------------------------------------------------------------------------------ registry
def test_registry_entries_are_consistent():
    entries = registry.load()
    local = {e.engine_id for e in entries.values() if e.provider == "local"}
    # The local entries carry today's step-key engine ids, so the existing cache stays valid.
    assert {local_engines.TTS, local_engines.KLEIN, local_engines.LTX} == local
    for e in entries.values():
        assert e.capability in registry.CAPABILITIES
        if e.provider == "fal":
            assert e.endpoint and e.family and e.price.usd is not None and e.price.synced
        else:
            assert e.price.gpu_seconds
        if e.capability == "video.image_to_video" and e.provider == "fal":
            assert e.durations.lengths() and (
                e.audio == "ambience" or e.defaults.get("generate_audio") is False
            )
    d = Defaults()
    for model in (d.tts, d.image, d.video):
        assert model in entries
    assert entries["fal/wan-2.6-flash"].defaults["enable_prompt_expansion"] is False
    assert entries["fal/qwen-3-tts-1.7b"].defaults["max_new_tokens"] > 200
    assert entries["fal/kling-v3-standard"].durations.lengths()[:2] == [3, 4]


def test_registry_user_file_and_synced_prices(tmp_path, db):
    lib = tmp_path / "lib"
    registry.user_file(lib).write_text(
        '[[model]]\nid = "fal/veo-3.1-fast"\ndisabled = true\n\n'
        '[[model]]\nid = "fal/kling-v3-standard"\nprice = { usd = "0.07" }\n'
    )
    entries = registry.load(lib)
    assert "fal/veo-3.1-fast" not in entries
    kling = entries["fal/kling-v3-standard"]
    assert str(kling.price.usd) == "0.07" and kling.price.unit == "output_second"

    db.record_price("fal/kling-v3-standard", "seconds", "0.14", "fal_pricing_api")
    db.record_price("fal/flux-2-klein-9b#text_to_image", "megapixels", "0.007", "fal_pricing_api")
    db.record_price("fal/nano-banana-2", "images", "0.08", "fal_pricing_api", status="deprecated")
    entries = registry.load(lib, db)
    kling = entries["fal/kling-v3-standard"]
    # What fal bills per unit sits beside the list price; it never replaces it.
    assert str(kling.price.usd) == "0.07" and str(kling.billing[""].unit_price) == "0.14"
    assert kling.billing[""].unit == "seconds"
    klein = entries["fal/flux-2-klein-9b"]
    assert (
        str(klein.billing["text_to_image"].unit_price) == "0.007"
        and str(klein.price.tiers["text_to_image"]) == "0.006"
    )
    assert entries["fal/nano-banana-2"].status == "deprecated"


def test_a_fal_model_without_a_list_price_is_refused(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    registry.user_file(lib).write_text(
        '[[model]]\nid = "fal/new"\nlabel = "New"\ncapability = "tts.speak"\nprovider = "fal"\n'
        'family = "elevenlabs"\nendpoint = "x"\nprice = { unit = "1k_chars" }\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fal/new has no list price"):
        registry.load(lib)


def test_unit_names_from_fal():
    assert registry.normalise_unit("seconds") == "output_second"
    assert registry.normalise_unit("Megapixels") == "megapixel"
    assert registry.normalise_unit("1000 characters") == "1k_chars"
    assert registry.normalise_unit("images") == "image"
    assert registry.normalise_unit("gpu hours") == "gpu hours"
