# Lanternist: the database, ready for Postgres

> **Status, 22 Sep 2026: built, in one pull request (`feat/postgres`) rather than the two below.** This is Phase A of `HOSTED_PLAN.md`. It needs no product decision, and it changes nothing a local user sees. It adds no migration, so a local library needs no backup. §3 lists where the build departed from this design.
>
> **Measured before writing.** The whole test suite ran against a throwaway Postgres 17, with every `Database` pointed at a fresh database of its own:
> - 225 of the 228 tests passed unchanged.
> - It took the same time as on SQLite: 85 s, against 90 s.
> - Every migration upgraded to head, downgraded to base and upgraded again.
>
> Of the three failures:
> - Two are migration tests that write rows through `sqlite3` on purpose, because they test the upgrade of a local library.
> - The third is real: a constraint the migrations create but the models don't declare. SQLite had hidden it (§1.3).

**Goal:** the same code runs on SQLite (a local library) and on Postgres (the hosted edition), and CI proves it on both. Every query lives in `db.py`, so the next phase can scope each one to the user who owns the row, in one file.

Definition of done:

1. A test fails if any module other than `db.py` builds a query or opens a session.
2. `scripts/check` passes on SQLite, as today. With `LANTERNIST_TEST_DATABASE_URL` set, `scripts/check postgres` runs the suite on Postgres, and CI runs both on every pull request.
3. `LANTERNIST_DATABASE_URL=postgresql+psycopg://… LANTERNIST_FAKE_ENGINES=1 lanternist serve` runs the whole app on Postgres: write, board, render, cancel and restart.
4. Two workers asking for the next job at the same moment never get the same one (tested on Postgres).
5. The Library costs the same number of queries for 1 story as for 50.

---

## 0. Where we are

- **`db.py`:** 7 tables and about 35 `Database` methods. The types are portable, money is integer micro-dollars, and timestamps are naive UTC.
- **Queries built outside `db.py`, in 7 places** (CLAUDE.md lists this as known duplication):
  - `api/app.py`: `_get`, `save_story`, `delete_story`, `list_jobs`, `get_job` and the SSE loop in `job_events`.
  - `jobs.py`: `execute`, which opens a session to call `db.storyboard(s, …)`.
- **Queries on the event loop.** The SSE loop reads the job row every 0.5 s for each open stream, inside an async function. On a local file a query takes microseconds. Over the network to Postgres it takes 1–5 ms, and every other request the process serves waits for it.
- **The Library.** `library()` runs 4 queries per story, and the Library page polls it every 4 s.
- **The queue.** `next_job` finds a job and `update_job` marks it running, in two steps. That's safe with one worker, and only with one.
- **Ids.** 12 hex characters (48 bits) in `String(32)` columns.

## 1. Design

### 1.1 Every query in `db.py`

| Today | Becomes |
|---|---|
| `app._get` and `Runner.execute` open a session only to pass it to `db.storyboard(s, …)` | `db.storyboard(story_id, version=None) -> (Story, StoryVersion)` opens its own session. The version that takes a session becomes the private `_storyboard(s, …)`, for `change_story`. |
| `save_story` checks `base_version` and saves, in a session the route holds | `db.save_edit(story_id, storyboard, base_version, note) -> (Story, StoryVersion)`. It raises `StaleVersion(now)`, which the route turns into today's 409. `renumber()` stays in the route, because it's storyboard logic. |
| `delete_story` walks the jobs, cancels the running ones, and deletes jobs, versions and the story | `db.active_jobs(story_id) -> list[str]`: the route cancels each through the runner. Then `db.delete_story(story_id) -> bool` deletes the story row. Its jobs and versions go through their `ON DELETE CASCADE` foreign keys, which SQLite honours through `PRAGMA foreign_keys=ON` and Postgres always does. Its `step_runs` stay (`SET NULL`), as `test_deleting_a_story_keeps_what_it_cost` already checks. |
| `list_jobs` builds a query | `db.jobs(active: bool, limit: int)` |
| `get_job` and the SSE loop call `s.get(Job, …)` | `db.get_job(job_id)` |

- **A test keeps it that way.** `test_every_query_lives_in_db_py` fails when a module under `src/lanternist`, other than `db.py` and `migrations/`, imports `sqlalchemy` or calls `.session()` on the database. Today only `db.py` imports SQLAlchemy, so the rule becomes a gate at no cost.
- **Docs.** In the same PR, delete the "`api/app.py` builds queries inline" line from CLAUDE.md, and the matching sentence from `.claude/rules/database.md`.

### 1.2 A database URL

- **Config.** Add `[database] url`. Empty means `sqlite:///<library>/lanternist.db`, which is today's file. `LANTERNIST_DATABASE_URL` overrides it; `config.py` is where every `LANTERNIST_*` variable is read. The hosted edition passes the URL from its secret store.
- **`Database(url)`** in place of `Database(path)`. Three callers change: `api/app.py`, `cli.py` and the test fixtures.
  - SQLite keeps today's pragmas and `check_same_thread`.
  - Postgres gets `pool_pre_ping=True` (managed Postgres closes idle connections) and `[database] pool_size`, default 5.
- **Driver.** psycopg 3 (`psycopg[binary]`), as an optional extra `lanternist[postgres]`, and in the dev group so tests can use it. A local install doesn't carry it.
- **Password.** The URL can hold a password. Whatever prints the URL (the doctor, the CLI, errors) prints `make_url(url).render_as_string(hide_password=True)`. Invariant 4 is about provider keys, but a database password deserves the same care.
- **Doctor.** A database row: the dialect, the revision it's at, and whether the database answers.
- **Example config.** `lanternist.example.toml` documents `[database]`.

### 1.3 The drift Postgres found

- **The constraint.** Migration `0001` creates `UniqueConstraint("story_id", "version")` on `story_versions`, but `StoryVersion` doesn't declare it. Alembic's check can't see the difference on SQLite; on Postgres it reports it. Fix: declare the constraint on the model. Every database already has it, so no migration is needed.
- **The race it guards.** Two saves of the same story at once (two tabs, or an edit while a job saves a version) both read version N and write N+1. `save_story` compares `base_version`, but the check and the write aren't one step. With the constraint, the second write fails instead of leaving two versions N+1.
  - The edit route turns that failure into the same 409 as a stale version.
  - `change_story` (re-rolls and new takes) tries once more on a conflict. It re-reads the latest version, so applying the change again is correct.
- **Name every constraint from now on** (`uq_<table>_<columns>`, `fk_…`, `ck_…`, as indexes are already named `ix_…`). Postgres names unnamed constraints itself, and a later migration that drops one needs its name. Add this to the `/add-migration` skill.

### 1.4 Claiming a job

- **`db.claim_job(fast_kinds, fast) -> Job | None`.** In one transaction, it selects the oldest queued job of the lane `FOR UPDATE SKIP LOCKED`, marks it running with its `started_at`, and commits.
  - On Postgres, two workers skip each other's row.
  - On SQLite, `with_for_update` renders nothing, and SQLite's single writer makes the claim atomic anyway.
- **`Runner.loop`** calls it in place of `next_job` and then `update_job(status="running")`. With one worker, nothing changes.
- **No new index.** The claim reads only queued rows, which `ix_jobs_status` already finds.
- **Left for hosted Phase D (workers):**
  - Heartbeats.
  - Re-queueing a dead worker's jobs. Today's `requeue_running` at start would take a live worker's jobs.
  - Cancelling a job that runs in another process.

### 1.5 No query on the API's event loop

- The SSE loop reads the job through `await asyncio.to_thread(db.get_job, job_id)`. That's the hot path: every viewer of every running job, twice a second.
- **Left as they are:**
  - Async routes that read settings once per call (`/api/models`, `/api/doctor`, `/api/providers`). They're rare.
  - The runner's own writes. They're throttled to four a second, and in the hosted edition the runner has a process of its own.
- Sessions stay synchronous. Async SQLAlchemy would touch every query to fix one loop.

### 1.6 The Library in a fixed number of queries

`library()` becomes four queries, however many stories there are:

1. Stories joined to their current version.
2. Each story's latest finished render, and latest finished board or render (for the poster), through `row_number() over (partition by …)`. SQLite has had window functions since 3.25.
3. The count of queued and running jobs per story.
4. The running jobs' `progress`, for the ring.

`test_library_queries_do_not_grow_with_stories` counts statements through SQLAlchemy's `before_cursor_execute` event, with 1 story and with 20.

### 1.7 Longer ids

- `new_id()` returns all 32 hex characters of `uuid4().hex`, which the `String(32)` columns already hold.
- Why: 48 bits are plenty for one person's library. For a hosted jobs table of a million rows, the chance that two ids ever match is about 1 in 560. A clash would only fail an insert, not mix two users' rows, but it's a free fix.
- Existing ids stay as they are, and nothing in the web app depends on their length (checked).

### 1.8 Tests on both databases

- **The switch.** When `LANTERNIST_TEST_DATABASE_URL` is set (an admin URL to a Postgres server), the `db` and `client` fixtures give each test a fresh Postgres database. Each one is cloned from a template migrated once per session (`CREATE DATABASE t_<id> TEMPLATE lanternist_template`) and dropped after the test. Unset, tests use SQLite files, as today.
- **The `client` fixture** already writes a `lanternist.toml`; it adds `[database] url`.
- **SQLite-only tests.** Three tests check the upgrade of a local library file, and stay on SQLite only (`@pytest.mark.sqlite_only`, skipped on Postgres):
  - `test_migration_keeps_mvp_rows`
  - `test_migration_0003_…`
  - `test_migration_on_a_copy_of_the_real_library`
- **`test_models_match_the_migrations`** runs on both. On Postgres it's the stricter check, as §1.3 showed.
- **`scripts/check postgres`** runs the tests only, since format, lint and types don't depend on the database. It needs the variable set.
- **CI.** A `python-postgres` job with a `postgres:17` service runs `scripts/check postgres`, in parallel with the others. The suite takes about 90 s either way.
- **Locally.** README's Develop section gets the one-line `docker run … postgres:17`.
- **New tests:**
  - `test_every_query_lives_in_db_py` (§1.1)
  - `test_claim_gives_each_worker_its_own_job`: two threads claim at once and get different jobs.
  - `test_library_queries_do_not_grow_with_stories` (§1.6)
  - `test_two_saves_of_one_version_conflict`: the second gets a 409.
  - `test_deleting_a_story_deletes_its_versions_and_jobs`: the cascade, on both databases.
  - `test_the_database_password_is_never_printed`

### 1.9 Out of scope

- **Users and `owner_id`:** hosted Phase B.
- **Moving the step cache from files into the database:** hosted Phase C, with R2.
- **Heartbeats, re-queueing across workers and cancelling across processes:** hosted Phase D.
- **JSONB.** On Postgres, the JSON columns become `json`, which can't be compared or indexed. Nothing queries inside them today. A column moves to JSONB in the migration that adds the first query needing it.
- **LISTEN/NOTIFY for the SSE.** Polling one row by its primary key twice a second per viewer is fine at this scale.
- **Copying a local library into a hosted database.**

---

## 2. Steps

Two pull requests. The first changes no behaviour; the second adds Postgres.

### PR 1 `chore/queries-in-db` (≈1 day)

- [x] Move the 7 inline queries into `db.py` (§1.1), with `test_every_query_lives_in_db_py`. Update CLAUDE.md and the database rule.
- [x] Declare the unique constraint. Add the 409 on a conflicting save, the one retry in `change_story`, and the naming rule in `/add-migration` (§1.3).
- [x] `library()` in four queries (§1.6).

### PR 2 `feat/postgres` (≈1.5 days)

- [x] `[database] url`, `Database(url)`, the psycopg extra, pool settings, the hidden password and the doctor row (§1.2).
- [x] `claim_job` (§1.4).
- [x] The SSE loop off the event loop (§1.5).
- [x] 32-character ids (§1.7).
- [x] The fixtures on both databases, `scripts/check postgres`, the CI job and the README (§1.8).
- [x] Run the definition of done at the top by hand on Postgres in fake mode: write, board, render, cancel, and restart during a render. A render killed with SIGKILL was re-queued at the next start and finished from the cache. Deleting a story kept its 16 `step_runs` rows, with no story. The doctor printed the URL with `***` for the password.

**Exit:**
- [x] Items 1–5 of the definition of done. The suite passes on both databases: 243 tests on SQLite (78 s), and 240 on Postgres (73 s) with the 3 `sqlite_only` ones skipped.
- [x] The local library opens exactly as before. `~/Lanternist` was opened read-only: 4 stories at revision 0003, `library()` in 7 ms, the old 12-character ids intact. `test_migration_on_a_copy_of_the_real_library` ran on a copy of it. No real story was rendered, which would take the GPU. Step keys read nothing from the database, and the step-key tests pass.

## 3. Where the build departed from the design

- **One pull request**, at the user's request, with the skills for the data layer: `/add-query` (new), `/add-migration` (named constraints, tests on both databases), `/check postgres`, and a database section in `/self-review` and the PR template.
- **The claim is one statement** (§1.4): `UPDATE jobs … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED) RETURNING`. With a select and then an update, SQLite wouldn't be safe: pysqlite runs the select outside a transaction, so two threads could read the same job before either one writes. `test_claim_gives_each_worker_its_own_job` fails on Postgres when the lock is removed. The runner's `run()` now takes the job it claimed.
- **The constraint stays unnamed on the model** (§1.3), as migration 0001 made it. A name on the model would differ from the one Postgres gave it, and from SQLite's none. New constraints get names.
- **`add_version` retries once too** (§1.3 named "an edit while a job saves a version"). A job's write or rewrite then lands as the version after the edit, instead of failing on the constraint. The review found that a retried change runs its callback twice, so `keep_redraws` now starts its list over on each run.
- **`migrate()` checks first that the database answers**, so a server that's down gets one sentence rather than Alembic's traceback. `lanternist doctor` runs every other check even then. `Database` accepts only `sqlite:///…` and `postgresql+psycopg://…`, and says so for any other URL.
- **`StaleVersion` carries only the version the save started from.** An exception handler in `api/app.py` turns it into the 409, so a re-roll or new take that conflicts twice also gets a 409 rather than a 500.
- **Two tests depended on the SQLite fixture making the library folder.** Postgres showed it, and they now make the folder themselves.
