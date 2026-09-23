---
paths:
  - "tests/**"
---

# Tests

`uv run pytest` runs everything that needs no GPU, no keys and no network, in about 20 seconds: unit
tests, the full pipeline and the API on fake engines, the provider clients against in-process fakes,
and the migrations.

- **Fixtures live in `conftest.py`**: `cfg`, `db`, `voices`, `client` (the app in fake mode on its
  own library) and `hosted_client` (the hosted edition, signed in as ann; send
  `headers={FAKE_USER: "bob"}` to act as someone else). Keys are always isolated from the real
  keychain. Use the shared fixtures, and add a new one there once two test files would otherwise
  repeat it.
- **Fakes, not mocks.** Remote behaviour goes through `providers.fake.FakeWorld` (steer it with its
  attributes: `fail_submit`, `polls_before_done`, …). Engines go through fake mode. Don't mock
  `httpx` or the code under test. Patching a delay to zero (`backoff`) is fine.
- **Pin the details that cost money or break caches:** exact request bodies sent to providers, step
  keys, filtergraph strings, and computed costs in micros. Test pure functions (`timing`, `text`,
  `prompts`, `ffmpeg.mix_graph`) with exact values.
- A test name reads as the fact it checks: `test_a_restart_resumes_instead_of_paying_again`.
- A bug fix adds the test that fails without it.
- `@pytest.mark.gpu` tests run real models (minutes, and they evict the user's models).
  `@pytest.mark.live` tests call the real APIs and spend real money. Their module docstring states
  the cost. Both are deselected by default, and neither runs without the user asking.
- Tests that need the user's own files (the prototype stories, the real library) use `skipif` on the
  path, so they pass on CI.
