---
paths:
  - "src/lanternist/pipeline.py"
  - "src/lanternist/store.py"
  - "src/lanternist/timing.py"
  - "src/lanternist/prompts.py"
  - "src/lanternist/text.py"
  - "src/lanternist/gpu.py"
  - "src/lanternist/engines/**"
---

# The render pipeline and the step cache

Background: plans/MVP_PLAN.md §2 ("Decisions"), plans/M2_PLAN.md §1.1.

## Step keys

- `store.step_key(kind, **inputs)` hashes everything that decides a step's output: engine id and
  version, the final prompt text, seed, size, every parameter, and the asset ids of upstream steps.
  Leave out anything that doesn't change the output. A missing input serves stale output. An extra
  one re-renders every story in the user's library for nothing.
- The engine ids carry a version: `TTS`, `KLEIN`, `LTX` in `engines/local.py`, `CLIP` and `MIX` in
  `pipeline.py`, and `FalEngine.version` for every fal adapter (`<registry id>@N`). When a change
  alters output on purpose (a new ffmpeg filter, a new graph, a new request field), bump `@N`.
  Otherwise keep the existing key fields exactly, because users' caches depend on them.
  `test_local_step_keys_are_unchanged` pins the local ones. Say which keys change in the PR.
- An engine builds its own keys (`engine.key(kind, **inputs)`): the stage passes what it decides
  (prompt, seed, size, upstream assets), the engine adds what's model-specific.
- Hash the prompt that is actually sent, built by `prompts.py`, never the scene fields it was built from.
- A key's inputs must be JSON-stable: lists, not tuples or sets; no floats computed differently on
  another run (round with `round(x, 3)`, as `clips` and `mix` do).

## Stages

Each stage builds one `Item` per output and hands them to `Pipeline._stage`, which does the same
things in the same order for every stage (don't write the loop again):

1. Serve the items whose key `store.get_step` holds.
2. `emit(stage, "start", done=hits, total=all)`, then `cached` (with its asset) or `queued` for each
   item, so the page shows every scene from the start.
3. Run all misses as **one batch** on the stage's engine (`engines/base.py`): one model load, under
   `lease()`, for a local engine; concurrent requests, no lease, for a remote one. The engine says
   when it starts on an item with `ctx.phase(item, "working", None)`, or that it's queued at a
   provider with `ctx.phase(item, "waiting", ahead)`. A new engine does too.
4. For each output as it lands: `store.put` the file, `store.put_step` its record, then
   `emit(stage, "done", scene=n, …, asset=…)`.
5. `emit(stage, "finish")`, and remove the `store.tmp()` work dir.

An item reports under its scene, or under the character it portrays (`Item.who`). `jobs.Progress`
folds these events into the snapshot's `scenes` and `cast`.

`peek()` shows what the cache holds without running anything. It must compute the same keys as the
stages, so build keys only through the `_…_key` helpers and never inline a second copy.

Every stage has a fake path (`cfg.fake_engines`) producing media of the right shape and length
through `engines/fake.py`. A new stage or engine gets one in the same PR.

## GPU

- Run a local engine only inside `async with lease(cfg, owner, vram_gb)`, and only for as long as
  the batch runs. Remote stages never take the lease.
- VRAM budgets come from config (`engines.*.vram_gb`), not literals.

## ffmpeg and timing

- Every ffmpeg command line is built in `engines/ffmpeg.py`, which runs it through `encode()` (with
  its NVENC-to-libx264 fallback) or `run()`. Filtergraph builders are pure functions returning
  strings, so tests can compare them exactly.
- All timeline arithmetic (slots, handles, crossfade offsets, cues) lives in `timing.py` as pure
  functions with tests. The pipeline calls them and does no timing arithmetic of its own.
