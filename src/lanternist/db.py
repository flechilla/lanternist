"""SQLite: stories, their versions, jobs, and what every step cost. Assets and the step cache stay
plain files (see store.py).

Every save of a storyboard is a new version, and a job points at the version it ran on, so a film
always matches the script it came from. `step_runs` logs each step that actually ran (local or
remote, with its cost), and doubles as the record that lets a restart resume a remote request
instead of paying for it twice.

Portable on purpose, so a later move off SQLite is a copy: money is integer micro-dollars, prices
are decimal strings, columns use SQLAlchemy's own types, and every query goes through here.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

if TYPE_CHECKING:
    from alembic.config import Config


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def to_micros(usd: Decimal | float | str) -> int:
    return int((Decimal(str(usd)) * 1_000_000).to_integral_value())


def to_usd(micros: int | None) -> float | None:
    return None if micros is None else micros / 1_000_000


class Base(DeclarativeBase):
    pass


class Story(Base):
    __tablename__ = "stories"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(8), default="en")
    version: Mapped[int] = mapped_column(Integer, default=0)
    budget_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # None: the default
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
    kind: Mapped[str] = mapped_column(String(16))  # write | rewrite | cast | board | render
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimate: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # shown before it ran, with price date
    created_at: Mapped[datetime] = mapped_column(default=now)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


TERMINAL = ("done", "failed", "cancelled")
OPEN_RUN = ("submitted", "running")


class StepRun(Base):
    """One step that actually ran: the invoice line, the resume record, the estimator's data."""

    __tablename__ = "step_runs"
    __table_args__ = (
        Index("ix_step_runs_key_status", "step_key", "status"),
        Index("ix_step_runs_provider_created", "provider", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # SET NULL, not CASCADE: what was spent stays counted after its story is deleted.
    story_id: Mapped[str | None] = mapped_column(ForeignKey("stories.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    scene: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(16))  # write | narration | cast | keyframes | motion | ambience
    step_key: Mapped[str | None] = mapped_column(String(64))  # the cache key; None for writer calls
    model_id: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(16))  # local | ollama | openrouter | fal
    status: Mapped[str] = mapped_column(
        String(16), default="running"
    )  # submitted | running | done | failed | cancelled
    request_id: Mapped[str | None] = mapped_column(String(100))
    urls: Mapped[dict | None] = mapped_column(JSON)  # fal: status, response, cancel
    units: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    cost_source: Mapped[str] = mapped_column(String(16), default="none")  # reported | computed | none
    estimate_micros: Mapped[int | None] = mapped_column(BigInteger)
    gpu_seconds: Mapped[float | None] = mapped_column(Float)
    wall_seconds: Mapped[float | None] = mapped_column(Float)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # tokens, billable units, queue wait, …
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()


class ModelPrice(Base):
    """Price and status history: a row only when either changes, so an old estimate can be explained."""

    __tablename__ = "model_prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(200), index=True)
    endpoint: Mapped[str | None] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[str] = mapped_column(String(40))  # decimal string: token prices go to 1e-7 USD
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | deprecated, from the catalog
    source: Mapped[str] = mapped_column(String(24))  # fal_pricing_api | registry | openrouter
    synced_at: Mapped[datetime] = mapped_column(default=now)


class Setting(Base):
    """What the Settings page saves; wins over lanternist.toml. Never API keys."""

    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[object | None] = mapped_column(JSON)  # nullable, as migration 0002 made it
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class Upload(Base):
    """A file we put on a provider's storage, reused until shortly before it expires."""

    __tablename__ = "uploads"
    __table_args__ = (UniqueConstraint("provider", "asset"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(16))
    asset: Mapped[str] = mapped_column(String(80))
    url: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(default=now)


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

    def alembic_config(self) -> "Config":
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        cfg.set_main_option("sqlalchemy.url", self.url)
        return cfg

    def migrate(self) -> None:
        from alembic import command

        command.upgrade(self.alembic_config(), "head")

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

    def create_story(self, title: str, language: str, storyboard: dict | None = None) -> Story:
        """A new story; with a storyboard (an import) it starts at version 1, else at 0 until it's written."""
        from .storyboard import slugify

        with self.session() as s:
            story = Story(slug=slugify(title), title=title, language=language, version=0)
            s.add(story)
            s.flush()
            if storyboard is not None:
                self.save_version(s, story, storyboard, note="imported")
            s.commit()
            return story

    def get_story(self, story_id: str) -> Story | None:
        with self.session() as s:
            return s.get(Story, story_id)

    def get_version(self, story_id: str, version: int) -> StoryVersion | None:
        with self.session() as s:
            return s.query(StoryVersion).filter_by(story_id=story_id, version=version).one_or_none()

    def story_versions(self, story_id: str) -> list[StoryVersion]:
        """Newest first."""
        with self.session() as s:
            q = s.query(StoryVersion).filter_by(story_id=story_id).order_by(StoryVersion.version.desc())
            return q.all()

    def story_jobs(self, story_id: str, limit: int) -> list[Job]:
        """The newest `limit` jobs of a story, newest first."""
        with self.session() as s:
            return (
                s.query(Job).filter_by(story_id=story_id).order_by(Job.created_at.desc()).limit(limit).all()
            )

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

    def add_version(self, story_id: str, storyboard: dict, note: str = "") -> int:
        """Save a storyboard as the story's next version, in a session of its own; returns the version."""
        with self.session() as s:
            story = s.get(Story, story_id)
            if story is None:
                raise KeyError(story_id)  # deleted while a job was writing it
            row = self.save_version(s, story, storyboard, note=note)
            s.commit()
            return row.version

    # jobs -------------------------------------------------------------------------------------
    def update_job(self, job_id: str, **fields) -> Job | None:
        """Set fields on a job; None if it's gone, deleted with its story."""
        with self.session() as s:
            job = s.get(Job, job_id)
            if job is not None:
                for k, v in fields.items():
                    setattr(job, k, v)
                s.commit()
            return job

    # step runs --------------------------------------------------------------------------------
    def start_run(self, **fields) -> int:
        with self.session() as s:
            run = StepRun(**fields)
            s.add(run)
            s.commit()
            return run.id

    def update_run(self, run_id: int, **fields) -> None:
        with self.session() as s:
            run = s.get(StepRun, run_id)
            for k, v in fields.items():
                setattr(run, k, v)
            s.commit()

    def get_run(self, run_id: int) -> StepRun | None:
        with self.session() as s:
            return s.get(StepRun, run_id)

    def open_run(self, step_key: str, provider: str) -> StepRun | None:
        """The newest submitted or running request for this step, if a restart left one behind."""
        with self.session() as s:
            return s.scalars(
                select(StepRun)
                .where(
                    StepRun.step_key == step_key, StepRun.provider == provider, StepRun.status.in_(OPEN_RUN)
                )
                .order_by(StepRun.created_at.desc())
            ).first()

    def spend_micros(
        self,
        story_id: str | None = None,
        job_id: str | None = None,
        since: datetime | None = None,
        stage: str | None = None,
    ) -> int:
        q = select(func.coalesce(func.sum(StepRun.cost_micros), 0))
        if story_id:
            q = q.where(StepRun.story_id == story_id)
        if job_id:
            q = q.where(StepRun.job_id == job_id)
        if stage:
            q = q.where(StepRun.stage == stage)
        if since:
            q = q.where(StepRun.created_at >= since)
        with self.session() as s:
            return int(s.scalar(q))

    def spend_by_story(self) -> dict[str, int]:
        """What each story has cost so far, in one query, for the library."""
        q = (
            select(StepRun.story_id, func.coalesce(func.sum(StepRun.cost_micros), 0))
            .where(StepRun.story_id.is_not(None))
            .group_by(StepRun.story_id)
        )
        with self.session() as s:
            return {sid: int(total) for sid, total in s.execute(q) if sid}

    def budget_micros(self, story_id: str, default_usd: float) -> int:
        """The story's own budget, or the default from Settings when it has none."""
        story = self.get_story(story_id)
        if story is not None and story.budget_micros is not None:
            return story.budget_micros
        return to_micros(str(default_usd))

    def set_budget(self, story_id: str, micros: int | None) -> Story | None:
        """Set a story's budget; None goes back to the default. None if there's no such story."""
        with self.session() as s:
            story = s.get(Story, story_id)
            if story is not None:
                story.budget_micros = micros
                s.commit()
            return story

    def writer_tokens_per_minute(self) -> dict[str, dict]:
        """For each writer model: average tokens in and out per minute of story, over finished write jobs."""
        q = (
            select(StepRun.model_id, StepRun.job_id, StepRun.meta, Job.params)
            .join(Job, Job.id == StepRun.job_id)
            .where(
                StepRun.stage == "write", StepRun.status == "done", Job.kind == "write", Job.status == "done"
            )
        )
        jobs: dict[tuple[str, str], dict] = {}
        with self.session() as s:
            for model_id, job_id, meta, params in s.execute(q):
                j = jobs.setdefault(
                    (model_id, job_id), {"in": 0, "out": 0, "minutes": (params or {}).get("minutes")}
                )
                j["in"] += (meta or {}).get("tokens_in") or 0
                j["out"] += (meta or {}).get("tokens_out") or 0
        per_model: dict[str, list[dict]] = {}
        for (model_id, _), j in jobs.items():
            if j["minutes"]:
                per_model.setdefault(model_id, []).append(j)
        return {
            m: {
                "in": round(sum(j["in"] / j["minutes"] for j in js) / len(js)),
                "out": round(sum(j["out"] / j["minutes"] for j in js) / len(js)),
                "jobs": len(js),
            }
            for m, js in per_model.items()
        }

    # settings ---------------------------------------------------------------------------------
    def saved_settings(self) -> dict:
        with self.session() as s:
            return {row.key: row.value for row in s.scalars(select(Setting))}

    def set_setting(self, key: str, value) -> None:
        with self.session() as s:
            row = s.get(Setting, key)
            if row:
                row.value, row.updated_at = value, now()
            else:
                s.add(Setting(key=key, value=value))
            s.commit()

    def delete_setting(self, key: str) -> None:
        with self.session() as s:
            if row := s.get(Setting, key):
                s.delete(row)
                s.commit()

    # uploads ----------------------------------------------------------------------------------
    def upload_url(
        self, provider: str, asset: str, min_left: timedelta = timedelta(minutes=10)
    ) -> str | None:
        with self.session() as s:
            row = s.scalars(select(Upload).where(Upload.provider == provider, Upload.asset == asset)).first()
            return row.url if row and row.expires_at - now() >= min_left else None

    def save_upload(self, provider: str, asset: str, url: str, expires_at: datetime) -> None:
        with self.session() as s:
            row = s.scalars(select(Upload).where(Upload.provider == provider, Upload.asset == asset)).first()
            if row:
                row.url, row.expires_at, row.created_at = url, expires_at, now()
            else:
                s.add(Upload(provider=provider, asset=asset, url=url, expires_at=expires_at))
            s.commit()

    # prices -----------------------------------------------------------------------------------
    def latest_prices(self) -> dict[str, ModelPrice]:
        with self.session() as s:
            rows = s.scalars(select(ModelPrice).order_by(ModelPrice.synced_at, ModelPrice.id))
            return {r.model_id: r for r in rows}  # later rows overwrite earlier ones

    def record_price(
        self,
        model_id: str,
        unit: str,
        unit_price: Decimal | str,
        source: str,
        endpoint: str | None = None,
        currency: str = "USD",
        status: str = "active",
    ) -> bool:
        """Add a row if price or status differs from the latest one; returns whether anything changed."""
        price = str(Decimal(str(unit_price)).normalize())
        latest = self.latest_prices().get(model_id)
        if latest and (latest.unit, Decimal(latest.unit_price), latest.currency, latest.status) == (
            unit,
            Decimal(price),
            currency,
            status,
        ):
            return False
        with self.session() as s:
            s.add(
                ModelPrice(
                    model_id=model_id,
                    endpoint=endpoint,
                    unit=unit,
                    unit_price=price,
                    currency=currency,
                    status=status,
                    source=source,
                )
            )
            s.commit()
        return True

    def prices_synced_at(self) -> datetime | None:
        with self.session() as s:
            return s.scalar(
                select(func.max(ModelPrice.synced_at)).where(ModelPrice.source == "fal_pricing_api")
            )
