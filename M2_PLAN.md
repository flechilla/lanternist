# Lanternist M2: OpenRouter and fal.ai

> **Status, 21 Sep 2026: Phase A is built.** 62 tests pass offline, and your library is migrated to `0002` (backup in `~/Lanternist/backups/`). One step is left: running the live checks (`uv run pytest -m live -s`) once your OpenRouter and fal keys are set. Phases B–F are next.
>
> This is the blueprint's M2 ("fal, registry, estimator, your own key") with one change: the writer calls OpenRouter directly instead of going through fal's `openrouter/router`. Going direct gives the real cost of every request, the full list of models, and one hop fewer.
> API facts below were read from the OpenRouter and fal docs, the per-model `llms.txt` pages and the fal-client 1.0.3 source on 21 Sep 2026. Anything marked **verify** was not confirmed and gets checked in Phase A.
> Everything new that M2 records goes into the existing SQLite database, `~/Lanternist/lanternist.db`: what each step cost, requests in flight, budgets, estimates, prices, settings and uploads (§1.13). A move to another database comes later, so the schema stays portable.

**Goal:** better models for every stage, and no GPU needed for any of them. Each stage (writer, narration, pictures, video, ambience) can run on a local engine, as today, or on a remote model: OpenRouter for the writer, fal.ai for media. You pay with your own keys, see an estimate before anything is spent, and a per-story budget caps it. Local stays the default and stays free.

Definition of done (the acceptance test at the end of Phase F):

1. In **Settings**, paste an OpenRouter key and a fal key. Both show ✓, and OpenRouter shows its usage and limit. The keys never reach the browser.
2. **New story:** Spanish, kids 5–8, 3 minutes, with an OpenRouter model as the writer. You get a storyboard, and the job shows what it cost.
3. **Board:** pictures on fal (klein 9B), narration local. The estimate appears before you start. Re-rolling one picture costs about $0.03.
4. **Render:** 3 scenes as video on fal (Kling v3 Standard), with ambience from MMAudio, and the estimate shown first. The film plays, and the actual cost is within ±15% of the estimate.
5. **Interruptions:** stop the server during the video stage and start it again: the fal requests already running are polled, not submitted again. Cancel a render: its fal requests are cancelled.
6. **Budget:** a full-video story with a $1 budget stops before the video stage and says how much more it needs. Raising the budget carries on from the cache.
7. **No GPU:** a story with every stage remote never takes the GPU lease and never touches Ollama or ComfyUI.

---

## 0. Where we are

Everything in `MVP_PLAN.md` phases 0–3 works on the 5090, from idea to film in the browser. From Phase 4, per-scene camera moves and subtitles (off, sidecar or burned in) are built.

Against the blueprint, that covers:
- **M1** (self-hosted alpha), all of it.
- **M0**, except the platform spike on other operating systems.
- **The local half of M3:** video and hybrid modes, the step cache, and re-rendering only what an edit reaches.

Still open from MVP Phase 4:
- motion intensity and pace controls
- aspect ratios
- wind-down
- previews jumping the queue
- more TTS engines and per-character voices

**What this plan builds on:**
- `writer.py` talks to the LLM through a single `Ollama.chat(system, user, schema, temperature)`.
- `pipeline.py` has one method per stage (`narrate`, `draw`, `motion`, `clips`, `mix`). Each works out step keys, serves cache hits, and runs the misses as one batch on one hard-wired local engine.
- `ffmpeg.video_clip` already fits any clip to its slot: it cover-scales, holds the last frame, and adds silence when the clip has no audio. So remote clips of any size or length drop straight in.

---

## 1. Design

### 1.1 One engine interface, local or remote

Each stage gets a capability. Each capability has engines, and an engine is either local or remote.

| Capability | Local (today) | Remote |
|---|---|---|
| `writer.chat` | Ollama `qwen3.8` | OpenRouter: any model with structured outputs |
| `tts.speak` | Qwen3-TTS 1.7B worker | fal: Qwen3-TTS 1.7B (clone), ElevenLabs v3, MiniMax Speech 2.8 HD, Chatterbox Multilingual |
| `image.keyframe` (cast sheet and keyframes) | FLUX.2 [klein] 9B worker | fal: klein 9B (text-to-image for the cast sheet, edit for keyframes), Nano Banana 2 edit |
| `video.image_to_video` | LTX-2.5 via ComfyUI | fal: Kling v3 Standard/Pro, LTX-2.5 fast, Veo 3.1 fast, Wan 2.6 flash |
| `audio.ambience` (**new**) | none (LTX makes its own) | fal: MMAudio v2, video-to-audio from the scene's `sound` line |

The interface is batch-shaped, because local engines load their model once per batch:

```python
class Engine(Protocol):
    entry: ModelEntry                    # registry entry: id, provider, capability, limits, price
    def key_params(self, item: Item) -> dict      # everything model-specific that decides the output
    def estimate(self, items: list[Item]) -> Estimate   # pure: units, USD, GPU-seconds
    async def run(self, items: list[Item], ctx: StepContext, on_item: Callable[[ItemResult], None]) -> None
```

**Local engines** wrap today's code unchanged: one worker subprocess, or one ComfyUI session, under `lease()` for the whole batch.

**Remote engines:**
- They take no lease.
- Items run concurrently under a per-provider semaphore.
- Every output is downloaded into the store the moment it lands, and `on_item` fires per item as it does today.

`pipeline.py` keeps its cache logic. Only the "run the pending items" half of each stage calls `engine.run` instead of a hard-wired worker. The two stages that chain work:
- **`draw`:** the cast sheet goes first. It is uploaded once, then all keyframes run in parallel with its URL as the reference.
- **`motion`:** a slot longer than one generation is split into shots. Each later shot starts from the previous shot's last frame, exactly as with local LTX.

**Cache compatibility:** local engines keep today's ids (`qwen3-tts-1.7b@1`, `flux2-klein-9b@1`, `ltx-2.5-22b-nvfp4@1`) and exactly today's key fields. A golden test pins the keys of a fixed storyboard, so the existing `~/Lanternist` cache stays warm. Remote engines key on their registry id plus their parameters, so switching a model re-runs exactly the steps it reaches.

### 1.2 The model registry

The registry is TOML files shipped in the package (`src/lanternist/registry/*.toml`, one per capability). TOML needs no new dependency; the blueprint's YAML sketch maps across one to one. A user file at `~/Lanternist/models.toml` can:
- re-price an entry
- disable an entry
- add an entry that points a known adapter family at a new endpoint

Adapters are written per **family** in code (`fal_image`, `fal_video`, `fal_tts`, `fal_audio`), because input names differ a lot between models:
- Kling takes `start_image_url` and `duration: "5"`.
- LTX takes `image_url` and `duration: 6`.
- Veo takes `duration: "6s"`.

The registry holds everything else:

```toml
[[model]]
id = "fal/kling-v3-standard"
label = "Kling v3 Standard"
capability = "video.image_to_video"
provider = "fal"
family = "kling"                                   # which input builder the adapter uses
endpoint = "fal-ai/kling-video/v3/standard/image-to-video"
commercial_use = true
durations = { min = 3, max = 15, step = 1 }        # billable clip lengths, for the shot planner
defaults = { generate_audio = false, negative_prompt = "blur, distort, low quality", cfg_scale = 0.5 }
price = { unit = "output_second", usd = 0.084, synced = "2026-09-21" }

[[model]]
id = "local/ltx-2.5-22b-nvfp4"                    # local engines are entries too
capability = "video.image_to_video"
provider = "local"
engine_id = "ltx-2.5-22b-nvfp4@1"                 # keeps today's step keys
durations = { frames = "8k+1", fps = 24, max_seconds = 20 }
price = { unit = "output_second", gpu_seconds = 4.3 }
```

The same entries drive the model pickers, the estimator and the doctor.

OpenRouter models are not hard-coded. The writer's list is the live `GET /api/v1/models?supported_parameters=structured_outputs`, which is public and needs no key. It is cached in memory for 24 h, and a short `recommended` list from Settings is pinned to the top.

`lanternist models sync` reads fal's `GET /v1/models/pricing` (needs the key) and `GET /v1/models` (status, to hide deprecated endpoints) into the `model_prices` table. It adds a row only when a price changes, so past estimates can still be explained. The app runs it at start when the newest row is more than a day old. The pricing API has one `unit_price` per endpoint. Tiers such as resolution, and "audio on costs more", stay as formulas in the registry.

### 1.3 Choosing models per story

- **`Storyboard.models`** (new, optional) holds `{writer, tts, image, video, ambience}` registry ids. Unset fields fall back first to what the Settings page saved (the `settings` table), then to `[defaults]` in `lanternist.toml`. It lives in the storyboard so a render always matches the version it came from. Step keys already carry the engine, so a model change is just an edit.
- **`Brief.writer`** picks the model that writes the story.
- **`sb.voice`** keeps its name, and its meaning follows the TTS engine:
  - For clone engines (local Qwen3-TTS, fal Qwen3-TTS, Chatterbox), it is a reference clip in `voices/`, as today.
  - For preset engines (ElevenLabs, MiniMax), it is one of that engine's voice ids, listed in the registry.

  The voice picker shows only voices that fit the chosen engine.
- Per-scene model overrides (the blueprint's `overrides`) come later. The interface doesn't need them yet.

```toml
[defaults]
writer = "ollama/qwen3.8"
tts = "local/qwen3-tts-1.7b"
image = "local/flux2-klein-9b"
video = "local/ltx-2.5-22b-nvfp4"
ambience = "none"            # or "fal/mmaudio-v2"; ignored for video models that make their own sound
budget_usd = 5.0             # per story; values saved on the Settings page (the settings table) win over this file

[openrouter]
url = "https://openrouter.ai/api/v1"
recommended = []             # model ids pinned at the top of the writer picker, chosen in Phase B
data_collection = "deny"     # verify: provider routing option that excludes providers that store prompts

[fal]
max_concurrency = 4          # new accounts start at 2 running requests; queued ones wait at fal, never dropped
media_ttl_hours = 24         # expiry sent with every request and upload (fal keeps media public forever by default)
```

### 1.4 Keys

- **Lookup order:**
  1. environment (`OPENROUTER_API_KEY`, `FAL_KEY`)
  2. the OS keychain, through `keyring` (new dependency)
  3. `~/.config/lanternist/secrets.toml` with mode 0600, for machines with no keychain
- **Setting a key:** from the Settings page through `PUT /api/providers/{name}/key`, which is write-only. `GET /api/providers` returns only `{configured, source, last4, ok, detail, usage}`.
- **Where a key goes:** only to its own provider. Keys are never stored in SQLite. A redacting httpx event hook keeps them out of logs, job errors and `step_runs` rows.
- **OpenRouter:**
  - `GET /api/v1/key` works with a normal key and shows `usage` and `limit_remaining`.
  - Account credits (`/api/v1/credits`) need a management key, so the app shows key usage and limit instead.
  - Suggest setting a spending limit on the key itself, at openrouter.ai.

### 1.5 Writer on OpenRouter

- **The LLM layer.** A new `llm.py` defines `LLM.chat(system, user, schema=None, temperature) -> Reply(text, usage)`. `Ollama` moves there from `writer.py`, and `OpenRouter` is the second implementation. `write_storyboard` and `rewrite_scene` receive an `LLM`, and only Ollama takes the GPU lease.
- **Request.** `POST /chat/completions` with `Authorization: Bearer`, `X-OpenRouter-Title: Lanternist` and `HTTP-Referer`.
- **Structured output (pass 2 and rewrites):**
  - Send `response_format: {type: "json_schema", json_schema: {name, strict: true, schema}}` with `provider: {require_parameters: true}`, so the request only routes to providers that honour the schema.
  - `inline_schema(strict=True)` adds `additionalProperties: false` and lists every property as required. It already inlines `$ref`s. Keep the schema to that safe subset: no `oneOf` and no `format`.
  - Models without structured outputs aren't offered.
- **Reasoning:**
  - Where the model allows it, send `reasoning: {effort: "none"}`.
  - For the models where reasoning is mandatory (the `/models` entry says so), send `{effort: "low", exclude: true}`.
  - Reasoning tokens count against `max_tokens`. A `200` with `finish_reason: "length"` and empty content therefore means "retry with a bigger budget", not "bad output".
- **Cost.** `usage.cost` arrives on every response with no extra flag. It is added to the job as the actual cost.
- **Errors:**

  | Status | What the writer does |
  |---|---|
  | 402 | "Out of credit or over the key's limit", naming `metadata.limit_source`. `openrouter_in_flight_budget` is transient: honour `Retry-After`. |
  | 403 | Moderation or refusal, shown with its reasons and never retried. |
  | 429, 502, 503 | Back off and retry twice. |
  | Errors inside a 200 body | Treated as errors. |
- **Prompts.** Unchanged. The ±15% length revision and the one repair retry stay: a better model makes them rarer, not unnecessary.

### 1.6 The fal client

Queue calls use plain httpx: they are four simple endpoints, and we need the raw URLs to resume.

| Step | Call | What happens |
|---|---|---|
| Submit | `POST https://queue.fal.run/{endpoint}` with `Authorization: Key …` and `X-Fal-Object-Lifecycle-Preference: {"expiration_duration_seconds": …}` | Returns `request_id`, `status_url`, `response_url` and `cancel_url`. We store and use those URLs rather than building them: for endpoints with sub-paths, the URL forms differ between the SDK and the OpenAPI (**verify**). |
| Poll | `status_url?logs=1`, with backoff from 1 s to 5 s | `IN_QUEUE` (with position) and `IN_PROGRESS` feed the progress line. `COMPLETED` carrying an `error` is a failure. |
| Result | `response_url` | Fetched immediately: large results expire about an hour after completion. Every output URL is downloaded into the store at once. |
| Cancel | `PUT cancel_url` | See "Cancel versus shutdown" below. |

Around those calls:
- **Uploads** (the cast sheet, last frames for chained shots, voice references, scene clips for MMAudio) use the same two calls as fal-client, written in httpx: a storage token from `rest.fal.ai`, then a `POST` to the CDN. If that fails, they fall back to the `upload/initiate` flow. Each upload carries the lifecycle header. *Built this way rather than on fal-client* to keep one code path, so the offline fake covers uploads too, and to avoid fal-client's dependencies (websockets, msgpack, aiofiles). The flow isn't in the public docs, so the live test checks it.
  - Each upload's URL and expiry go in the `uploads` table. A file is uploaded again only when its URL has less than 10 minutes left, so a cast sheet is uploaded once per story, not once per keyframe.
- **Requests in flight** are `step_runs` rows. The row is written with status `submitted`, the `request_id` and the three URLs *before* polling starts, and it moves to `running`, then `done`, `failed` or `cancelled`.
  - A step whose key has a `submitted` or `running` fal row less than 50 minutes old polls that row's URLs instead of submitting again, so a server restart costs nothing.
  - An older row is marked `failed` ("expired before restart"), and the step submits again.
- **Cancel versus shutdown.** The runner already tells them apart (`cancelling()` on shutdown means re-queue). A user cancel sends `PUT cancel_url` and marks the row `cancelled`. A shutdown leaves the requests running and their rows open for the restart. `StepContext` carries which one it is.
- **Errors:**
  - 422 → a step error naming the field and fal's `type`. `content_policy_violation` is shown and never retried.
  - 429 `concurrent_requests_limit` and 5xx → back off and retry. 5xx and queue time aren't billed.
- **Cost:**
  - Read `X-Fal-Billable-Units` from the result response (**verify** which response carries it), then multiply by the synced unit price.
  - This lands close to the real cost without the admin-only billing APIs, which stay out of scope.
- **Privacy:**
  - Every submit and upload carries an expiry (`media_ttl_hours`), because fal CDN media is otherwise public and kept forever.
  - Voice references get one hour.
  - The blueprint lists payload deletion (`DELETE /v1/models/requests/{id}/payloads`) for voice samples, which fal otherwise keeps for 30 days (**verify**).

### 1.7 Pictures on fal

- **Cast sheet:**
  - Uses `fal-ai/flux-2/klein/9b` at 1024×1024, about $0.006.
  - Nano Banana 2 has no pure text-to-image path in our list, so its cast sheet uses its edit endpoint with no references.
- **Keyframes:**
  - Use `fal-ai/flux-2/klein/9b/edit` with `image_urls: [cast sheet]`, `image_size: {width: 1920, height: 1088}`, `seed` and `num_inference_steps: 4`.
  - Cost is about $0.034 each: $0.011 per megapixel, counting input and output.
  - It's the same model as the local worker, so the character lock behaves the same.
- **Premium option:** `fal-ai/nano-banana-2/edit`.
  - It takes `aspect_ratio` and `resolution` in place of a size: 16:9 at 2K, about $0.12 per frame.
  - It follows long prompts and references better.
  - The clip step already crops whatever size comes back.
- **Seeds and re-rolls:** models that take a seed get the scene seed. For models without one, a re-roll still changes the step key, so it still draws a new picture.

### 1.8 Video on fal

**The shot planner** replaces `timing.shot_lengths`: `timing.plan_shots(clip_seconds, durations, hold_max)`.
- It picks the cheapest set of billable lengths that covers the clip, allowing a short freeze on the last frame at the end. `video_clip`'s `tpad` already does that freeze.
- The freeze defaults to 1 s: `[render] hold_max = 1.0`, which covers the crossfade handle, where most of it sits under the fade. The blueprint's 2 s is the upper setting, because 2 s frozen out of a 7 s clip shows.
- Ties go to fewer shots, because every chain is a visible seam.
- It returns the shots, the seconds paid for and the seconds wasted. The estimator shows the waste.
- Local LTX keeps its exact `8k+1` frames.

| Model | Billable lengths | Price (list, 21 Sep) | Notes |
|---|---|---|---|
| Kling v3 Standard | "3"–"15" s, any whole second | $0.084/s with audio off | `start_image_url`. No seed or size input: it follows the image. **`generate_audio` defaults to true: send false.** |
| LTX-2.5 fast (`lightricks/ltx-2.5/image-to-video/fast`) | 6, 8 … 20 s | $0.09/s at 720p, $0.13/s at 1080p, **audio included** | Same model as local, with its own ambience, so no MMAudio needed. |
| Veo 3.1 fast | "4s", "6s", "8s" | $0.10/s without audio | Premium look. Long slots need 2 shots. |
| Wan 2.6 flash (`wan/v2.6/image-to-video/flash`, no `fal-ai/` prefix) | "5", "10", "15" | $0.05/s at 720p | Cheapest. **`enable_prompt_expansion` defaults to true: send false**, or the character lock gets rewritten. |

Other details:
- **Prompt:** `prompts.video()` works as it is, and `VIDEO_NEGATIVE` goes where the model takes a negative prompt.
- **Resolution:** ask for 1080p where it costs the same, otherwise 720p. The clip step upscales to the render size.
- **Audio off by default.** Narration is separate, and audio costs 50–100% more.
- **Ambience comes from the `audio.ambience` step:**
  - `fal-ai/mmaudio-v2` gets the scene's raw clip plus `scene.sound` and returns the same video with sound muxed in, at $0.001/s.
  - Its output replaces the motion asset, so `video_clip` and the mix are untouched.
  - It's skipped for models whose registry entry says `audio = "ambience"` (local LTX, LTX fast).
- **Concurrency:** all video scenes go out at once, up to `max_concurrency`. A hybrid film's video stage takes about as long as its slowest clip, instead of the sum of all of them.

### 1.9 Narration on fal

Subtitle timing stays exact because nothing downstream changes:
- Each chunk from `text.tts_chunks` is one request, and a scene's chunks run concurrently.
- The chunks are joined with `chunk_gap` into one wav per scene, plus the `chunk_durations` the local worker returns today.
- The chunk limit comes from the registry: 300 characters for Chatterbox.

| Engine | Voice | Price | Notes |
|---|---|---|---|
| fal Qwen3-TTS 1.7B | Clone of `voices/<name>.wav` | $0.09 per 1k chars | Two calls. `qwen-3-tts/clone-voice/1.7b` turns the clip and its transcript into a speaker embedding. That's a cached step keyed by the voice's sha, with the `.safetensors` kept in the store. Each chunk then passes `speaker_voice_embedding_file_url`. **`max_new_tokens` defaults to 200: raise it**, or long chunks may be cut off. |
| ElevenLabs v3 | Preset (`voice`, default "Rachel") | $0.10 per 1k chars | `language_code` (ISO 639-1). No cloning from a clip. |
| MiniMax Speech 2.8 HD | Preset (`voice_setting.voice_id`) | $0.10 per 1k chars | Send `output_format: "url"` (the default is hex). Its $1.50 clone is left for M4. |
| Chatterbox Multilingual | Clone: the reference clip's URL as `voice` | $0.025 per 1k chars | 300 characters per request, 23 languages. |

The language check in `narrate()` (today "not supported by Qwen3-TTS") becomes each engine's `languages` list in the registry, and the pickers filter on it.

### 1.10 Estimate, budget and cost

- **Every step that runs** writes a `step_runs` row (§1.13) with its units, cost and time. That includes local steps, whose GPU-seconds calibrate the local estimates, and each writer call.
  - OpenRouter costs are `reported`.
  - fal costs are `computed` as billable units × unit price.
  - Local steps cost nothing but record GPU-seconds.
- **Spend** is a sum over `step_runs`: per job, per story, or per month. A cache hit adds no row, so re-renders cost exactly what they actually ran.
- **`jobs.estimate`** (JSON) keeps the estimate shown before the job, stamped with its price date, so estimate and actual can be compared per stage.
- **`estimate(sb, kind)`** walks the same steps as `Pipeline.peek`:
  - Cached steps cost nothing.
  - Before narration exists, seconds come from words and `WPM`. After that, from the real slots.
  - Video seconds go through the shot planner.
  - Writer cost uses the model's per-token prices on token counts measured from the first stories. It's shown as a range until we have measurements.
  - Local steps show GPU time instead of dollars.
- **API:** `GET /api/stories/{id}/estimate?kind=board|render` returns a line per stage, the total, the wasted seconds and the price date.
- **Budget:**
  - `stories.budget_micros`. When it's empty, the default from Settings applies.
  - Before each remote stage, the runner checks `spent + stage estimate ≤ budget`.
  - If it would go over, the job fails with "needs $X more", and the UI offers "Raise budget to $Y and continue".
  - Continuing wastes nothing, because the finished steps are cached.
  - No new job states are needed.

**Rough cost of a 3-minute hybrid film** (13 scenes, 4 of them video, clips of about 14 s), at list prices:

| Stage | Choice | Cost |
|---|---|---|
| Narration | fal Qwen3-TTS, about 2,700 characters | ≈ $0.25 |
| Pictures | cast sheet + 13 keyframes, klein 9B | ≈ $0.45 (Nano Banana 2 at 2K: ≈ $1.60) |
| Video | 4 × 14 s | Kling v3 Std ≈ $4.70 · LTX fast 720p ≈ $5.00 · Wan flash (15 s clips) ≈ $3.00 |
| Ambience | MMAudio, 56 s | ≈ $0.06 |
| Writer | frontier model | cents; measured in Phase B |

That's about $5.50 with Kling. Full video on Kling is about $16. Everything but video costs under $1.

### 1.11 GPU lease and doctor

- **The lease** wraps local engines only. A board with fal pictures and local narration takes the lease for narration only, and never evicts ComfyUI for a stage that doesn't use it.
- **The doctor** checks what the default models need:
  - GPU, Ollama and ComfyUI checks become warnings when no local engine is chosen.
  - New rows for each provider: the key is present, the key works (`/api/v1/key`, and fal `/v1/models/pricing` for one endpoint), and OpenRouter's usage and limit.

### 1.12 Tests

- **Offline fakes.** `providers/fake.py` is an in-process fake of fal's queue and OpenRouter, plugged in as httpx transports.
  - The fake fal walks `IN_QUEUE → IN_PROGRESS → COMPLETED` and serves ffmpeg test media.
  - `LANTERNIST_FAKE_ENGINES=1` uses it too, so the real adapters (polling, cancel, resume, cost) run in tests and in UI work with no keys.
- **Unit tests:**
  - the strict-schema transform
  - `plan_shots` golden cases, with a 1 s hold: 7 s on Kling → 6; 14 s on Veo → 8 + 6; 23 s on Kling → 11 + 11; 12 s on Wan → one 15 s shot with 3 s paid and trimmed
  - the estimator, including cached steps being free
  - key lookup and redaction
  - in-flight resume after a simulated restart, from `step_runs` rows
  - cancel versus shutdown
  - the golden local step keys (§1.1)
  - migration `0002` upgrading a copy of today's `lanternist.db` with no data lost, and downgrading cleanly
  - the settings precedence: Settings page, then toml, then built-in defaults
- **Live tests:** `pytest -m live`, opt-in with real keys and a spend of about $0.50. One writer call on a cheap model, one klein keyframe, one 5 s Wan clip, one Qwen3-TTS chunk and one MMAudio pass. It checks each computed cost against the account's usage.

### 1.13 Data: the SQLite database

**Today**, `~/Lanternist/lanternist.db` holds `stories`, `story_versions` (every storyboard save) and `jobs`. Around it are plain files:
- the step cache in `steps/`: what each step made
- content-addressed assets in `assets/`
- finished films in `films/`

**M2 adds** its data to the same database, through SQLAlchemy models in `db.py` and one Alembic migration, `0002_runs_and_costs`.

The file step cache and the assets don't move: the cache stays the index of what's already made. `step_runs` is the log of what ran and what it cost, joined to the cache by `step_key`.

| Table | Change | Holds | Used for |
|---|---|---|---|
| `step_runs` | **new** | `id`, `story_id`, `job_id` (both `ON DELETE SET NULL`, so spend history outlives a deleted story), `scene`, `stage` (`write`, `narration`, `cast`, `keyframes`, `motion`, `ambience`), `step_key` (empty for writer calls), `model_id`, `provider` (`local`, `ollama`, `openrouter`, `fal`), `status` (`submitted`, `running`, `done`, `failed`, `cancelled`), `request_id`, `urls` (JSON: status, response, cancel), `units`, `unit`, `cost_micros`, `cost_source` (`reported`, `computed`, `none`), `estimate_micros`, `gpu_seconds`, `wall_seconds`, `meta` (JSON: tokens in and out, billable units, queue wait, fal inference time), `error`, `created_at`, `started_at`, `finished_at` | The cost of each step, resuming requests after a restart, and calibrating the estimator. Indexed on `story_id`, `job_id`, `(step_key, status)` and `(provider, created_at)`. |
| `jobs` | adds `estimate` (JSON) | The estimate shown before the job: lines per stage, total, waste, price date | Comparing estimate and actual |
| `stories` | adds `budget_micros` (empty = the default) | The per-story budget | The budget check before remote stages |
| `model_prices` | **new** | `model_id` (`<id>#<role>` for a second endpoint), `endpoint`, `unit`, `unit_price` (a decimal string), `currency`, `status` (`active`, `deprecated`, `unlisted`), `source` (`fal_pricing_api`, `registry`, `openrouter`), `synced_at`. A row is added only when the price or status changes. | Estimates, computed fal costs, and explaining old estimates |
| `settings` | **new** | `key`, `value` (JSON), `updated_at`: default models per stage, default budget, `recommended` writer models, fal concurrency and media expiry | What the Settings page edits. It takes precedence over `lanternist.toml`. Removing a row falls back to the file. **Never keys.** |
| `uploads` | **new** | `provider`, `asset`, `url`, `expires_at`, `created_at`; unique on `(provider, asset)` | Not uploading the cast sheet once per keyframe |

**Rules, so a later move to another database is a copy, not a rewrite:**
- **Money** is an integer in micro-dollars (`cost_micros`, `budget_micros`). The API converts it to dollars.
- **Prices** are decimal strings, because OpenRouter's per-token prices go to 1e-7 dollars.
- **Types** are SQLAlchemy's own: `JSON`, `Integer`, `String`, `Text`. Timestamps stay naive UTC through `db.now()`, as today. No SQLite-only SQL.
- **Every query** goes through `db.py`.
- **Writes are short.** Concurrent remote steps write their rows from one process, and WAL, which is already on, handles that.

### 1.14 New and changed files

```
src/lanternist/
  keys.py               # key lookup (env → keychain → secrets file), redact()
  prefs.py              # what the Settings page may change, and settings precedence
  llm.py                # LLM protocol; Ollama (moved from writer.py) and OpenRouter
  estimate.py           # prices the uncached steps of a board or render
  registry/             # __init__.py (loader, model_prices overlay, sync_prices) + tts/image/video/audio .toml
  providers/
    openrouter.py       # chat, models list (cached in memory), key info, typed errors
    fal.py              # queue submit/poll/cancel, uploads, downloads, resume from step_runs, pricing sync
    fake.py             # in-process fake fal + OpenRouter for tests and fake mode
  engines/
    base.py             # Engine, Item, ItemResult, Estimate, StepContext (writes step_runs)
    local.py            # klein, Qwen3-TTS and LTX wrapped with today's keys (from pipeline.py)
    fal_image.py  fal_video.py  fal_tts.py  fal_audio.py
  pipeline.py           # stages call engine.run; new ambience stage
  timing.py             # plan_shots
  db.py                 # StepRun, ModelPrice, Setting, Upload models; spend and settings queries
  migrations/versions/0002_runs_and_costs.py
web/src/pages/Settings.tsx     # keys, default models, default budget
web/src/components/ModelPicker.tsx  EstimateBox.tsx
```

---

## 2. Phases

Each phase ends with something that runs end to end. Sizes assume one developer working with Claude Code.

### Phase A: foundations (≈2 days) · built 21 Sep 2026

- [x] `[defaults]`, `[openrouter]` and `[fal]` config sections. `keys.py`, `redact()`, and `keyring` (the Secret Service keychain here).
  - Named `keys.py` rather than `secrets.py`, so it can't shadow Python's `secrets` module.
  - Instead of an httpx hook, `redact()` runs wherever text gets stored: job errors, `step_runs.error` and provider errors.
- [x] Registry loader, the TOML entries for the models in §1.7–1.9, and the local entries with today's engine ids. `lanternist models [--capability] [--sync]`.
  - Kling v3 Pro is left out until its price is checked.
  - Writer models are listed live from Ollama and OpenRouter, with no TOML.
- [x] Alembic `0002_runs_and_costs` and the models in `db.py` (§1.13). It was tested on a copy of the library first, then applied: 2 stories, 7 versions and 9 jobs kept. `model_prices` gained a `status` column.
- [x] `providers/openrouter.py` and `providers/fal.py`, with retries, the semaphore, `step_runs` rows written before polling, the `uploads` cache and lifecycle headers.
  - A user's cancel cancels at fal; a shutdown leaves requests running to be resumed. `Runner.cancel_requested` tells the two apart.
- [ ] Settle the **verify** items against the live APIs: `uv run pytest -m live -s`, about a cent, once both keys are set. It prints:
  - fal's unit names, and whether each matches the registry
  - which response carries `X-Fal-Billable-Units`
  - that the upload flow works
  - that OpenRouter accepts `data_collection`

  Payload deletion for voice clips waits for Phase F.
- [x] `GET /api/providers` and `PUT/DELETE /api/providers/{name}/key`. `GET/PUT /api/settings`, backed by the `settings` table. A Settings page with the keys only. Provider rows in the doctor. `lanternist keys set|clear|status`.
  - The doctor turns a local engine's failure into a warning when no default model uses that engine.
- [x] `providers/fake.py`, wired into tests and fake mode.

**Exit:**
- [x] `lanternist doctor` shows a row for each provider: "no key (optional)" until a key is set.
- [ ] OpenRouter ✓ with its usage and limit, and fal ✓, once keys are set.
- [ ] `lanternist models --sync` needs the fal key. Without it, `lanternist models` lists every entry with its list price and date.
- [x] The existing stories, versions and jobs are all still there after the migration.
- [x] `uv run pytest` passes with no network: 62 tests (was 15).

### Phase B: the writer on OpenRouter (≈1.5 days)

- [ ] `llm.py`, with `Ollama` moved there and `OpenRouter` added: strict schema, reasoning control, empty-content handling, typed errors and reported cost.
- [ ] `Brief.writer`. The lease only when the writer is Ollama. Rewrites use the story's writer.
- [ ] `GET /api/models?capability=writer.chat`: Ollama models (free) first, then the recommended OpenRouter models, then the rest, searchable, each with a price per story from measured token counts.
- [ ] A writer picker on New story, and the cost on the finished job. `lanternist write --writer openrouter/<id>`.
- [ ] Try 3–4 models on the same three ideas (en, es, pt). Keep the best-value ones as `recommended`, and record their token counts for the estimator.

**Exit:**
- Ideas in English, Spanish and Portuguese each give a valid storyboard within ±15% of target length on at least two OpenRouter models, with the cost shown.
- The Ollama path is unchanged.

### Phase C: the engine interface and pictures on fal (≈3 days)

- [ ] `engines/base.py` and `engines/local.py`. Move klein, Qwen3-TTS and LTX behind the interface. The golden-key test proves the cache is unchanged.
- [ ] `fal_image.py`, with klein 9B (text-to-image and edit) and Nano Banana 2 edit. `draw` runs as two waves: the cast sheet, then all keyframes in parallel.
- [ ] `Storyboard.models`. A "Models" panel on the story (pictures for now) with a per-scene re-roll price.
- [ ] Progress lines show fal queue position and in-progress state.

**Exit:**
- Maya's board with fal klein pictures and local narration: the cast is as consistent as the local board (checked by eye).
- A second board is all cache hits. Re-rolling one scene costs one image.
- The existing local stories re-render entirely from cache.

### Phase D: estimate and budget (≈1.5 days)

This phase comes before video on purpose: video is where the money goes.
- [ ] `estimate.py` and `GET …/estimate`, with an `EstimateBox` before "Prepare board" and before "Render": lines per stage, the total, waste, price date, and GPU time for local steps.
- [ ] Budget checks before remote stages. The "Raise budget and continue" flow. A default budget in Settings.
- [ ] Cost so far on the story and in the Library.

**Exit:**
- The estimate for a cached story is $0.
- A render over budget stops before spending and continues from the cache once the budget is raised.

### Phase E: video on fal (≈3 days)

- [ ] `timing.plan_shots` with golden tests. `motion` uses it for every engine, and local LTX gives the same frames as today.
- [ ] `fal_video.py` with the Kling, LTX-fast, Veo and Wan builders: audio off, prompt expansion off, 720p or 1080p. Shots chain on last frames.
- [ ] The `audio.ambience` stage with `fal_audio.py` (MMAudio v2), skipped for models that make their own sound.
- [ ] Cancel versus shutdown on in-flight requests, and resume after a restart.
- [ ] A video-model picker. Per-scene video re-roll with its price.

**Exit:**
- A hybrid Spanish film with 3 Kling scenes and MMAudio ambience.
- A 23 s slot renders as two chained shots, with the waste reported.
- Killing the server mid-stage and restarting resumes without paying again. Cancel cancels at fal.

### Phase F: narration on fal (≈2 days)

- [ ] `fal_tts.py`:
  - Qwen3-TTS: the clone-embedding step, per-chunk requests, and `max_new_tokens` raised.
  - ElevenLabs v3, MiniMax Speech 2.8 HD, and Chatterbox with its 300-character chunks.
- [ ] Voices follow the TTS engine (clips or presets). The Voices page lists presets per engine with a sample line. The languages come from the registry.
- [ ] Run the definition of done at the top of this file.

**Exit:**
- The same Spanish story narrated by fal Qwen3-TTS with the `demo` clone and by an ElevenLabs preset.
- Subtitle cues line up.
- Steps 1–7 of the definition of done pass.

**Total: about 13 working days.**

---

## 3. Risks

| Risk | Mitigation |
|---|---|
| Models differ in input names, defaults and limits | Adapters per family, with limits and defaults in the registry. The live test suite runs each family once. |
| Hidden defaults cost money or change output (audio on, prompt expansion on, a 200-token cap) | Explicit values in every registry entry's `defaults`, and unit tests that assert the request bodies. |
| Clip rounding waste (a 12 s slot billed as a 15 s Wan clip) | Kling and LTX fast bill in 1 s or 2 s steps. The shot planner with a short hold, and waste shown in the estimate. |
| Characters drift on models other than klein | klein 9B on fal is the default: the same model and method as local. Nano Banana 2 is opt-in, and Z-Image (no references) isn't offered for keyframes. |
| Surprise bills | An estimate before every board and render, the per-story budget, and a spending limit on the OpenRouter key. fal's pay-per-request plus the budget check before every remote stage. |
| A restart pays for the same request twice | In-flight records, and shutdown never sends cancel. |
| Public media: fal CDN files are public and kept forever by default | An expiry on every request and upload. Outputs are copied into the store at once. Voice references get one hour. |
| Children's stories sent to third parties | OpenRouter `data_collection: "deny"` (**verify**). Prompts carry character looks, never real names beyond the story's own. |
| Moderation false positives on children's scenes | The error is shown with the provider's reason. The scene can be edited or re-rolled, or its stage switched to local. Nothing is retried automatically. |
| Models get retired or re-priced | `models sync` hides deprecated endpoints. Estimates are stamped with the price date. |
| Licences | Registry `commercial_use` flags. The existing "personal use" note for local klein stays. fal endpoints fall under fal's terms, so check the endpoint page before a commercial use. |

---

## 4. Out of scope

- **Hosted-edition features:** credits and the ledger, Stripe, Clerk, Postgres and R2, webhooks, and fal admin-key billing reconciliation.
- **Voices:** voice-clone consent and watermarking (M4), and MiniMax paid clones.
- **Other media:** music generation, and OpenRouter's image (`/api/v1/images`) and speech (`/api/v1/audio/speech`) endpoints. The engine interface takes those as one more adapter each, later.
- **Scheduling:** per-scene model overrides, and running remote stages alongside local ones or across jobs.
- **Storage:** moving off SQLite, and moving the file step cache into the database. §1.13 keeps the schema ready for both.
- **Still open from MVP Phase 4:** aspect ratios, pace and motion controls, and wind-down. Aspect ratios are best done right after this plan: Veo, LTX and Wan take 16:9 or 9:16 natively, and Kling follows its start image.

## 5. Decisions to confirm

1. **OpenRouter direct** for the writer, not fal's `openrouter/router`. Recommended.
2. **fal for all media in M2**, even though OpenRouter also offers images and speech. fal has klein 9B edit (our cast lock), Qwen3-TTS cloning, video and ambience behind one queue API. Recommended.
3. **Local stays the default for every stage.** Remote models are opt-in per story or in Settings.
4. **A default budget of $5 per story**, and fal media kept for 24 h.
5. **Keys** from the environment, then the OS keychain, then a 0600 file.
6. **Phase order:** writer → pictures → estimate and budget → video → narration. The alternative is video before pictures, if the video quality jump matters most to you.
