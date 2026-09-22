---
paths:
  - "src/lanternist/db.py"
  - "src/lanternist/migrations/**"
---

# The database

SQLite at `~/Lanternist/lanternist.db`, through SQLAlchemy 2 and Alembic. The user's real library
lives in it, and `Database.migrate()` upgrades it at every start. A bad migration therefore breaks
their data the next time they open the app. Background: M2_PLAN.md §1.13.

- **Every query lives in `db.py`**, as a `Database` method or on a model. Other modules call those;
  they don't build queries of their own. `api/app.py` still queries inline: move a query into
  `db.py` when you touch the code around it.
- **Portable types only**: `String(n)`, `Integer`, `BigInteger`, `Float`, `Text`, `JSON`, `DateTime`.
  No SQLite-only SQL, no `sqlite_*` options. Timestamps are naive UTC from `db.now()`.
- **Money** columns end in `_micros` and are `BigInteger`. **Prices** are `String` decimals.
- **Spend history outlives stories.** `step_runs` and anything else that records money use
  `ondelete="SET NULL"`, never `CASCADE`.
- Keep writes short: open a session, write, commit. Remote steps write concurrently from one process,
  so hold no session across an `await` on the network.

## Changing the schema

Use `/add-migration`. In short:

1. Change the model in `db.py`.
2. Hand-write `migrations/versions/NNNN_<what>.py`. Use `op.batch_alter_table` for any alter
   (SQLite), and write a `downgrade()` that really reverses it.
3. The migration is a frozen snapshot: it spells out columns with `sa.*` types. It never imports
   `lanternist.db`, because the models will have moved on.
4. `test_models_match_the_migrations` fails if the models and migrations disagree. Add a test that
   upgrades a database holding the previous revision's rows and checks nothing was lost (see
   `test_migration_keeps_mvp_rows`).
