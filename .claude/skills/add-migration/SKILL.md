---
name: add-migration
description: Change Lanternist's database schema safely, on SQLite and Postgres. Change the model in db.py, hand-finish an Alembic migration with named constraints and a real downgrade, and prove on both databases that existing rows survive. Use for any new or changed table, column, index or constraint.
argument-hint: "<what changes, e.g. 'add stories.cover_asset'>"
---

# Change the schema: $ARGUMENTS

Every start of the app upgrades the user's real library (`~/Lanternist/lanternist.db`), so a
migration runs against their data the next time they open Lanternist. The hosted edition runs the
same migration on Postgres. Read `.claude/rules/database.md` first.

1. **Model.** Change `db.py`: portable types, `_micros` `BigInteger` for money, `String` for prices,
   explicit `nullable`, `ondelete="SET NULL"` for anything that records spend. Give every new
   constraint and index a name (step 3). Add or extend the `Database` method that queries it, with
   `/add-query`; no other module builds that query.
2. **Draft.** Next revision = the highest number in `src/lanternist/migrations/versions/` plus one.
   Let Alembic draft it against a fresh database at head:
   ```bash
   uv run python - <<'EOF'
   import tempfile
   from alembic import command
   from lanternist.db import Database
   d = Database(f"sqlite:///{tempfile.mkdtemp()}/draft.db"); d.migrate()
   command.revision(d.alembic_config(), message="<what>", autogenerate=True, rev_id="NNNN")
   EOF
   ```
3. **Finish it by hand**, in the style of `0002_runs_and_costs.py`:
   - The docstring says what changes.
   - Remove the `Create Date` line and the "auto generated" comments.
   - Use `op.batch_alter_table` for any alter on an existing table (SQLite can't alter in place).
   - Give a new NOT NULL column on a table that has rows a `server_default`, or backfill it.
   - Name everything you create, the same in the model and the migration: `uq_<table>_<columns>`,
     `fk_<table>_<column>`, `ck_<table>_<what>`, `ix_<table>_<columns>`. Postgres names an unnamed
     constraint itself (`story_versions_story_id_version_key`), SQLite leaves it nameless, and a later
     migration can't drop it on both without one name.
   - Write a `downgrade()` that reverses every step in reverse order. `pass` is not a downgrade.
   - Keep the SQL portable: `sa.*` types and `op.*` operations. An `op.execute` holds SQL that both
     databases accept (see `0003`'s downgrade).
   - Never import `lanternist.db` in a migration.
4. **Tests** (`tests/test_data.py`):
   - `test_models_match_the_migrations` must pass on both databases: models and migrations agree,
     and base ↔ head round-trips. On Postgres it also compares constraint names and types, so it
     catches drift SQLite hides.
   - Add `test_migration_NNNN_keeps_rows`. Take the `db` fixture, `command.downgrade` it to the
     previous revision, and insert rows as they look today through `db.engine.begin()` and
     `sqlalchemy.text`. Then upgrade, check that nothing was lost and the new column has its default,
     downgrade, and check again. Written this way it runs on both databases. The older tests that
     write through `sqlite3` are `@pytest.mark.sqlite_only`; don't copy that part.
   - When `~/Lanternist/lanternist.db` exists, `test_migration_on_a_copy_of_the_real_library` runs
     the migration on a copy of it. Make sure it ran (`pytest -rs` lists skips) and passed.
5. **Run it on Postgres.** `scripts/check postgres`, with `LANTERNIST_TEST_DATABASE_URL` set (the
   README's Develop section starts a server in one line). CI runs it too, but a migration that fails
   there is quicker to fix here.
6. **The real library.** Don't migrate `~/Lanternist/lanternist.db` yourself. In the PR, tell the
   user the first start will migrate it, and suggest a backup first:
   `cp ~/Lanternist/lanternist.db ~/Lanternist/backups/lanternist-$(date +%F).db`.
7. **Docs.** Update the data table in the plan (plans/M2_PLAN.md §1.13 or its successor) when it
   describes the schema.
8. Run `scripts/check`.
