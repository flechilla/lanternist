---
paths:
  - "src/lanternist/api/**"
  - "web/src/api.ts"
---

# The API and its TypeScript mirror

`api/app.py` serves REST under `/api`, SSE at `/api/jobs/{id}/events`, and the built web app. It binds
to localhost; there are no accounts.

- **Routes stay thin.** A route validates input, calls the module that owns the work (`db`, `prefs`,
  `keys`, `Runner`, `Pipeline`), and shapes the response. Business rules, queries and file handling
  belong in those modules.
- Request bodies are Pydantic models. Reuse the domain models (`Storyboard`, `Brief`) rather than
  restating their fields.
- Errors: `HTTPException(status, "sentence")`: 404 for a missing thing, 409 for a stale
  `base_version`, 422 for input the owner module rejected (`ValueError` becomes 422). `raise … from None`.
- Long work is a job: `runner.enqueue(...)` and return the job. Never await a model or a provider
  inside a request.
- Build a response through `job_dict` or `story_dict`, or a helper like them. Don't hand-assemble the
  same shape twice. Timestamps are ISO strings.
- Nothing secret goes out: no key values, no absolute paths beyond what the UI already shows.

## Keeping `web/src/api.ts` in step

`api.ts` hand-mirrors the response shapes and holds the only `fetch` calls in the frontend.

- Any change to a route's path, parameters or response shape updates `api.ts` in the same PR:
  its interface and its `api.*` call. `pnpm --dir web build` then type-checks every caller.
- When the frontend needs a list or a number the backend owns (languages, stages, words per minute),
  add it to a response, usually `/api/options`. Don't copy it into TypeScript.
