# Lanternist M2: OpenRouter and fal.ai

> **Status, 21 Sep 2026: Phases A and B are built and checked against the live APIs.** 91 tests pass offline, and your library is migrated to `0002` (backup in `~/Lanternist/backups/`). Both keys work. A first real video was made end to end: GPT Luna wrote the story and MiniMax H3 Max rendered the shot on fal, for $0.80 as estimated. Stories can now be written by any OpenRouter model with structured output, picked on New story; Claude Opus 5 wrote a Spanish story in the app for $0.21, as estimated. **22 Sep: Phases C–F are built and pass offline** (162 tests): the engine interface; pictures on fal with five models (Nano Banana Pro, Seedream 5.0 Pro and FLUX.2 [max] among them); an estimate and a budget before anything is spent; video on fal with nine models, MiniMax H3 Max and its cheap Turbo among them, with MMAudio ambience; and narration on fal with voices you can hear before choosing. **A first live run through the app** (22 Sep, a throwaway library, $0.43 in all): GPT-5.6 Luna wrote a 1-minute Spanish story, two ElevenLabs voices were heard before Aria was chosen, ElevenLabs narrated it, klein drew the cast sheet and pictures, and MiniMax H3 Max Turbo animated one 15 s scene at 480P in 3 s of inference. Every fal charge matched its estimate within 3% (narration and video exactly), and the cast held between the pictures and the clip. What's left is the rest of the definition of done, live: Kling with MMAudio, a restart and a cancel mid-video, and a clone on fal Qwen3-TTS.
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

`lanternist models sync` reads fal's `GET /v1/models/pricing` (needs the key) and `GET /v1/models` (status, to hide deprecated endpoints) into the `model_prices` table. It adds a row only when a price changes, so past estimates can still be explained. The app runs it at start when the newest row is more than a day old.

**Two prices per model** (learned from the live API):
- **List price** (`price`, with tiers such as audio on or 1080p) comes from each model page, per our unit: a second of video, an image, 1,000 characters. **Estimates use it.**
- **Billing price** (`billing`) is what the pricing API returns: one *base* price per endpoint, per fal's own billing unit. Veo's is its audio-on price. LTX fast is billed at $0.01 per "unit". Kling's is $0.14, which matches none of its listed prices. The **actual cost** of a request is its billable units × the billing price.
- **Drift:** the sync never overwrites a list price. When fal bills in our unit but its price matches no list tier, `models --sync` flags it, so the model page can be re-read.

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
recommended = ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5", "deepseek/deepseek-v4.1-flash", "openai/gpt-5.6-luna"]   # pinned in the writer picker; from the Phase B trials
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
  - Read `X-Fal-Billable-Units` from the result response (confirmed live), then multiply by the endpoint's billing price (§1.2), not its list price.
  - This lands close to the real cost without the admin-only billing APIs, which stay out of scope.
- **Privacy:**
  - Every submit and upload carries an expiry (`media_ttl_hours`), because fal CDN media is otherwise public and kept forever.
  - Voice references get one hour.
  - The blueprint lists payload deletion (`DELETE /v1/models/requests/{id}/payloads`) for voice samples, which fal otherwise keeps for 30 days (**verify**).

### 1.7 Pictures on fal

Every fal picture model draws the cast sheet from text (`endpoints.text_to_image`, 1024×1024), then every keyframe at once on its edit endpoint with the cast sheet as the reference. The cast sheet is uploaded once per story: keyframes running together share one upload.

| Model | Size | Seed | List price (22 Sep) | A keyframe | Notes |
|---|---|---|---|---|---|
| FLUX.2 [klein] 9B (`fal-ai/flux-2/klein/9b[/edit]`) | `image_size` | yes | $0.011/MP in and out; cast sheet $0.006/MP | $0.034 | Same model as local, so the lock behaves the same. The cheapest good choice. |
| Nano Banana 2 (`fal-ai/nano-banana-2[/edit]`) | `aspect_ratio` + `resolution` | yes | $0.08 at 1K; 0.5K ×0.75, 2K ×1.5, 4K ×2 | $0.12 at 2K | Follows long prompts and references well. |
| **Nano Banana Pro** (`fal-ai/nano-banana-pro[/edit]`) | `aspect_ratio` + `resolution` | yes | $0.15 at 1K or 2K, $0.30 at 4K | $0.15 | Google's best: the closest match to the cast sheet. |
| **Seedream 5.0 Pro** (`bytedance/seedream/v5/pro/...`) | `image_size` | **no** | $0.0675 up to 1536², $0.135 above; $0.0045 per reference after the first | $0.0675 | ByteDance's best; rich detail. |
| **FLUX.2 [max]** (`fal-ai/flux-2-max[/edit]`) | `image_size` | yes | $0.07 for the first MP, $0.03 per MP after, references included, rounded up (**verify** the rounding) | $0.16 | Black Forest Labs' best, klein's big sibling. |

- **Quality.** A model with a `quality` entry (Nano Banana's `resolution`) lets the story pick it; each option's price is a `price.tiers` entry. `Storyboard.models.image_quality` holds the choice, and an option the model doesn't offer falls back to its default.
- **Safety.** klein returns a black picture when its checker trips, with `has_nsfw_concepts: [true]`. The adapter turns that into an error that names the scene, instead of storing a black frame.
- **Seeds and re-rolls:** models that take a seed get the scene seed. For models without one, a re-roll still changes the step key, so it still draws a new picture.
- **Not offered:** GPT Image 2 and 2.5 are billed per token with a quality setting, so an estimate before the run would be a guess. They can come later as their own family.

### 1.8 Video on fal

**The shot planner** replaces `timing.shot_lengths`: `timing.plan_shots(clip_seconds, durations, hold_max)`.
- It picks the cheapest set of billable lengths that covers the clip, allowing a short freeze on the last frame at the end. `video_clip`'s `tpad` already does that freeze.
- The freeze defaults to 1 s: `[render] hold_max = 1.0`, which covers the crossfade handle, where most of it sits under the fade. The blueprint's 2 s is the upper setting, because 2 s frozen out of a 7 s clip shows.
- Ties go to fewer shots, because every chain is a visible seam.
- It returns the shots, the seconds paid for and the seconds wasted. The estimator shows the waste.
- Local LTX keeps its exact `8k+1` frames.

| Model | Billable lengths | Price (list, 22 Sep) | Notes |
|---|---|---|---|
| **MiniMax H3 Max Turbo** (`minimax/h3-max-turbo/image-to-video`) | 5–15 s, any whole second | $0.0125/s at 480P, $0.02 at 768P, $0.04 at 1080P until 30 Sep; then double | **The cheapest good video: a whole film for cents at 480P, for trying the flow.** A seed. `prompt_expansion_mode` defaults to "balanced", MiniMax's rewrite of the prompt into H3's own shot format: kept on since the quality review (§6). No audio switch, but its quiet sound bed serves as ambience. |
| **MiniMax H3 Max** (`minimax/h3-max/image-to-video`) | 5–15 s | $0.025/s at 480P, $0.04 at 768P, $0.08 at 1080P until 30 Sep; then double | fal's post-trained H3: strong prompt following. Same inputs as Turbo. |
| Kling v3 Standard | "3"–"15" s, any whole second | $0.084/s with audio off | `start_image_url`. No seed or size input: it follows the image. **`generate_audio` defaults to true: send false.** |
| **Kling v3 Pro** | "3"–"15" s | $0.112/s with audio off | Kling's best motion; same inputs as Standard. |
| **Veo 3.1** | "4s", "6s", "8s" | $0.20/s without audio at 720p or 1080p, $0.40 at 4k | Google's best. Long slots need 2 shots. |
| Veo 3.1 fast | "4s", "6s", "8s" | $0.10/s without audio | Premium look. Long slots need 2 shots. |
| **Wan 3.0** (`alibaba/wan-3.0/image-to-video`) | 2–30 s | $0.05/s at 480p, $0.10 at 720p, $0.20 at 1080p, sound included | `start_image_url`, no seed. Any length to 30 s, so almost nothing is trimmed. `enable_prompt_expansion` defaults to true: send false. |
| LTX-2.5 fast (`lightricks/ltx-2.5/image-to-video/fast`) | 6, 8 … 20 s | $0.09/s at 720p, $0.13/s at 1080p, **audio included** | Same model as local, with its own ambience, so no MMAudio needed. 1440p and 4K aren't offered: they stop at 10 s. |
| Wan 2.6 flash (`wan/v2.6/image-to-video/flash`, no `fal-ai/` prefix) | "5", "10", "15" | $0.025/s at 720p with audio off | Cheap. **`enable_prompt_expansion` defaults to true: send false**, or the character lock gets rewritten. |

- **Launch prices end on a date.** A registry price can carry `until` and `then`: H3's list the launch price until 30 Sep and the regular one after, so estimates and budgets stay right on 1 Oct with no change. `models --sync` flags any other drift.
- **Not offered:** Seedance 2.5 is billed per token and costs about $0.47/s at 720p, and Gemini Omni Flash has no audio switch listed. Both can come later as their own families.

Other details:
- **Prompt:** `prompts.video()` works as it is, and `VIDEO_NEGATIVE` goes where the model takes a negative prompt.
- **Resolution:** a story picks it (the model's `quality`), with each option priced on the picker. The defaults: 1080p where it costs the same (Veo), else 720p or 768P. The clip step upscales to the render size.
- **Audio off by default.** Narration is separate, and audio costs 50–100% more.
- **Ambience comes from the `audio.ambience` step:**
  - `fal-ai/mmaudio-v2` gets the scene's raw clip plus `scene.sound` and returns the same video with sound muxed in, at $0.001/s.
  - Its output replaces the motion asset, so `video_clip` and the mix are untouched.
  - It's skipped for models whose registry entry says `audio = "ambience"` (local LTX, LTX fast, H3, Wan 3.0).
  - **Changed from the first plan:** MMAudio is the default (`defaults.ambience`), since it only ever runs for a video model with no sound of its own, which is already a fal model. Only its sound is kept: it's muxed under our own copy of the clip, so a clip longer than MMAudio's 30 s isn't cut.
- **Concurrency:** all video scenes go out at once, up to `max_concurrency`. A hybrid film's video stage takes about as long as its slowest clip, instead of the sum of all of them.

### 1.9 Narration on fal

Subtitle timing stays exact because nothing downstream changes:
- Each chunk from `text.tts_chunks` is one request, and a scene's chunks run concurrently.
- The chunks are joined with `chunk_gap` into one wav per scene, plus the `chunk_durations` the local worker returns today.
- The chunk limit comes from the registry: 300 characters for Chatterbox.

| Engine | Voice | Price | Notes |
|---|---|---|---|
| fal Qwen3-TTS 1.7B | Clone of `voices/<name>.wav`, or one of 9 presets | $0.09 per 1k chars | Two calls. `qwen-3-tts/clone-voice/1.7b` turns the clip and its transcript into a speaker embedding. That's a cached step keyed by the voice's sha, with the `.safetensors` kept in the store. Each chunk then passes `speaker_voice_embedding_file_url`. **`max_new_tokens` defaults to 200: raise it**, or long chunks may be cut off. |
| ElevenLabs v3 | One of 21 presets (`voice`; the names in fal's schema, plus "Rachel") | $0.10 per 1k chars | `language_code` (ISO 639-1). No cloning from a clip. |
| MiniMax Speech 2.8 HD | One of 17 presets (`voice_setting.voice_id`, from fal's schema) | $0.10 per 1k chars | Send `output_format: "url"` (the default is hex), and `language_boost`. Its $1.50 clone is left for M4. |
| Chatterbox Multilingual | Clone: the reference clip's URL as `voice` | $0.025 per 1k chars | 300 characters per request, 23 languages. |

The language check in `narrate()` (today "not supported by Qwen3-TTS") becomes each engine's `languages` list in the registry, and the pickers filter on it.

**Hearing a voice before choosing it** (added to the plan, for value): every voice picker (New story, the Script step, the Voices page) has a Listen button on each voice.
- A preset's sample is the language's sample line (`text.SAMPLES`), narrated like any scene and cached under the same kind of key, so each voice is made once per language, about a cent each; the button shows that price until it's made.
- A recording plays itself, and for a model on fal that clones, "Listen" plays it as that model says it.
- A sample is a job with no story (migration `0003` lets `jobs.story_id` be empty) in a fast lane of its own beside the queue: a few seconds on fal, never the GPU, so it never waits behind a render. Local narrators aren't sampled: they'd take the GPU, and their voice is the recording.

### 1.10 Estimate, budget and cost

- **Every step that runs** writes a `step_runs` row (§1.13) with its units, cost and time. That includes local steps, whose GPU-seconds calibrate the local estimates, and each writer call.
  - OpenRouter costs are `reported`.
  - fal costs are `computed` as billable units × the endpoint's billing price from the pricing API.
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
| Writer | Claude Opus 5 (GPT-5.6 Luna: under a cent) | ≈ $0.21 (measured in Phase B) |

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
- [x] Settle the **verify** items against the live APIs (`uv run pytest -m live -s`, 21 Sep, under a cent):
  - **OpenRouter:** a strict-schema request with `data_collection: deny` is accepted, and `usage.cost` comes back. The cheapest structured-output model (Mistral Nemo) answered through DeepInfra.
  - **fal pictures:** `X-Fal-Billable-Units` is on the **result** response. A 512×288 klein picture billed 0.453 megapixels, so fal's own unit count is what to trust. Results also carry `has_nsfw_concepts`.
  - **fal uploads:** the two-step upload works. Files land on `v3b.fal.media`.
  - **fal's pricing API:** it returns one base price per endpoint, which isn't always the list price. That led to the two-price design in §1.2.
  - **Wan 2.6 flash:** the page's $0.05/s is *with* audio. We send audio off, at $0.025/s, now in the registry.
  - **Billing and usage APIs:** they need an admin key, as expected. A normal key gets 403.
- [x] **How fal bills options, settled by a real clip** (MiniMax H3 Max text-to-video, 10 s at 1080P):
  - fal's base price for the endpoint is $0.025 per "seconds", which is the 480p rate.
  - The clip billed **32 billable units**, so 32 × $0.025 = **$0.80**. That's exactly the listed 1080p price ($0.08/s × 10 s) and exactly our estimate.
  - Options scale the *units*, not the price. Actual cost = billable units × base price, as §1.2 now does. Kling's $0.14 base fits the same rule, so its drift flag is expected.
- [x] **First end-to-end generation**, run as a one-off script through the new clients and logged in `step_runs` (`~/Lanternist/films/tests/luna-h3-max*.mp4`):
  - **Writer:** GPT Luna (`openai/gpt-5.6-luna`) at reasoning effort `high` wrote the story and the shot prompt. 295 tokens in, 786 out (351 of them reasoning), $0.001, 7 s.
  - **Video:** H3 Max rendered 10 s of 1080p in 14 s of wall time.
  - **Clip format:** H.264 (Constrained Baseline), 24 fps, 1920×1080, with the index at the end of the file. Store fal clips with `-movflags +faststart` so they play in the browser straight away.
- [x] **fal's pricing API** 404s a whole batch when one endpoint in it has no price. `Fal.pricing` now asks one at a time after a 404.
- Payload deletion for voice clips waits for Phase F.
- [x] `GET /api/providers` and `PUT/DELETE /api/providers/{name}/key`. `GET/PUT /api/settings`, backed by the `settings` table. A Settings page with the keys only. Provider rows in the doctor. `lanternist keys set|clear|status`.
  - The doctor turns a local engine's failure into a warning when no default model uses that engine.
- [x] `providers/fake.py`, wired into tests and fake mode.

**Exit:**
- [x] `lanternist doctor` shows a row for each provider: "no key (optional)" until a key is set.
- [x] OpenRouter ✓ with its usage and limit ($250 limit on the key), and fal ✓.
- [x] `lanternist models --sync` recorded 13 fal endpoints in `model_prices`. `lanternist models` shows each list price beside what fal bills.
- [x] The existing stories, versions and jobs are all still there after the migration.
- [x] `uv run pytest` passes with no network: 63 tests (was 15).

### Phase B: the writer on OpenRouter (≈1.5 days) · built 21 Sep 2026

- [x] `llm.py`, with `Ollama` moved there and `OpenRouterLLM` added: strict schema, reasoning control, empty-content handling, typed errors and reported cost.
  - **Parameters.** The model list's `supported_parameters` is the *union* over a model's providers. Claude Opus 5 is the proof:
    - Its structured-output providers (Anthropic, Claude on AWS) take no `temperature`, and the one that does (Azure) has no structured output.
    - A strict schema plus a temperature therefore found no provider (404).
    - The writer now reads `/models/{id}/endpoints` (public, cached for a day). With a schema, it sends `reasoning`, `max_tokens` and `temperature` (in that order of need) only when one structured-output provider takes all of them. Without a schema, providers ignore what they lack. If the provider list can't be read, it falls back to the union and logs a warning.
  - **Reasoning.** Effort is per story. `None` means the model's own default. A requested effort is clamped to the nearest one the model supports ("none" on a mandatory-reasoning model becomes its lowest).
  - **Token limit.** `max_tokens` is 32k, capped by the model's limit. On an empty "length" stop, the writer retries once with twice the room. The wasted attempt is still paid for, so its tokens and cost are counted. If there's no more room, or the retry stops too, the call fails and its `step_runs` row keeps what OpenRouter billed.
  - **Code fences.** Replies wrapped in a code fence, or with `<think>` blocks, are unwrapped before validation.
- [x] `Brief.writer` and `Brief.effort`, validated.
  - `Storyboard.models` (`writer`, `writer_effort`) records who wrote the story, and rewrites use that writer, not the current default.
  - Only Ollama takes the GPU lease.
  - Jobs now run with the settings saved in the app, so `defaults.writer` from Settings applies.
- [x] Every writer call is a `step_runs` row (stage `write`): tokens in, out and reasoning, effort, upstream provider, wall time, and OpenRouter's reported cost. Failed and cancelled calls are recorded too, with what OpenRouter billed for them. A cost it didn't report is `null` (`cost_source` "none"), as for local models.
  - Write and rewrite jobs return `{writer, cost_usd, calls, tokens_in, tokens_out}`.
  - The job log shows each pass's cost.
- [x] `GET /api/models?capability=writer.chat` lists the writers:
  - Local Ollama models first (embedding models hidden).
  - Then `openrouter.recommended`, then the rest. `:batch` and `:free` variants are hidden.
  - Each model shows its per-token prices, supported efforts and a cost per minute of story. The cost comes from, in order of preference:
    1. token counts measured on your finished write jobs
    2. the trial counts below
    3. the trial median
  - Only the writer's list is served so far; the media stages' lists come with their pickers in Phase C (the picture list did).
- [x] The writer picker on New story: search, groups (on this machine, then OpenRouter), a price for the chosen length, and a reasoning select when the model has efforts. OpenRouter models are disabled until a key is set.
  - The story header shows "written by … for $X". `GET /api/stories/{id}` sends the writer and its cost, summed from `step_runs`, so failed attempts count.
  - `lanternist write --writer openrouter/<id> --effort <e>` prints the calls, tokens and cost.
  - `lanternist models --capability writer.chat` uses the same catalog.
  - `POST /api/stories` refuses an OpenRouter writer when there's no key.
- [x] Fake mode now fakes Ollama too (`/api/chat`, `/api/tags`), so tests and UI work never touch the local model. The fake storyboard has one scene per numbered paragraph, so a full write succeeds offline.
- [x] **Trials:** 5 models × 3 ideas (en, es, pt), 3-minute bedtime stories for ages 5–8, plus Gemini and Sonnet again at `low` effort. That's 24 stories, $2.26 in total. That includes $0.39 for the story pass of the three Opus runs that then failed on the parameter bug above.
  - **Every story was valid and within ±15% of its target length.** Opus 5 hit the exact target on all three ideas.
  - Times are per story. Tokens are per minute of story, both passes, at the model's default effort unless the row says otherwise.

    | Model | Tokens in / out | Cost per story | Time | Verdict |
    |---|---|---|---|---|
    | Claude Opus 5 | 921 / 2,613 | $0.21 | 95 s | Best by a distance: specific, inventive detail, a real wind-down, idiomatic Spanish and Brazilian Portuguese |
    | Claude Sonnet 5 (default: high) | 939 / 6,012 | $0.19 (up to $0.30) | 143 s | Very good but wordy; high reasoning triples the cost |
    | Claude Sonnet 5 (low) | 1,706 / 1,672 | $0.06 | 58 s | Same quality as high; runs a length revision more often |
    | DeepSeek V4.1 Flash | 649 / 4,727 | $0.012 | 175 s | Simple, correct, good for small children; Portuguese comes out European; slow |
    | Gemini 3.8 Flash (default: medium) | 384 / 7,866 | $0.09 (up to $0.14) | 124 s | Stilted Spanish and Portuguese, heavy on adjectives; reasoning spikes even at low (17k tokens) |
    | GPT-5.6 Luna | 507 / 1,855 | $0.007 | 53 s | Cheapest and fastest; occasional slips ("el mundo quiera") |
  - **Reasoning is most of the output, and it drives the cost.** A lower effort is usually the better deal for the writer.
  - **Recommended** (the new built-in `openrouter.recommended`): Opus 5, Sonnet 5, DeepSeek V4.1 Flash and GPT-5.6 Luna. Gemini 3.8 Flash is left out.
  - Their token counts are in `llm.TRIAL_TOKENS_PER_MINUTE`, and the median (700 in / 2,900 out per minute) prices every other model.
  - Local qwen3.8 is unchanged: 20 s for a 1-minute story, under the GPU lease.

**Exit:**
- [x] Ideas in English, Spanish and Portuguese each gave a valid storyboard within ±15% of target length on five OpenRouter models, with the cost shown.
- [x] A story written in the app on Opus 5, in Spanish: 13 scenes and 4 characters, $0.214 against a $0.21 estimate, 99 s. The cost is shown on the story.
- [x] The Ollama path is unchanged. It is tested against the fake, and a real 1-minute story took 20 s.
- Not checked live: a scene rewrite on an OpenRouter model. It is covered offline, and it uses the same strict-schema path as the storyboard.

### Phase C: the engine interface and pictures on fal (≈3 days) · built 22 Sep 2026

- [x] `engines/base.py` and `engines/local.py`. Move klein, Qwen3-TTS and LTX behind the interface. The golden-key test proves the cache is unchanged.
  - Every stage, ffmpeg's clips and mix too, now runs through one `Pipeline._stage`: serve the cache hits, run the misses as one batch, store each output as it lands. The five copies of that loop are gone.
  - An item can wait on another in its batch (`Item.after`): keyframes on a cast sheet drawn in the same job. A local engine keeps one model load for both; a remote one runs them as two waves.
  - `test_local_step_keys_are_unchanged` pins the keys computed on `main` before the change.
  - Every step a local model makes is a `step_runs` row with its GPU seconds, for calibrating the estimates.
- [x] `fal_image.py`, with klein 9B (text-to-image and edit) and Nano Banana 2, plus three top-tier models not in the first plan: **Nano Banana Pro, Seedream 5.0 Pro and FLUX.2 [max]** (§1.7). `draw` runs as two waves: the cast sheet, then all keyframes in parallel.
  - When one keyframe fails (moderation, say), the others still finish and are stored, since they're paid for; then the stage fails naming the scene.
  - What fal bills is refreshed at most once a day, before the first remote stage of a job (`registry.ensure_synced`), and read at request time, so a computed cost uses today's billing price.
- [x] `Storyboard.models` (it holds the writer since Phase B) gains the picture model and its quality. A "Models" panel on the Board step (pictures for now) with the price of each redraw on its button. `GET /api/models?capability=image.keyframe` lists every model with its price per picture at each quality, priced by the engines' own estimates.
- [x] Progress lines show fal queue position and in-progress state.
  - Progress rows now carry their label from `pipeline.LABELS` (moved from `jobs.py`), and the web app shows them in the order they ran: its own stage list is gone.

**Exit:**
- [ ] Maya's board with fal klein pictures and local narration: the cast is as consistent as the local board (checked by eye). A live board of another story held its cast well (22 Sep); Maya's is still to do.
- [x] A second board is all cache hits. Re-rolling one scene costs one image (`test_a_board_on_fal_draws_the_cast_first_and_uploads_it_once`, offline).
- [x] The existing local stories re-render entirely from cache (the golden keys).

### Phase D: estimate and budget (≈1.5 days) · built 22 Sep 2026

This phase comes before video on purpose: video is where the money goes.
- [x] `estimate.py` and `GET …/estimate`, with an `EstimateBox` before "Prepare board" and before "Render": lines per stage, the total, waste, price date, and GPU time for local steps.
  - It walks the same items the stages build (`Pipeline.narration_items`, `cast_item`, `keyframe_item`, `motion_items`), so it prices exactly the steps that would run.
  - "Prepare board" and "Approve and render" carry their price on the button; so does each scene's redraw.
  - Every board and render job keeps the estimate shown before it (`jobs.estimate`, in micro-dollars); the API shows every `*_micros` field as `*_usd`.
- [x] Budget checks before remote stages. The "Raise budget and continue" flow. A default budget in Settings.
  - The check runs in `Pipeline._stage` before a remote engine's batch: the story's spend so far plus that batch's estimate must fit. Otherwise the job fails with "needs $X more" and a structured `result.budget`, and the story page offers "Raise the budget to $Y and carry on" (the next half dollar that fits).
  - Settings gained "Defaults for every story": the default picture model and the default budget. A story's own budget is set, or handed back to Settings, in the estimate box.
- [x] Cost so far on the story and in the Library.

**Exit:**
- [x] The estimate for a cached story is $0.
- [x] A render over budget stops before spending and continues from the cache once the budget is raised (tested offline, and checked by hand in the app in fake mode).

### Phase E: video on fal (≈3 days) · built 22 Sep 2026

- [x] `timing.plan_shots` with golden tests. `motion` uses it for every fal engine; local LTX keeps its equal shots and exact frames (the golden keys).
  - A range of whole seconds (Kling 3–15, Wan 3.0 2–30) is solved directly; a short list (Veo's 4, 6, 8) by trying the combinations. Three 8 s shots beat two 15 s ones for a 24.5 s slot on a model billing only those.
- [x] Add MiniMax H3 Max (`minimax/h3-max/image-to-video`, plus the cheaper `h3-max-turbo`) to the registry:
  - Durations are 5–15 s, with a seed and a resolution (480P, 768P, 1080P) the story picks.
  - It has no audio switch, yet it returns an audible track (−27 dB mean in our test): it's treated as the scene's ambience.
  - Its launch price doubles after 30 Sep, which the registry now says with `until` and `then`.
  - Also added: Kling v3 Pro, Veo 3.1 and Wan 3.0 (§1.8).
- [x] `fal_video.py` with the Kling, LTX-fast, Veo and Wan builders (and H3 and Wan 3.0): audio off, prompt expansion off, the story's resolution. Shots chain on last frames.
  - Each shot is a step of its own, so a scene that fails halfway doesn't pay again for the shots it made. Clips are stored with their index at the front, so the browser plays them at once.
  - When one scene fails, the others still finish and are stored before the stage reports it.
- [x] The `audio.ambience` stage with `fal_audio.py` (MMAudio v2), skipped for models that make their own sound, and for scenes with no sound line.
- [x] Cancel versus shutdown on in-flight requests, and resume after a restart (tested at the pipeline level: a stopped render's requests are polled again, not paid again; a user's cancel cancels them at fal).
- [x] A video-model picker and an ambience picker on the Board, and the video and ambience defaults in Settings. Per-scene video re-roll with its price ("New take · $0.07", `Scene.video_seed`, so the picture stays), and "Watch" for each animated scene.

**Exit:**
- [ ] A hybrid Spanish film with 3 Kling scenes and MMAudio ambience. Offline it passes (`test_a_hybrid_film_on_kling_with_ambience`); the live run is pending.
- [x] A 23 s slot renders as two chained shots, with the waste reported.
- [x] Killing the server mid-stage and restarting resumes without paying again. Cancel cancels at fal (offline; to check live).

### Phase F: narration on fal (≈2 days) · built 22 Sep 2026

- [x] `fal_tts.py`:
  - Qwen3-TTS: the clone-embedding step, per-chunk requests, and `max_new_tokens` raised.
  - ElevenLabs v3, MiniMax Speech 2.8 HD, and Chatterbox with its 300-character chunks.
  - Each chunk is a cached step of its own, and a reference recording stays on fal for an hour (`fal.voice_ttl_hours`).
- [x] Voices follow the TTS engine (clips or presets). The Voices page lists presets per engine with a sample line. The languages come from the registry.
  - `Storyboard.models.tts` picks a story's narrator on the Script step; switching keeps the voice when the new model has it, else starts on its first. The default narrator is in Settings.
  - Every voice can be heard before it's chosen (§1.9).
- [ ] Run the definition of done at the top of this file. Needs live runs on your keys.

**Exit:**
- [ ] The same Spanish story narrated by fal Qwen3-TTS with the `demo` clone and by an ElevenLabs preset (offline, both paths pass; live pending).
- [x] Subtitle cues line up (`test_a_board_narrated_by_an_elevenlabs_preset`).
- [ ] Steps 1–7 of the definition of done pass (live).

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

---

## 6. Film quality review (22 Sep 2026)

Outside the plan above: a review of what the flow makes, film by film, with the fixes it led to on
`feat/film-quality`. Four films of 3½–4¼ minutes were made and judged frame by frame, with the
narration transcribed back by Whisper and the loudness measured (`~/Lanternist-lab/films`).

| Film | Writer | Pictures | Video | Notes |
|---|---|---|---|---|
| The Kite and the Old Windmill (baseline) | Opus 5, the old storyboard pass | klein, whole cast sheet | local LTX | 19 shots of 13 s |
| The Runaway Red Kite | Opus 5, shots, objects, places | klein, portraits | local LTX | 39 shots |
| Los faroles de la primera nevada | the same, in Spanish | klein, portraits | H3 Max Turbo 480P, and local LTX | 34 shots; $3.19 of video, as estimated |

**What spoiled the baseline, and what changed:**

| Finding | Change |
|---|---|
| Every picture got the whole cast sheet, so characters who weren't in a scene walked in (8 of 19 pictures) | Each character is drawn alone from the cast sheet; a picture gets only the portraits of who is in it, named "image 1", "image 2" as FLUX.2 asks (`Storyboard.portraits`) |
| "The red kite" came out as the bird in 8 of 11 pictures; "the sail" as a ship's | Objects the story turns on join the cast (`CastMember.kind`), places get looks (`Storyboard.places`), each restated in every prompt |
| One 13 s shot per paragraph: slow, and video drifts off its subject that long | The writer cuts each paragraph into one to three shots on sentence boundaries; they cut to each other (`Scene.continues`), paragraphs crossfade |
| The writer's "the children" drew extra children | Every character in a shot is named, every time |
| The film played at −25 LUFS; LTX's sound bed swung 31 dB between clips | Each clip's sound is levelled against the narration; the film is set to −16 LUFS in two passes (`mix@2`) |
| H3 ignored a "holds still" camera with our prompt sent as is | H3 rewrites its prompt (`prompt_expansion_mode = "balanced"`), and the clip's record keeps what it wrote |

**Measured after:** the kite, the cast and the places held across all 39 and 34 pictures; films
at −16.1 LUFS; narration word-perfect (one spelling in 600 words). H3 Max Turbo beat local LTX on
the same pictures: it followed the camera direction, and morphed nothing where LTX melted lanterns
together and merged a jug into a mug. It made 4¼ minutes of video in 90 s.

**Still open:**
- A character drawn twice in about one picture in ten, even told the count. A vision model catches
  it (next item).
- A small character drawn alone (a fox cub) loses its scale, and scenes then draw it adult-sized.
- The demo voice narrates at about 185 words a minute against the 150 the writer plans for, so films
  run 10% short. Measuring each narrator's pace would fix the length.
- Next, from similar products: a music bed ducked under the voice (ACE-Step, locally or on fal), and
  checking clips as well as pictures.
