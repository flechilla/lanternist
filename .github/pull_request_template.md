## What and why

<!-- One paragraph: the change, and the reason for it. Link the plan item (plans/M2_PLAN.md §…) if there is one. -->

## How it was checked

<!-- `scripts/check` passes. Say what else you ran: `pytest -m live` (and what it cost), `pytest -m gpu`,
     the app in fake mode, a real render. Paste numbers where they matter: durations, costs, file sizes. -->

## Checklist

- [ ] `scripts/check` passes locally.
- [ ] One concern per PR. A mechanical reformat or rename goes in its own commit or PR.
- [ ] Nothing is defined twice: constants, labels, prices and schemas each live in one place (see CLAUDE.md, "One source for each fact").
- [ ] Step keys: existing stories re-render from cache, or the PR says why a key changed and bumps the engine's `@N` version.
- [ ] Money and keys: costs in integer micro-dollars; no key in the database, logs, errors or the browser; every remote call has an expiry and a timeout.
- [ ] Database: queries live in `db.py` and pass on SQLite and Postgres (`scripts/check postgres`, or CI's `python-postgres` job); a model change comes with an Alembic migration that upgrades and downgrades, and names its constraints.
- [ ] API: a changed response shape is mirrored in `web/src/api.ts` in the same PR.
- [ ] Tests cover the behaviour the PR adds or fixes; a bug fix adds the test that would have caught it.
- [ ] The plan file's checkboxes and status line reflect what this PR finished.
