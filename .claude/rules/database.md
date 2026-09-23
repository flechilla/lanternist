---
paths:
  - "src/lanternist/db.py"
  - "src/lanternist/migrations/**"
  - "tests/test_data.py"
---

# The database

One `Database(url)`, through SQLAlchemy 2 and Alembic, on two databases:

- **SQLite**, at `~/Lanternist/lanternist.db`: a local library. The user's real library lives in
  it, and `Database.migrate()` upgrades it at every start. A bad migration therefore breaks their
  data the next time they open the app.
- **Postgres**, from `[database] url` or `LANTERNIST_DATABASE_URL`: the hosted edition, with many
  users and several processes at once.

Everything below keeps the same code correct on both. Background: plans/DB_PLAN.md, and
plans/M2_PLAN.md §1.13 for the tables.

## Queries

- **Every query lives in `db.py`**, as a `Database` method. Other modules call those; they don't
  import SQLAlchemy, open a session or touch `db.engine`, and `test_every_query_lives_in_db_py` fails
  if they do. A method opens its own session; one that takes a session is private (`_storyboard`,
  `_save_version`).
- **Portable SQL only.** No SQLite-only SQL, no `sqlite_*` options, no raw `text()` where a
  SQLAlchemy construct exists. Watch the places where the two differ:
  - NULLs sort first on SQLite and last on Postgres, ascending, and the other way round descending.
    Say `.nulls_last()` or `.nulls_first()` when the column can be NULL.
  - `with_for_update()` renders nothing on SQLite, so it can't be what makes a read-then-write safe
    there. Use one statement (`UPDATE … WHERE … RETURNING`, as `claim_job` does) or a unique
    constraint.
  - After a failed statement, Postgres refuses the rest of the transaction until a rollback; SQLite
    carries on. Catch a constraint failure at the commit and roll back, as `_commit_version` does.
  - Window functions (`row_number() over (…)`) and `RETURNING` work on both.
- **A fixed number of queries for a list.** A page that lists rows (the Library, the jobs list)
  costs the same number of queries for 1 row as for 50: join, group or rank in SQL, never a query per
  row in a Python loop. `test_library_queries_do_not_grow_with_stories` shows how to count them.
- **The database settles races.** A check and a write in two statements can interleave with another
  process. Make the write itself fail (a unique constraint, a conditional `UPDATE`), and turn that
  failure into the module's error (`StaleVersion`, then a 409), as `save_edit` and `claim_job` do.
- **Keep writes short**: open a session, write, commit. Remote steps write concurrently from one
  process, so hold no session across an `await` on the network.
- **No query on the event loop where it's hot.** Sessions are synchronous. An async function that
  queries often (the SSE loop) calls `await asyncio.to_thread(db.method, …)`: a query over the
  network to Postgres takes milliseconds, and every other request would wait for them.

## Types and values

- **Portable types only**: `String(n)`, `Integer`, `BigInteger`, `Float`, `Text`, `JSON`, `DateTime`.
  Timestamps are naive UTC from `db.now()`. Ids are `new_id()`: 32 hex characters.
- **JSON columns are `json` on Postgres**, which can't be compared or indexed, and nothing queries
  inside them. The migration that adds the first query needing it moves that column to JSONB.
- **Money** columns end in `_micros` and are `BigInteger`. **Prices** are `String` decimals.
- **Spend history outlives stories.** `step_runs` and anything else that records money use
  `ondelete="SET NULL"`, never `CASCADE`. A delete leans on the foreign keys' `ON DELETE` (SQLite
  honours them through `PRAGMA foreign_keys=ON`); don't delete child rows by hand.
- **The URL can hold a password.** Print it only as `db.shown`. Never put `str(db.url)`, or a
  SQLAlchemy error that may quote it, into a message.

## Changing the schema

Use `/add-migration`. In short:

1. Change the model in `db.py`.
2. Hand-write `migrations/versions/NNNN_<what>.py`. Use `op.batch_alter_table` for any alter
   (SQLite), and write a `downgrade()` that really reverses it.
3. Name every new constraint and index: `uq_<table>_<columns>`, `fk_<table>_<column>`,
   `ck_<table>_<what>`, `ix_<table>_<columns>`. Postgres names an unnamed one itself, and a later
   migration can't drop it without that name. (`story_versions` and `uploads` keep the unnamed unique
   constraints their migrations made.)
4. The migration is a frozen snapshot: it spells out columns with `sa.*` types. It never imports
   `lanternist.db`, because the models will have moved on.
5. `test_models_match_the_migrations` fails if the models and migrations disagree; on Postgres it's
   the stricter check. Add a test that upgrades a database holding the previous revision's rows and
   checks nothing was lost.

## Tests

- The `db` and `client` fixtures give each test a database of its own: a SQLite file, or, with
  `LANTERNIST_TEST_DATABASE_URL` set, a fresh Postgres database. Write tests against those, through
  `Database` methods, so they run on both.
- `@pytest.mark.sqlite_only` is for a test about a local library file (one that writes through
  `sqlite3`, or reads `~/Lanternist`). Nothing else.
- `scripts/check postgres` runs the suite on Postgres, and CI runs it on every pull request.
