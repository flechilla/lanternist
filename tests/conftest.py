"""Shared fixtures. Every test runs away from the real keychain, the real key file and any keys in the
environment, and gets its own library folder."""

import importlib

import pytest
from fastapi.testclient import TestClient

from lanternist import config
from lanternist.config import Paths, Settings
from lanternist.db import Database


@pytest.fixture(autouse=True)
def _isolated_keys(request, tmp_path, monkeypatch):
    if request.node.get_closest_marker("live"):  # live tests use your real keys
        yield
        return
    monkeypatch.setenv("LANTERNIST_KEYRING", "0")
    monkeypatch.setenv("LANTERNIST_SECRETS_FILE", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from lanternist import providers

    providers.reset_fake()
    yield
    providers.reset_fake()


@pytest.fixture
def voices(tmp_path):
    """A voices folder holding the default narrator, `demo`."""
    folder = tmp_path / "voices"
    folder.mkdir()
    (folder / "demo.wav").write_bytes(b"RIFF fake")
    return folder


@pytest.fixture
def cfg(tmp_path) -> Settings:
    return Settings(paths=Paths(library=tmp_path / "lib"))


@pytest.fixture
def db(cfg) -> Database:
    d = Database(cfg.library / "lanternist.db")
    d.migrate()
    return d


@pytest.fixture
def client(tmp_path, voices, monkeypatch):
    """The app in fake mode on its own library, as `lanternist serve` would run it."""
    toml = tmp_path / "lanternist.toml"
    toml.write_text(f'[paths]\nlibrary = "{tmp_path / "lib"}"\nvoices = ["{voices}"]\n', encoding="utf-8")
    monkeypatch.setenv("LANTERNIST_CONFIG", str(toml))
    monkeypatch.setenv("LANTERNIST_FAKE_ENGINES", "1")
    config.settings.cache_clear()
    import lanternist.api.app as appmod

    appmod = importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        yield c
    config.settings.cache_clear()
