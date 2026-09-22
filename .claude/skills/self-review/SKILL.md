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
   - Is there a query outside `db.py`? A model change without its migration?
   - Does a fal call lack an expiry, or poll before its `step_runs` row exists?
   - Is there a feature with no fake-mode path?
4. **Contract.** If a route's shape changed, did `web/src/api.ts` change with it?
5. **Tests.** Is every new behaviour tested? Does a bug fix include the test that fails without it?
   Do the tests assert exact values where cost or cache keys are involved?
6. **Plan.** If the change finishes a plan item, is it ticked in the plan file?

## Report

A numbered list, most serious first. For each finding give `file:line`, the rule it breaks (quote
it), and the concrete fix. Mark each one **must fix** (breaks an invariant, a test or a rule) or
**should fix**. If you find nothing, say "No findings". Don't invent findings to fill the list.
