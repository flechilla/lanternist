"""The database: users, their stories, the stories' versions, jobs, and what every step cost. Assets
and the step cache stay plain files (see store.py).

Every row a user owns (a story and its versions, a job, a step run, a setting) carries its owner, and
every method that reads or changes one takes the owner first and filters on it: a row that isn't
yours looks exactly like one that doesn't exist. SHARED lists the methods that don't, and why. The
local edition is one user, LOCAL, who owns everything in a library.

Every save of a storyboard is a new version, and a job points at the version it ran on, so a film
always matches the script it came from. `step_runs` logs each step that actually ran (local or
remote, with its cost), and doubles as the record that lets a restart resume a remote request
instead of paying for it twice.

A local library is a SQLite file; the hosted edition runs the same code on Postgres, and the tests
run on both. So everything here is portable: money is integer micro-dollars, prices are decimal
strings, columns use SQLAlchemy's own types, and every query goes through here, so that no other
module needs to know which database it is.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
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
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    func,
    make_url,
    select,
    update,
)
from sqlalchemy.exc import ArgumentError, DBAPIError, IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, aliased, mapped_column, sessionmaker

if TYPE_CHECKING:
    from alembic.config import Config

    from .storyboard import Storyboard


class DatabaseError(Exception):
    pass


URLS = "sqlite:///<file>, or postgresql+psycopg://user:password@host:port/name"  # what Database takes
WHERE = "[database] url in lanternist.toml, or LANTERNIST_DATABASE_URL"  # where the URL comes from
LOCAL = "local"  # the local edition's one user: their id, and what signs them in

# The public methods that don't take the owner first, and why. A test holds every other one to it.
SHARED = {
    # The worker's, on the job it has claimed; a step run is written with the job's owner.
    "claim_job",
    "requeue_running",
    "update_job",
    "spend_by_step",
    "start_run",
    "update_run",
    "get_run",
    # What everyone shares: prices, uploads (a URL is found only by having the file), and the averages
    # estimates are made from, which show no one's rows.
    "latest_prices",
    "record_price",
    "prices_synced_at",
    "upload_url",
    "save_upload",
    "step_seconds",
    "writer_tokens_per_minute",
    # The database itself.
    "migrate",
    "revision",
    "close",
    "alembic_config",
    # Sign-in, which is how the owner is found.
    "user",
    "sign_in",
    "start_session",
    "session_user",
    "end_session",
    "revoke_session",
    "user_updated",
    "user_deleted",
}


class StaleVersion(DatabaseError):
    """A save made from a version that is no longer the story's latest."""

    def __init__(self, base: int):
        super().__init__(f"the story changed since version {base}: reload it, then make the change again")


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex


def to_micros(usd: Decimal | float | str) -> int:
    return int((Decimal(str(usd)) * 1_000_000).to_integral_value())


def to_usd(micros: int | None) -> float | None:
    return None if micros is None else micros / 1_000_000


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("auth_subject", name="uq_users_auth_subject"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # Who signs them in: WorkOS's user id, LOCAL, or fake:<name> in fake mode.
    auth_subject: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | admin
    created_at: Mapped[datetime] = mapped_column(default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class SignedIn(Base):
    """A signed-in browser. The cookie holds a random token and this table only its hash, so a copy of
    the table signs no one in."""

    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the cookie's token
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_sessions_user_id"), index=True
    )
    # WorkOS's own session (the `sid` of its access token): signing out ends it too.
    provider_session: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Story(Base):
    __tablename__ = "stories"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_stories_owner_id"), index=True
    )
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(8), default="en")
    version: Mapped[int] = mapped_column(Integer, default=0)
    budget_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # None: the default
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class StoryVersion(Base):
    __tablename__ = "story_versions"
    # Two saves from the same version can't both become the next one. Unnamed, as migration 0001
    # made it; a new constraint gets a name (see /add-migration).
    __table_args__ = (UniqueConstraint("story_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    storyboard: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_jobs_owner_id"), index=True
    )
    # None for a job that belongs to no story: a voice sample.
    story_id: Mapped[str | None] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # write | rewrite | cast | board | render | sample
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
ACTIVE = ("queued", "running")
OPEN_RUN = ("submitted", "running")


class StepRun(Base):
    """One step that actually ran: the invoice line, the resume record, the estimator's data."""

    __tablename__ = "step_runs"
    __table_args__ = (
        Index("ix_step_runs_key_status", "step_key", "status"),
        Index("ix_step_runs_provider_created", "provider", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # SET NULL, not CASCADE: what was spent stays counted after its story, or its owner, is deleted.
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_step_runs_owner_id"), index=True
    )
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
    """What a user saves on the Settings page; wins over lanternist.toml. Never API keys."""

    __tablename__ = "settings"
    # Named, since migration 0004 builds the table under another name and renames it.
    __table_args__ = (PrimaryKeyConstraint("owner_id", "key", name="pk_settings"),)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_settings_owner_id")
    )
    key: Mapped[str] = mapped_column(String(100))
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


@dataclass
class LibraryRow:
    """A story as the library lists it."""

    story: Story
    storyboard: dict  # the current version's
    film: Job | None  # the latest finished render
    drawn: Job | None  # the latest finished board or render, for the poster
    active: int  # jobs queued or running
    progress: float | None  # how far through the running one is, by time, when it knows


def _sqlite_pragmas(conn, _) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")  # SQLite ignores ON DELETE without it
    cur.close()


def _commit_version(s: Session, base: int) -> None:
    """Commit a new version saved from `base`. Two saves from the same version both make the next one,
    and the story_versions unique constraint refuses the later: StaleVersion, as if it had seen the
    first."""
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise StaleVersion(base) from None


class Database:
    """One database, by its URL: `sqlite:///<file>` for a local library, `postgresql+psycopg://…` for
    the hosted edition."""

    def __init__(self, url: str, pool_size: int | None = None):
        """`pool_size`: the connections kept open to Postgres; None leaves SQLAlchemy's default."""
        try:
            self.url = make_url(url)
        except (ArgumentError, ValueError):  # ValueError: a port that isn't a number
            raise DatabaseError(f"can't read the database URL: write it as {URLS}, in {WHERE}") from None
        if self.url.drivername not in ("sqlite", "postgresql+psycopg"):
            raise DatabaseError(
                f"Lanternist can't use a {self.url.drivername} database URL: write it as {URLS}, in {WHERE}"
            )
        try:
            if self.url.drivername == "sqlite":
                Path(self.url.database or "").parent.mkdir(parents=True, exist_ok=True)
                self.engine = create_engine(self.url, connect_args={"check_same_thread": False})
                event.listen(self.engine, "connect", _sqlite_pragmas)
            else:
                # Managed Postgres closes idle connections, so each one is tested before use.
                pool = {} if pool_size is None else {"pool_size": pool_size}
                self.engine = create_engine(self.url, pool_pre_ping=True, **pool)
        except ImportError:
            raise DatabaseError(
                f"no driver for {self.url.drivername}: install the postgres extra "
                "(`uv sync --extra postgres`, or `pip install 'lanternist[postgres]'`)"
            ) from None
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def close(self) -> None:
        """Close the connections this database holds open, for one made for a single look."""
        self.engine.dispose()

    @property
    def shown(self) -> str:
        """The URL as it may be printed: without its password, which libpq also takes as a parameter."""
        secret = {k: "***" for k in self.url.query if "password" in k}
        return self.url.update_query_dict(secret).render_as_string(hide_password=True)

    def alembic_config(self) -> "Config":
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        # The config interpolates %, which a URL-encoded password can hold.
        cfg.set_main_option(
            "sqlalchemy.url", self.url.render_as_string(hide_password=False).replace("%", "%%")
        )
        return cfg

    def migrate(self) -> None:
        """Upgrade to the latest migration; DatabaseError when the database doesn't answer."""
        from alembic import command

        self.revision()  # one sentence for a database that doesn't answer, not Alembic's traceback
        command.upgrade(self.alembic_config(), "head")

    def revision(self) -> str | None:
        """The migration the database is at, None before the first; DatabaseError when it doesn't answer."""
        from alembic.runtime.migration import MigrationContext

        try:
            with self.engine.connect() as conn:
                return MigrationContext.configure(conn).get_current_revision()
        except DBAPIError as e:  # the driver's own words, without SQLAlchemy's wrapping
            raise DatabaseError(
                f"the database at {self.shown} doesn't answer ({str(e.orig).splitlines()[0]}): start it, "
                f"or fix {WHERE}"
            ) from None

    # users ------------------------------------------------------------------------------------
    def user(self, user_id: str) -> User | None:
        with self.session() as s:
            return s.get(User, user_id)

    def sign_in(self, subject: str, email: str | None) -> User:
        """The user the sign-in provider knows as `subject`, made at their first sign-in, with the email
        it gave this time."""
        with self.session() as s:
            user = s.scalars(select(User).where(User.auth_subject == subject)).one_or_none()
            if user is None:
                user = User(auth_subject=subject, email=email)
                s.add(user)
                try:
                    s.commit()
                except IntegrityError:  # their first sign-in, twice at once: the other one made them
                    s.rollback()
                    return self.sign_in(subject, email)
            elif email and user.email != email:
                user.email = email
                s.commit()
            return user

    def start_session(self, user_id: str, token_hash: str, provider_session: str | None, days: int) -> None:
        """A signed-in browser, for `days`. The user's expired sessions go at the same time."""
        with self.session() as s:
            s.execute(delete(SignedIn).where(SignedIn.user_id == user_id, SignedIn.expires_at <= now()))
            s.add(
                SignedIn(
                    id=token_hash,
                    user_id=user_id,
                    provider_session=provider_session,
                    expires_at=now() + timedelta(days=days),
                )
            )
            s.commit()

    def session_user(self, token_hash: str) -> User | None:
        """Who a session signs in: None when it has expired, or ended, or their account was deleted."""
        q = (
            select(User)
            .join(SignedIn, SignedIn.user_id == User.id)
            .where(SignedIn.id == token_hash, SignedIn.expires_at > now(), User.deleted_at.is_(None))
        )
        with self.session() as s:
            return s.scalars(q).one_or_none()

    def end_session(self, token_hash: str) -> str | None:
        """Sign a browser out; returns the provider's session, to end that too."""
        q = delete(SignedIn).where(SignedIn.id == token_hash).returning(SignedIn.provider_session)
        with self.session() as s:
            ended = s.scalars(q).one_or_none()
            s.commit()
            return ended

    def revoke_session(self, provider_session: str) -> None:
        """The provider ended one of its sessions: end ours with it."""
        with self.session() as s:
            s.execute(delete(SignedIn).where(SignedIn.provider_session == provider_session))
            s.commit()

    def user_updated(self, subject: str, email: str | None) -> None:
        with self.session() as s:
            s.execute(update(User).where(User.auth_subject == subject).values(email=email))
            s.commit()

    def user_deleted(self, subject: str) -> None:
        """The provider deleted the account: nobody signs in as them again. Their stories and files stay
        until the account deletion of HOSTED_PLAN Phase I removes them."""
        with self.session() as s:
            user = s.scalars(select(User).where(User.auth_subject == subject)).one_or_none()
            if user is None:
                return
            user.deleted_at = user.deleted_at or now()
            s.execute(delete(SignedIn).where(SignedIn.user_id == user.id))
            s.commit()

    def _story(self, s: Session, owner: str, story_id: str) -> Story | None:
        """The owner's story; None for another's, exactly as for one that doesn't exist."""
        story = s.get(Story, story_id)
        return story if story is not None and story.owner_id == owner else None

    def _job(self, s: Session, owner: str, job_id: str) -> Job | None:
        job = s.get(Job, job_id)
        return job if job is not None and job.owner_id == owner else None

    # stories ----------------------------------------------------------------------------------
    def storyboard(self, owner: str, story_id: str, version: int | None = None) -> tuple[Story, StoryVersion]:
        """A story and one of its versions, the latest by default; KeyError when either is missing."""
        with self.session() as s:
            return self._storyboard(s, owner, story_id, version)

    def _storyboard(
        self, s: Session, owner: str, story_id: str, version: int | None = None
    ) -> tuple[Story, StoryVersion]:
        story = self._story(s, owner, story_id)
        if story is None:
            raise KeyError(story_id)
        v = version or story.version
        row = s.scalars(select(StoryVersion).filter_by(story_id=story_id, version=v)).one_or_none()
        if row is None:
            raise KeyError(f"{story_id} v{v}")
        return story, row

    def change_story(
        self, owner: str, story_id: str, change: "Callable[[Storyboard], str | None]", note: str = ""
    ) -> int | None:
        """Apply `change` to the story's latest version and save the result as its next, noted with what
        `change` returns (what it found to change), else `note`; returns its number, or None when the
        change left the story as it was. When another save takes that number first, the change is
        applied once more, to the version that save made: so `change` may run twice, and what it does
        must depend only on the storyboard it's given."""
        try:
            return self._change_story(owner, story_id, change, note)
        except StaleVersion:
            return self._change_story(owner, story_id, change, note)

    def _change_story(
        self, owner: str, story_id: str, change: "Callable[[Storyboard], str | None]", note: str
    ) -> int | None:
        from .storyboard import Storyboard

        with self.session() as s:
            story, row = self._storyboard(s, owner, story_id)
            sb = Storyboard.model_validate(row.storyboard)
            was = sb.model_dump()
            said = change(sb)
            if sb.model_dump() == was:
                return None
            new = self._save_version(s, story, sb.model_dump(), note=said or note)
            _commit_version(s, row.version)
            return new.version

    def save_edit(
        self, owner: str, story_id: str, storyboard: dict, base_version: int, note: str
    ) -> tuple[Story, StoryVersion]:
        """Save an edit made from `base_version` as the story's next version. StaleVersion when the story
        has moved on since, even by a save landing at the same moment; KeyError when it's gone."""
        with self.session() as s:
            story = self._story(s, owner, story_id)
            if story is None:
                raise KeyError(story_id)
            if story.version != base_version:
                raise StaleVersion(base_version)
            row = self._save_version(s, story, storyboard, note=note)
            _commit_version(s, base_version)
            return story, row

    def create_story(self, owner: str, title: str, language: str, storyboard: dict | None = None) -> Story:
        """A new story; with a storyboard (an import) it starts at version 1, else at 0 until it's written."""
        from .storyboard import slugify

        with self.session() as s:
            story = Story(owner_id=owner, slug=slugify(title), title=title, language=language, version=0)
            s.add(story)
            s.flush()
            if storyboard is not None:
                self._save_version(s, story, storyboard, note="imported")
            s.commit()
            return story

    def library(self, owner: str) -> list[LibraryRow]:
        """Every story of the owner's, newest edit first, with what the library shows of it. Four queries
        however many stories there are, since the Library page asks every few seconds."""
        current = (
            select(Story, StoryVersion.storyboard)
            .outerjoin(
                StoryVersion, (StoryVersion.story_id == Story.id) & (StoryVersion.version == Story.version)
            )
            .where(Story.owner_id == owner)
            .order_by(Story.updated_at.desc())
        )
        newest = Job.finished_at.desc().nulls_last()  # Postgres puts NULLs first when descending
        ranked = (
            select(
                Job,
                func.row_number().over(partition_by=Job.story_id, order_by=newest).label("drawn"),
                func.row_number()
                .over(partition_by=(Job.story_id, Job.kind), order_by=newest)
                .label("of_kind"),
            )
            .where(Job.owner_id == owner, Job.status == "done", Job.kind.in_(("board", "render")))
            .subquery()
        )
        finished = select(aliased(Job, ranked), ranked.c.drawn, ranked.c.of_kind).where(
            (ranked.c.drawn == 1) | ((ranked.c.kind == "render") & (ranked.c.of_kind == 1))
        )
        active = (
            select(Job.story_id, func.count())
            .where(Job.owner_id == owner, Job.status.in_(ACTIVE))
            .group_by(Job.story_id)
        )
        running = select(Job.story_id, Job.progress).where(Job.owner_id == owner, Job.status == "running")
        with self.session() as s:
            films: dict[str, Job] = {}
            drawn: dict[str, Job] = {}
            for job, first, first_of_kind in s.execute(finished).tuples():
                if first == 1 and job.story_id:
                    drawn[job.story_id] = job
                if job.kind == "render" and first_of_kind == 1 and job.story_id:
                    films[job.story_id] = job
            counts = dict(s.execute(active).tuples().all())
            fractions = {
                sid: (progress or {}).get("fraction") for sid, progress in s.execute(running).tuples()
            }
            return [
                LibraryRow(
                    st,
                    sb or {},
                    films.get(st.id),
                    drawn.get(st.id),
                    counts.get(st.id, 0),
                    fractions.get(st.id),
                )
                for st, sb in s.execute(current).tuples()
            ]

    def get_story(self, owner: str, story_id: str) -> Story | None:
        with self.session() as s:
            return self._story(s, owner, story_id)

    def get_version(self, owner: str, story_id: str, version: int) -> StoryVersion | None:
        q = (
            select(StoryVersion)
            .join(Story, Story.id == StoryVersion.story_id)
            .where(
                Story.owner_id == owner, StoryVersion.story_id == story_id, StoryVersion.version == version
            )
        )
        with self.session() as s:
            return s.scalars(q).one_or_none()

    def story_versions(self, owner: str, story_id: str) -> list[StoryVersion]:
        """Newest first."""
        q = (
            select(StoryVersion)
            .join(Story, Story.id == StoryVersion.story_id)
            .where(Story.owner_id == owner, StoryVersion.story_id == story_id)
            .order_by(StoryVersion.version.desc())
        )
        with self.session() as s:
            return list(s.scalars(q))

    def story_jobs(self, owner: str, story_id: str, limit: int) -> list[Job]:
        """The newest `limit` jobs of a story, newest first."""
        q = (
            select(Job)
            .where(Job.owner_id == owner, Job.story_id == story_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        with self.session() as s:
            return list(s.scalars(q))

    def delete_story(self, owner: str, story_id: str) -> bool:
        """Delete a story, and with it (ON DELETE CASCADE) its versions and jobs; what it cost stays
        counted (SET NULL). False if there was no such story."""
        with self.session() as s:
            story = self._story(s, owner, story_id)
            if story is None:
                return False
            s.delete(story)
            s.commit()
            return True

    def _save_version(self, s: Session, story: Story, storyboard: dict, note: str = "") -> StoryVersion:
        from .storyboard import slugify

        story.version += 1
        story.title = storyboard.get("title", story.title)
        story.slug = slugify(story.title)
        story.language = storyboard.get("language", story.language)
        story.updated_at = now()
        row = StoryVersion(story_id=story.id, version=story.version, storyboard=storyboard, note=note)
        s.add(row)
        return row

    def add_version(self, owner: str, story_id: str, storyboard: dict, note: str = "") -> int:
        """Save a storyboard as the story's next version, whichever that is by then: once more when
        another save takes the number first. Returns the version."""
        try:
            return self._add_version(owner, story_id, storyboard, note)
        except StaleVersion:
            return self._add_version(owner, story_id, storyboard, note)

    def _add_version(self, owner: str, story_id: str, storyboard: dict, note: str) -> int:
        with self.session() as s:
            story = self._story(s, owner, story_id)
            if story is None:
                raise KeyError(story_id)  # deleted while a job was writing it
            base = story.version
            row = self._save_version(s, story, storyboard, note=note)
            _commit_version(s, base)
            return row.version

    # jobs -------------------------------------------------------------------------------------
    def add_job(
        self,
        owner: str,
        story_id: str | None,
        kind: str,
        version: int | None,
        params: dict,
        estimate: dict | None,
    ) -> Job:
        """A queued job of the owner's, on one of their stories (the caller has found it), or on none."""
        with self.session() as s:
            job = Job(
                owner_id=owner,
                story_id=story_id,
                kind=kind,
                version=version,
                params=params,
                progress={},
                estimate=estimate,
            )
            s.add(job)
            s.commit()
            return job

    def requeue_running(self) -> None:
        """Put every job a stopped server left running back in the queue."""
        with self.session() as s:
            for job in s.scalars(select(Job).where(Job.status == "running")):
                job.status = "queued"
            s.commit()

    def cancel_queued(self, owner: str, job_id: str) -> bool:
        """Cancel a job that hasn't started; False if it has, or is gone."""
        with self.session() as s:
            job = self._job(s, owner, job_id)
            if job is None or job.status != "queued":
                return False
            job.status, job.finished_at = "cancelled", now()
            s.commit()
            return True

    def claim_job(self, fast_kinds: tuple[str, ...], fast: bool) -> Job | None:
        """Mark the oldest queued job of one lane (the fast kinds, or everything else) running, and return
        it. One statement, so two workers asking at once never get the same job: on Postgres each skips
        the row the other has locked, and SQLite runs one write at a time."""
        queued = aliased(Job)  # the subquery reads the table the statement updates
        lane = queued.kind.in_(fast_kinds) if fast else queued.kind.not_in(fast_kinds)
        oldest = (
            select(queued.id)
            .where(queued.status == "queued", lane)
            .order_by(queued.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        claim = (
            update(Job)
            .where(Job.id == oldest)
            .values(status="running", started_at=now(), error=None)
            .returning(Job)
        )
        with self.session() as s:
            job = s.scalars(claim).one_or_none()
            s.commit()
            return job

    def get_job(self, owner: str, job_id: str) -> Job | None:
        with self.session() as s:
            return self._job(s, owner, job_id)

    def jobs(self, owner: str, active: bool, limit: int) -> list[Job]:
        """The owner's newest `limit` jobs, newest first; with `active`, only those queued or running."""
        q = select(Job).where(Job.owner_id == owner).order_by(Job.created_at.desc()).limit(limit)
        if active:
            q = q.where(Job.status.in_(ACTIVE))
        with self.session() as s:
            return list(s.scalars(q))

    def active_jobs(self, owner: str, story_id: str) -> list[str]:
        """The ids of a story's jobs that are queued or running."""
        q = select(Job.id).where(Job.owner_id == owner, Job.story_id == story_id, Job.status.in_(ACTIVE))
        with self.session() as s:
            return list(s.scalars(q))

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

    def open_run(self, owner: str, step_key: str, provider: str) -> StepRun | None:
        """The owner's newest submitted or running request for this step, if a restart left one behind.
        Another user's request for the same step is theirs: they paid for it."""
        with self.session() as s:
            return s.scalars(
                select(StepRun)
                .where(
                    StepRun.owner_id == owner,
                    StepRun.step_key == step_key,
                    StepRun.provider == provider,
                    StepRun.status.in_(OPEN_RUN),
                )
                .order_by(StepRun.created_at.desc())
            ).first()

    def spend_micros(
        self,
        owner: str,
        story_id: str | None = None,
        job_id: str | None = None,
        since: datetime | None = None,
        stage: str | None = None,
    ) -> int:
        """What the owner has spent: on a story, a job or a stage, or since a time."""
        q = select(func.coalesce(func.sum(StepRun.cost_micros), 0)).where(StepRun.owner_id == owner)
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

    def step_seconds(self, stage: str, model_id: str, limit: int) -> list[float]:
        """How long a model's most recent steps in a stage took, end to end, newest first."""
        q = (
            select(func.coalesce(StepRun.wall_seconds, StepRun.gpu_seconds))
            .where(StepRun.stage == stage, StepRun.model_id == model_id, StepRun.status == "done")
            .where(func.coalesce(StepRun.wall_seconds, StepRun.gpu_seconds).is_not(None))
            .order_by(StepRun.created_at.desc())
            .limit(limit)
        )
        with self.session() as s:
            return [float(secs) for secs in s.scalars(q)]

    def spend_by_step(self, job_id: str) -> dict[tuple[str, int | None], int]:
        """What a job has paid for, by stage and scene: only steps with a cost, so no local ones."""
        q = (
            select(StepRun.stage, StepRun.scene, func.sum(StepRun.cost_micros))
            .where(StepRun.job_id == job_id, StepRun.cost_micros.is_not(None))
            .group_by(StepRun.stage, StepRun.scene)
        )
        with self.session() as s:
            return {(stage, scene): int(micros) for stage, scene, micros in s.execute(q)}

    def spend_by_story(self, owner: str) -> dict[str, int]:
        """What each of the owner's stories has cost so far, in one query, for the library."""
        q = (
            select(StepRun.story_id, func.coalesce(func.sum(StepRun.cost_micros), 0))
            .where(StepRun.owner_id == owner, StepRun.story_id.is_not(None))
            .group_by(StepRun.story_id)
        )
        with self.session() as s:
            return {sid: int(total) for sid, total in s.execute(q) if sid}

    def budget_micros(self, owner: str, story_id: str, default_usd: float) -> int:
        """The story's own budget, or the default from Settings when it has none."""
        story = self.get_story(owner, story_id)
        if story is not None and story.budget_micros is not None:
            return story.budget_micros
        return to_micros(str(default_usd))

    def set_budget(self, owner: str, story_id: str, micros: int | None) -> Story | None:
        """Set a story's budget; None goes back to the default. None if there's no such story."""
        with self.session() as s:
            story = self._story(s, owner, story_id)
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
    def saved_settings(self, owner: str) -> dict:
        with self.session() as s:
            return {row.key: row.value for row in s.scalars(select(Setting).where(Setting.owner_id == owner))}

    def set_setting(self, owner: str, key: str, value) -> None:
        with self.session() as s:
            row = s.get(Setting, (owner, key))
            if row:
                row.value, row.updated_at = value, now()
            else:
                s.add(Setting(owner_id=owner, key=key, value=value))
            s.commit()

    def delete_setting(self, owner: str, key: str) -> None:
        with self.session() as s:
            if row := s.get(Setting, (owner, key)):
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
