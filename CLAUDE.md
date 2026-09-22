# Lanternist

A one-line idea in, a narrated story film out. An LLM writes a storyboard; TTS narrates it; an image
model draws a cast sheet and one keyframe per scene; a video model animates the scenes marked video;
ffmpeg mixes the film. Every stage runs locally on one 32 GB GPU, or remotely (OpenRouter for the
writer, fal.ai for media) with the user's own keys.

- `README.md`: what it does and how to run it.
- `MVP_PLAN.md` (done) and `M2_PLAN.md` (in progress): the design, the decisions and why, and the phase
  checklists. Read the relevant section before changing a subsystem. When a PR finishes a plan item,
  tick its box and update the status line at the top.

## Commands

```bash
uv sync && pnpm --dir web install        # once
scripts/check                            # every gate CI runs; must pass before a PR
scripts/check fix                        # apply formatters and safe lint fixes
scripts/check python|web|dup             # one group
uv run pytest -k name                    # a few tests
LANTERNIST_FAKE_ENGINES=1 uv run lanternist serve   # the whole app on :8420, no GPU, no keys
pnpm --dir web dev                       # Vite on :5173, proxying /api to :8420
```

Ask before running `pytest -m live` (spends money on the user's keys) or `pytest -m gpu` (evicts the
user's models and takes the GPU for minutes). Neither runs by default.

## Map

| Where | What |
|---|---|
| `storyboard.py` | The Storyboard: the one document the writer makes, the editor edits and the renderer reads |
| `writer.py` | Idea to storyboard in two passes (prose, then structured prompts) |
| `prompts.py` | Every picture and video prompt, with the character lock |
| `pipeline.py` | The stages (`narrate`, `draw`, `motion`, `clips`, `mix`), each cached and batched through `_stage` |
| `store.py` | Content-addressed assets and the step cache (plain files) |
| `timing.py`, `text.py` | Timeline, shot split, subtitle cues; sentence splitting and TTS chunks |
| `engines/` | The engine interface (`base.py`), local and fal engines, which engine runs a model (`catalog.py`), ffmpeg, ComfyUI/LTX, the worker runner, the fake engines |
| `voices.py` | The narrator's reference recordings |
| `workers/` | Scripts that run *inside other venvs* (Qwen3-TTS, klein) |
| `gpu.py` | The GPU lease: evict other models, wait for free VRAM |
| `providers/` | OpenRouter and fal clients, and in-process fakes of both |
| `registry/` | Every model the app offers, with limits and prices (TOML) |
| `db.py`, `migrations/` | SQLite through SQLAlchemy; Alembic migrations |
| `estimate.py` | What a board or render would cost, before it runs; the budget check uses the same prices |
| `jobs.py` | The in-process job queue and progress snapshots |
| `api/app.py` | FastAPI: REST, SSE progress, the built web app |
| `keys.py`, `prefs.py`, `config.py` | API keys; settings saved in the app; `lanternist.toml` |
| `web/src/` | React + TypeScript; `api.ts` is the only place that calls the backend |

## Invariants

Breaking one of these corrupts a user's library, spends their money or leaks their keys. Each has
a rule file under `.claude/rules/` with the details.

1. **A step key hashes everything that decides the step's output, and nothing else.** Adding a field
   to a key re-renders every existing story. When output changes on purpose, bump the engine's `@N`.
2. **Only local engines take the GPU lease**, one stage at a time. A remote stage never touches it.
3. **Workers import only the standard library and their own venv.** They cannot import `lanternist`.
4. **API keys go only to their own provider.** Never in SQLite, logs, job errors or the browser. Any
   text we store passes through `keys.redact()`.
5. **Money is integer micro-dollars** (`db.to_micros`); prices are decimal strings. No floats for cost.
6. **Every query goes through `db.py`**, using portable SQLAlchemy types. A model change ships with
   its migration.
7. **Every fal request and upload carries an expiry**, and its `step_runs` row is written before
   polling, so a restart resumes instead of paying twice. Only a user's cancel cancels at fal.
8. **Fake mode covers every feature.** New remote code goes through `providers.transport()`, so the
   fakes exercise the real client.
9. **Narration is in the story's language; visual, motion and sound prompts are English.** The
   character lock lives in `prompts.py`, never in an LLM instruction.

## One source for each fact

Each fact below has one home, and everything else reads it from there. Before adding a constant,
label, list or type, search for an existing one. If the frontend needs a backend fact, the API
sends it; the frontend doesn't hard-code it.

| Fact | Home | Read by |
|---|---|---|
| Storyboard shape | `storyboard.py` | `lanternist schema`; `web/src/api.ts` mirrors it by hand |
| Languages | `text.LANGUAGES` | `/api/options` |
| Styles, audiences, kinds | `writer.py` | `/api/options` |
| Story length: words per minute and per scene | `writer.WPM`, `Brief.target_words`, `Brief.scenes` | the writer |
| Stage names and labels | `pipeline.LABELS` | progress snapshots, the estimate, budget messages |
| Models, limits, prices | `registry/*.toml` | pickers, estimator, doctor, adapters |
| Config defaults | `config.py` | documented in `lanternist.example.toml` (keep it in step) |
| Settings the app may change | `prefs.EDITABLE` | Settings page |
| Providers and their env vars | `keys.PROVIDERS` | CLI, API, doctor |
| ffmpeg command lines | `engines/ffmpeg.py` | pipeline |
| Quality gates | `scripts/check` | CI, `/check` |

Known duplication, to remove, not to copy (delete a line when it's fixed):
- `web/src/pages/NewStory.tsx` hard-codes words per minute and words per scene (`writer.WPM`,
  `WORDS_PER_SCENE`), so its estimate is wrong outside English.
- `web/src/api.ts` `LANGUAGE_NAMES` and `STYLE_NAMES`, and `NewStory.tsx` `AUDIENCE_NAMES` repeat
  backend lists.
- `app.options()` lists the cameras again instead of reading `storyboard.Camera`.
- `api/app.py` and `jobs.py` build queries inline instead of calling `db.py`.

## How code here is written

Read the neighbouring code before writing, and match it.

- **Plain and compact.** Short functions, early returns, comprehensions where they read well. No
  wrappers, managers or base classes for a single use. Build the second case when it exists, not before.
- **Docstrings say why.** A module starts with a docstring about its job and the decision behind it.
  A comment explains a non-obvious reason ("klein wants sides divisible by 16"), never what the next
  line does.
- **Errors are sentences a user can act on.** Say what failed and what to do: "no fal key: add one in
  Settings, or run `lanternist keys set fal`". Each module raises its own error class.
- **No slop.** No commented-out code, dead code, unused parameters, `print` debugging, TODOs without
  a plan item, placeholder names (`data2`, `helper`, `utils`), defensive `try` around code that
  can't fail, or broad `except` without a `# noqa: BLE001 - reason`. No comment restating the code.
  No change outside the task.
- **Types.** Modern syntax (`X | None`, `list[str]`), Pydantic at boundaries (API, config, TOML, LLM
  output), dataclasses inside. mypy runs in CI. The modules listed under `[[tool.mypy.overrides]]` in
  `pyproject.toml` are exempt for now: when you touch one, make it pass and remove it from the list.
  Never add one.
- **Never weaken a gate to get green.** No new `noqa`, `type: ignore`, eslint-disable, ignore rule or
  exemption without a reason in the same line, and say so in the PR.

## Shipping work

1. Branch from `main`: `feat/…`, `fix/…`, `chore/…`. One concern per PR. A mechanical reformat or
   rename goes in its own commit or PR.
2. Tests for what changed: a bug fix adds the test that would have caught it.
3. `scripts/check` passes locally.
4. `/self-review` against this file and the rules, then fix what it finds.
5. Commit messages follow the log: `M2 Phase B: writer on OpenRouter`, `Fix the subtitle offset
   after a crossfade`. The subject line says what changed; the body says why.
6. `/pr` opens the pull request with the template; CI must be green before merging.

Skills: `/check`, `/self-review`, `/pr`, `/add-model` (a registry entry end to end),
`/add-migration` (a schema change).
