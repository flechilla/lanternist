---
name: add-migration
description: Change Lanternist's database schema safely. Change the model in db.py, hand-finish an Alembic migration with a real downgrade, and prove with tests that existing rows survive. Use for any new or changed table, column, index or constraint.
argument-hint: "<what changes, e.g. 'add stories.cover_asset'>"
---

# Change the schema: $ARGUMENTS

Every start of the app upgrades the user's real library (`~/Lanternist/lanternist.db`), so a
migration runs against their data the next time they open Lanternist. Read
`.claude/rules/database.md` first.

1. **Model.** Change `db.py`: portable types, `_micros` `BigInteger` for money, `String` for prices,
   explicit `nullable`, `ondelete="SET NULL"` for anything that records spend. Add or extend the
   `Database` method that queries it; no other module builds that query.
2. **Draft.** Next revision = the highest number in `src/lanternist/migrations/versions/` plus one.
   Let Alembic draft it against a fresh database at head:
   ```bash
   uv run python - <<'EOF'
   import pathlib, tempfile
   from alembic import command
   from lanternist.db import Database
   d = Database(pathlib.Path(tempfile.mkdtemp()) / "draft.db"); d.migrate()
   command.revision(d.alembic_config(), message="<what>", autogenerate=True, rev_id="NNNN")
   EOF
   ```
3. **Finish it by hand**, in the style of `0002_runs_and_costs.py`:
   - The docstring says what changes.
   - Remove the `Create Date` line and the "auto generated" comments.
   - Use `op.batch_alter_table` for any alter on an existing table (SQLite can't alter in place).
   - Give a new NOT NULL column on a table that has rows a `server_default`, or backfill it.
   - Name indexes `ix_<table>_<columns>`.
   - Write a `downgrade()` that reverses every step in reverse order. `pass` is not a downgrade.
   - Never import `lanternist.db` in a migration.
4. **Tests** (`tests/test_data.py`):
   - `test_models_match_the_migrations` must pass: models and migrations agree, and base ↔ head
     round-trips.
   - Add `test_migration_NNNN_keeps_rows`: upgrade to the previous revision, insert rows as they
     look today, upgrade, check nothing was lost and the new column has its default, then downgrade
     and check again. `test_migration_keeps_mvp_rows` is the template.
   - When `~/Lanternist/lanternist.db` exists, `test_migration_on_a_copy_of_the_real_library` runs
     the migration on a copy of it. Make sure it ran (not skipped) and passed.
5. **The real library.** Don't migrate `~/Lanternist/lanternist.db` yourself. In the PR, tell the
   user the first start will migrate it, and suggest a backup first:
   `cp ~/Lanternist/lanternist.db ~/Lanternist/backups/lanternist-$(date +%F).db`.
6. **Docs.** Update the data table in the plan (plans/M2_PLAN.md §1.13 or its successor) when it describes
   the schema.
7. Run `scripts/check`.
