---
name: add-query
description: Add or change a query in Lanternist's db.py so it runs the same on SQLite and Postgres, costs a fixed number of statements, lets the database settle races, and is tested on both. Use when a feature needs to read or write rows, when a query has to move out of another module, or when a page, loop or async function reads the database.
argument-hint: "<what it reads or writes, e.g. 'the renders a story finished this week'>"
---

# Add a query: $ARGUMENTS

Read `.claude/rules/database.md` first. The same code runs a local SQLite library and the hosted
Postgres, and every query lives in `db.py` so that the hosted edition can scope each one to the user
who owns the row, in one file.

1. **Look first.** Search `db.py` for a method that already returns this, or nearly (grep the table
   and the columns). Extend it rather than add a sibling. If another module builds the query today,
   this is a move: delete the old code in the same change.
2. **Place it.** A `Database` method in `db.py`, in its table's section (`# stories`, `# jobs`, …):
   - It opens its own session (`with self.session() as s:`), and returns rows, plain values or a
     small dataclass (`LibraryRow`). Never a session or a statement.
   - A helper that takes a session is private (`_storyboard`), for use inside `db.py` only.
   - Callers (routes, the runner, the pipeline) only call methods: they don't import SQLAlchemy or
     touch `db.engine`. `test_every_query_lives_in_db_py` checks it.
   - Missing rows: `None` from a getter, `False` from a delete, `KeyError` where the caller turns
     it into a 404. Follow the neighbours.
3. **Write it in SQLAlchemy 2 style** (`select`, `update`, `s.scalars`, `s.execute(…).tuples()`)
   and keep it portable (the rule's list: NULL ordering, `with_for_update`, errors mid-transaction).
   The older methods still use `s.query`: leave them unless you're changing them anyway.
4. **Count the statements.** Anything that lists must cost the same for 1 row as for 50. Join,
   `group_by`, or rank with `func.row_number().over(partition_by=…)` (as `library()` does). A caller
   that loops over rows and calls a method for each one needs a new method that takes them all.
5. **Decide what a race does.** If the method reads and then writes on what it read, another
   process can write in between:
   - Make it one statement: `update(…).where(…).returning(…)`, as `claim_job` does.
   - Or let a unique constraint refuse the second write, and turn the `IntegrityError` at commit
     into the module's error, as `_commit_version` turns it into `StaleVersion`.
   - Retry only when doing the change again is right, and only once (`change_story`,
     `add_version`). A callback it runs again must depend only on its argument: `keep_redraws`
     clears what the first run collected.
6. **Async callers.** An async function that queries on a hot path (per request, per tick, per
   viewer) calls `await asyncio.to_thread(db.method, …)`, as the SSE loop does. A rare call can stay
   direct.
7. **Tests**, through the `db` fixture, so they run on both databases, with exact values:
   - A list: the statement count, with `statements(db)` from `tests/test_data.py`
     (`test_library_queries_do_not_grow_with_stories`). Move that helper into `conftest.py` once a
     second test file needs it.
   - A race: make the interleaving happen on purpose. The `lands_first` fixture runs another save
     just as the one under test writes (`test_two_saves_of_one_version_conflict`). A callback can
     also save from inside the change (`test_a_change_made_as_another_save_lands_is_applied_to_that_save`).
     For a claim, use threads behind a `Barrier` (`test_claim_gives_each_worker_its_own_job`).
   - A retry: the code it runs twice must start over. Test that the second run's result doesn't
     carry the first's (`test_the_new_seeds_keep_an_edit_saved_while_the_job_ran`).
   - Anything that deletes: what cascades, and what must stay (`step_runs` keeps its cost).
8. **Run it on both.** Run `scripts/check python`, then `scripts/check postgres` (see `/check` for
   the server). A test that passes on SQLite and fails on Postgres is a portability bug in the query,
   not in the test.
9. **Docs.** If the change removes a line from CLAUDE.md's "Known duplication", delete that line.
   If it finishes a plan item, tick it.
