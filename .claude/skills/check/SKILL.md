---
name: check
description: Run Lanternist's quality gates (the same ones CI runs on every pull request) and fix what fails. Use before committing or opening a PR, after a change touches several files, or when asked to check, lint, type-check or test the project.
argument-hint: "[python|web|dup]"
---

# Run the gates

```bash
scripts/check $ARGUMENTS
```

With no argument, every gate runs in order and the script stops at the first failure. If the
environment isn't set up: `uv sync && pnpm --dir web install`.

## When a gate fails

| Gate | Fix |
|---|---|
| python: format / web: format | `scripts/check fix`, then re-run. Never hand-format. |
| python: lint | Fix the code. The rule's name says why (`B905`: add `strict=True`; `BLE001`: catch the specific exception). |
| python: types | Fix the types. Where a value really can be None, handle it or raise a useful error. Where it can't, but the checker can't see why (`stdout=PIPE`), use `cast` and give the reason on the line. Never `type: ignore`. |
| python: tests | Read the failure, reproduce with `uv run pytest -x -k <name>`, and fix the code, not the test, unless the test is wrong. Say which. |
| web: lint | As for Python. Floating promise: await it, handle it, or `void` it on purpose. |
| web: types and build | `tsc` errors come first in the output; fix those. |
| duplication | jscpd names two ranges. Extract what they share into the module that owns it, then call it from both. |

`test_models_match_the_migrations` failing means `db.py` and the migrations disagree: see
`/add-migration`.

## Don't weaken a gate

Don't add a `noqa`, `type: ignore`, `eslint-disable`, an ignored rule, a mypy exemption or a jscpd
exclusion to get to green. Don't delete or skip a test either. If a rule is wrong for a line, write
the reason on that line (`# noqa: BLE001 - a broken keychain must not break the app`) and mention it
to the user. The mypy exemption list in `pyproject.toml` only ever shrinks.

## Report

Say which gates ran, what failed, and what you changed to fix it. If something still fails, show the
exact error. Don't summarise it as "mostly passing".
