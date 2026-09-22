---
name: add-model
description: Add a model to Lanternist's registry (a fal endpoint or a local engine for narration, pictures, video or ambience) with prices read from its page, every cost-changing default made explicit, and tests. Use when asked to add, offer or support a new model or endpoint.
argument-hint: "<model name or fal endpoint id>"
---

# Add a model: $ARGUMENTS

Read `.claude/rules/remote.md` and the capability's section in `M2_PLAN.md` (§1.7 pictures, §1.8
video, §1.9 narration) first. Writer models are not registry entries: they come live from Ollama and
OpenRouter.

1. **Find its place.** Pick the capability (`tts.speak`, `image.keyframe`, `video.image_to_video`,
   `audio.ambience`) and its file, `src/lanternist/registry/<capability>.toml`. Read every entry
   there, and pick the `family` whose input builder fits. If none fits, the model needs a new family
   adapter: say so, and plan that code with its own tests before writing the entry.
2. **Read the source, not memory.** Fetch the endpoint's page on fal.ai (its API schema and
   `llms.txt`, as M2_PLAN.md did) and note today's date. Record:
   - every input name and its default
   - billable lengths and sizes
   - list price per our unit, with its tiers (audio on, resolution)
   - the licence and commercial use
   - whether it takes a seed, a reference image or a negative prompt
3. **Write the entry**, following its neighbours:
   - `id = "fal/<short-name>"`, a `label` ending `· fal`, `endpoint` (plus `endpoints` for extra
     roles).
   - `defaults`: every input that changes cost or output, stated explicitly even when it equals
     fal's default. Audio, prompt expansion, resolution and safety options are the usual ones.
   - `durations` for video, `languages`, `voices` and `max_chars` for narration, `references` for
     pictures.
   - `price = { unit, usd = "…", tiers = {…}, synced = "YYYY-MM-DD" }`. Write the USD values as
     decimal strings.
   - `commercial_use` and `licence`. Put gotchas in `notes` ("no seed input: it follows the start
     image").
4. **Test offline.** The registry loads (`ModelEntry` forbids unknown keys, so a typo fails).
   `lanternist models --capability <capability>` lists it at the right price. The adapter's request
   body for this entry equals an exact expected dict, defaults included, sent against the fake fal.
   If the new durations change shot planning, add a golden case to the `plan_shots` tests.
5. **Check the price.** `lanternist models --sync` needs the fal key and writes to the user's
   library, so ask first. It records what fal bills. A drift warning means the list price or tier
   doesn't match fal's billing: re-read the page before trusting either.
6. **Live test, only if the user agrees.** Say what it will cost first. Add one minimal call to
   `tests/test_live.py`, and compare the computed cost with the account's usage.
7. **Plan.** Add the model to the relevant table in `M2_PLAN.md`, with its price and date.
8. Run `scripts/check`.
