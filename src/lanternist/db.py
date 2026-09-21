"""SQLite: stories, their versions, and jobs. Assets and the step cache stay plain files (see store.py).

Every save of a storyboard is a new version, and a job points at the version it ran on, so a film
always matches the script it came from.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Base(DeclarativeBase):
    pass


class Story(Base):
    __tablename__ = "stories"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(8), default="en")
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class StoryVersion(Base):
    __tablename__ = "story_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    storyboard: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))          # write | rewrite | cast | board | render
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


TERMINAL = ("done", "failed", "cancelled")


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.url = f"sqlite:///{path}"
        self.engine = create_engine(self.url, connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def _pragmas(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self) -> None:
        from alembic import command
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        cfg.set_main_option("sqlalchemy.url", self.url)
        command.upgrade(cfg, "head")

    # stories ----------------------------------------------------------------------------------
    def storyboard(self, s: Session, story_id: str, version: int | None = None) -> tuple[Story, StoryVersion]:
        story = s.get(Story, story_id)
        if story is None:
            raise KeyError(story_id)
        v = version or story.version
        row = s.query(StoryVersion).filter_by(story_id=story_id, version=v).one_or_none()
        if row is None:
            raise KeyError(f"{story_id} v{v}")
        return story, row

    def save_version(self, s: Session, story: Story, storyboard: dict, note: str = "") -> StoryVersion:
        from .storyboard import slugify

        story.version += 1
        story.title = storyboard.get("title", story.title)
        story.slug = slugify(story.title)
        story.language = storyboard.get("language", story.language)
        story.updated_at = now()
        row = StoryVersion(story_id=story.id, version=story.version, storyboard=storyboard, note=note)
        s.add(row)
        return row
