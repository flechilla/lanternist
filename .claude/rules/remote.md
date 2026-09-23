---
paths:
  - "src/lanternist/providers/**"
  - "src/lanternist/registry/**"
  - "src/lanternist/keys.py"
  - "src/lanternist/prefs.py"
  - "src/lanternist/doctor.py"
---

# Remote providers, keys, prices and the registry

Background: plans/M2_PLAN.md §1.2–1.13. Where the plan marks something **verify**, confirm it with a live
test before relying on it, and record what you learned in the plan.

## Keys

- Look keys up only through `keys.get_key(provider, fake=cfg.fake_engines)`, and store them only
  through `keys.set_key`.
- A key goes in the `Authorization` header to its own provider's API hosts. It never goes to a CDN
  (`Fal.download` sends no key), and never into the database, a log line, a job error, a `step_runs` row or
  an API response. `GET /api/providers` shows `last4` only.
- Pass any provider text you store or show through `keys.redact()`. Existing examples: job errors,
  `ProviderError` messages, `step_runs.error`.

## Calls

- Use plain httpx through the client's `client()` helper, so `providers.transport(cfg)` can swap in
  the fakes. Don't add an SDK.
- Retry only what's retryable: 429, 5xx, transport errors, and OpenRouter's in-flight 402. Use
  `providers.backoff()` and honour `Retry-After`. Never retry a 4xx that means "no": moderation,
  validation, bad key.
- Raise the provider's `ProviderError` subclass with `status`, `type` and `retryable`, and a message
  that names the field or reason.
- fal: attach `X-Fal-Object-Lifecycle-Preference` to every submit and upload. Write the
  `step_runs` row (`submitted`, with the three URLs) *before* polling. A shutdown leaves the request
  running; only `RunSpec.user_cancelled()` sends the cancel.
- OpenRouter: send only the parameters the model lists in `supported_parameters`. Treat an error
  inside a 200 body as an error.

## Money

- USD in the database is integer micro-dollars (`db.to_micros`, `db.to_usd`). Prices are `Decimal`
  or decimal strings. `float` is only for display.
- Actual fal cost is billable units × **billing** price. Estimates use the **list** price
  (`registry/__init__.py` explains why these differ). A cost we couldn't compute is
  `cost_source="none"`, never a guess.

## The registry

- Every model is a `[[model]]` entry in `registry/<capability>.toml`, validated by `ModelEntry`
  (`extra="forbid"`, so a typo fails loudly).
- `defaults` states every request field that changes cost or output, even when it matches fal's
  default: `generate_audio = false`, `enable_prompt_expansion = false`. fal's defaults change without
  notice, and they cost money.
- Prices carry `synced = "YYYY-MM-DD"` and come from the model page. `lanternist models --sync`
  records what fal bills; it never overwrites a list price.
- Adapters are written per family (`family = "kling"`), not per model. A new model of a known family
  is a TOML entry and a test, with no new code. Use `/add-model`.
