---
name: self-review
description: Review the current branch's changes against Lanternist's own rules (one source for each fact, no slop, the invariants, tests) with fresh eyes, before a PR. Use when a change is finished, before /pr, or when asked to review the diff.
argument-hint: "[base branch, default main]"
context: fork
agent: reviewer
---

# Review the change against this project's rules

You are reviewing someone else's change, and you have no stake in it. Find what's wrong. Don't
praise, and don't restate the diff.

## Gather

Compare against `$ARGUMENTS`, or `main` if that's empty. Call it `<base>` below. Passing the reformat
commit's SHA keeps a mechanical reformat out of the review.

```bash
git diff --stat <base>...HEAD; git status --short
git diff <base>...HEAD; git diff HEAD          # committed, then uncommitted work
```

Read `CLAUDE.md` and every `.claude/rules/*.md` whose `paths` match a changed file. For each changed
function, read the whole function and its callers, not just the hunk.

## Check

1. **One source for each fact.** For every new constant, list, label, type, helper or query in the
   diff, search the repo for an existing one (`grep -rn` for the value and for similar names). Check
   the CLAUDE.md table: does the change copy a backend fact into the frontend, or restate a shape
   that `storyboard.py`, the registry or `api.ts` already owns? Then run the loose clone check, and
   report only the clones that touch changed files:
   `web/node_modules/.bin/jscpd --config .jscpd.json --ignore-identifiers --exit-code 0 src web/src tests`
2. **Slop.** Look for: commented-out code; dead code; unused parameters; a comment that restates the
   code; a wrapper, base class or option with one user; a defensive `try` or `None` check that can't
   trigger; a broad `except`; a placeholder name; a TODO without a plan item; `print` debugging; an
   edit outside the task. Also: a message that doesn't say what to do, and code that doesn't match
   its neighbours' style.
3. **Invariants** (CLAUDE.md, numbered):
   - Does a changed `step_key(...)` input or engine id alter existing keys? Was the engine `@N`
     bumped only for a real output change?
   - Is a local engine used outside `lease()`, or does a remote stage take the lease?
   - Does a worker import anything outside the standard library and its own venv?
   - Can a key reach storage, a log or a response? Does stored text skip `redact()`?
   - Is money handled as a float?
   - Is there a query outside `db.py`? A model change without its migration? (Section 4 has more.)
   - Does a fal call lack an expiry, or poll before its `step_runs` row exists?
   - Is there a feature with no fake-mode path?
4. **The database**, when the diff touches `db.py`, a migration, a `Database` method's callers, or
   the test fixtures. Read `.claude/rules/database.md`, then check that the same code is right on
   SQLite and on Postgres:
   - **Where.** Does a module other than `db.py` (or `migrations/`) import SQLAlchemy, call
     `db.session()` or touch `db.engine`, under any name for the database? Does a public `Database`
     method take a session?
   - **Portable.** Is there SQLite-only SQL (`sqlite_*`, `INSERT OR`, `strftime`, `json_extract`)
     or raw `text()` where a construct exists? Is there a descending or ascending order on a column
     that can be NULL, without `nulls_last()`/`nulls_first()`? Does a read-then-write count on
     `with_for_update()`, which renders nothing on SQLite?
   - **Cost.** Does a list or a loop run a query per row? Count the statements a list page sends
     for 1 row and for 50. Does an async function run a query on the event loop in a hot path (per
     request, per tick) instead of `asyncio.to_thread`?
   - **Races.** Does a check and a write in two statements let another process slip in between? Is
     the race settled by a constraint or a single statement, and does its failure become the
     module's error (a 409, not a 500)?
   - **Schema.** Is every new constraint and index named (`uq_`, `fk_`, `ck_`, `ix_`), with the
     same name in the model and the migration? Does the migration downgrade? Does its keeps-rows
     test run on both databases (not `sqlite_only`, unless it's about a local library file)?
   - **Deletes.** Do they lean on `ON DELETE`, with spend kept (`SET NULL`)?
   - **Secrets.** Can the database URL's password reach a message, a log or a response? Anything
     printed uses `db.shown`.
   - **Proof.** Did the tests run on Postgres? The PR body names `scripts/check postgres`, or CI's
     `python-postgres` job is green. If `LANTERNIST_TEST_DATABASE_URL` is set here, run it.
5. **Contract.** If a route's shape changed, did `web/src/api.ts` change with it?
6. **Tests.** Is every new behaviour tested? Does a bug fix include the test that fails without it?
   Do the tests assert exact values where cost or cache keys are involved?
7. **Plan.** If the change finishes a plan item, is it ticked in the plan file?

## Report

A numbered list, most serious first. For each finding give `file:line`, the rule it breaks (quote
it), and the concrete fix. Mark each one **must fix** (breaks an invariant, a test or a rule) or
**should fix**. If you find nothing, say "No findings". Don't invent findings to fill the list.
