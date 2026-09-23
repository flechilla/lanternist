"""Shared fixtures. Every test runs away from the real keychain, the real key file and any keys in the
environment, and gets its own library folder and database.

The database is a SQLite file in the library. With LANTERNIST_TEST_DATABASE_URL set to an admin URL
of a Postgres server (`scripts/check postgres`), each test gets a Postgres database of its own
instead, cloned from one migrated once per session, and dropped after the test."""

import asyncio
import importlib
import os
import time
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, make_url, text

from lanternist import config, providers
from lanternist.config import Paths, Settings
from lanternist.db import Database, Story
from lanternist.providers.fake import FakeWorld
from lanternist.storyboard import CastMember, Line, Scene, Storyboard

TEST_DATABASE_URL = os.environ.get("LANTERNIST_TEST_DATABASE_URL")


def pytest_collection_modifyitems(items):
    if TEST_DATABASE_URL:
        for item in items:
            if item.get_closest_marker("sqlite_only"):
                item.add_marker(pytest.mark.skip(reason="checks a local SQLite library file"))


@pytest.fixture(autouse=True)
def _isolated_database(monkeypatch):
    """A LANTERNIST_DATABASE_URL in the shell would point the app under test at that database."""
    monkeypatch.delenv("LANTERNIST_DATABASE_URL", raising=False)


def _on(database: str) -> str:
    """The test server's URL, on another of its databases."""
    return make_url(TEST_DATABASE_URL).set(database=database).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def _postgres() -> Iterator[tuple[Engine, str]]:
    """The test server, and a database on it at head that each test's database is a copy of."""
    # CREATE DATABASE can't run in a transaction.
    admin = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    template = f"lanternist_template_{uuid.uuid4().hex[:8]}"
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{template}"'))
    migrated = Database(_on(template))
    migrated.migrate()
    migrated.close()  # a template is copied only while nothing is connected to it
    yield admin, template
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{template}"'))
    admin.dispose()


@pytest.fixture
def database_url(request, tmp_path) -> Iterator[str]:
    """This test's database: lanternist.db in its library, or a fresh copy of the Postgres template."""
    if not TEST_DATABASE_URL:
        yield f"sqlite:///{tmp_path / 'lib' / 'lanternist.db'}"
        return
    admin, template = request.getfixturevalue("_postgres")
    name = f"t_{uuid.uuid4().hex}"
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{template}"'))
    yield _on(name)
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


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
    from lanternist.providers import openrouter

    providers.reset_fake()
    openrouter._models_cache.clear()
    yield
    providers.reset_fake()
    openrouter._models_cache.clear()


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
def fake_cfg(tmp_path, voices) -> Settings:
    """Fake engines on the test's own library, so boards and renders run end to end in seconds."""
    return Settings(paths=Paths(library=tmp_path / "lib", voices=[voices]), fake_engines=True)


@pytest.fixture
def fakes(fake_cfg) -> FakeWorld:
    """The fake fal, OpenRouter and Ollama that fake mode talks to, to steer and inspect."""
    providers.transport(fake_cfg)
    world = providers.fake_world()
    assert world is not None
    return world


@pytest.fixture
def make_story():
    """A small storyboard: one scene per mode given, each showing one character and saying a few words."""

    def make(modes=("still", "video", "still"), **kw) -> Storyboard:
        return Storyboard(
            title="Test",
            cast=[CastMember(id="a", name="Ann", look="girl in a red coat")],
            scenes=[
                Scene(
                    n=i,
                    narration=[Line(text=f"Scene {i} has a few words to say out loud here.")],
                    visual=f"picture {i}",
                    cast=["a"],
                    mode=m,
                )
                for i, m in enumerate(modes, 1)
            ],
            **kw,
        )

    return make


@pytest.fixture
def story_row(db) -> str:
    """A story in the database, for pipelines that record spend and check its budget."""
    with db.session() as s:
        s.add(Story(id="s1", slug="test", title="Test", version=1))
        s.commit()
    return "s1"


@pytest.fixture
def db(database_url) -> Iterator[Database]:
    d = Database(database_url)
    d.migrate()
    yield d
    d.close()


@pytest.fixture
def lands_first():
    """Arranges another save to land at the same moment as the one under test: `save` runs once, on a
    connection of its own, just as the database is about to update a story, after the save under test
    has read the version it builds on."""
    listening = []

    def arrange(db: Database, save) -> None:
        landed: list[bool] = []

        def hook(_conn, _cursor, statement, *_) -> None:
            if statement.startswith("UPDATE stories") and not landed:
                landed.append(True)
                save()

        event.listen(db.engine, "before_cursor_execute", hook)
        listening.append((db, hook))

    yield arrange
    for db, hook in listening:
        event.remove(db.engine, "before_cursor_execute", hook)


# The hosted edition in tests: remote models only, and the test client's own address as its origin.
HOSTED_TOML = """edition = "hosted"

[hosted]
url = "http://testserver"

[defaults]
writer = "openrouter/openai/gpt-5.6-luna"
tts = "fal/chatterbox-multilingual"
image = "fal/flux-2-klein-9b"
video = "fal/h3-max-turbo"

"""


def _serve(tmp_path, voices, database_url, monkeypatch, head: str = "") -> Iterator[TestClient]:
    """The app in fake mode on its own library and database, as `lanternist serve` would run it, with
    `head` at the top of its lanternist.toml."""
    toml = tmp_path / "lanternist.toml"
    toml.write_text(
        f'{head}[paths]\nlibrary = "{tmp_path / "lib"}"\nvoices = ["{voices}"]\n\n'
        f'[database]\nurl = "{database_url}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LANTERNIST_CONFIG", str(toml))
    monkeypatch.setenv("LANTERNIST_FAKE_ENGINES", "1")
    config.settings.cache_clear()
    import lanternist.api.app as appmod

    appmod = importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        yield c
    appmod.db.close()
    config.settings.cache_clear()


@pytest.fixture
def client(tmp_path, voices, database_url, monkeypatch):
    """The local edition."""
    yield from _serve(tmp_path, voices, database_url, monkeypatch)


@pytest.fixture
def hosted_client(tmp_path, voices, database_url, monkeypatch):
    """The hosted edition."""
    yield from _serve(tmp_path, voices, database_url, monkeypatch, HOSTED_TOML)


@pytest.fixture
def wait(request):
    """Waits for a job to finish and returns it; the test fails unless it finished as done. It asks the
    test's own app, hosted or local: asking for the other would start that one in its place."""
    client = request.getfixturevalue("hosted_client" if "hosted_client" in request.fixturenames else "client")

    def wait_for(job_id: str, timeout: float = 60) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in ("done", "failed", "cancelled"):
                assert job["status"] == "done", job["error"]
                return job
            time.sleep(0.2)
        raise TimeoutError(job_id)

    return wait_for


@pytest.fixture
def until():
    """Waits, in an async test, until `cond()` holds; fails after `timeout` seconds."""

    async def wait(cond, timeout: float = 5.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not cond():
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError
            await asyncio.sleep(0.01)

    return wait
