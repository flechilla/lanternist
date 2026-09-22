---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Python

Python 3.12, managed by uv. `ruff format` owns the layout; `ruff check` and mypy run in CI, all
configured in `pyproject.toml`.

## Idioms this codebase uses

- `pathlib.Path` everywhere. Pass `encoding="utf-8"` to text reads and writes; about half of today's
  calls leave it out, so add it when you touch one.
- `log = logging.getLogger(__name__)` at module level, with %-style arguments
  (`log.info("unloaded %s", name)`). `print` belongs only in `cli.py` and the workers' protocol.
- Settings arrive as a `Settings` argument (`cfg`). Only entry points (`cli.py`, `api/app.py`) call
  `config.settings()`. Only `config.py` (the `LANTERNIST_*` switches) and `keys.py` (the provider
  key variables) read `os.environ`.
- Lazy imports only where they pay off: CLI start-up time, or a heavy or optional dependency. Put
  everything else at the top.
- `zip(..., strict=True)` whenever the sequences must line up: scenes, keyframes, narration and chunks.
- A small record is a `@dataclass`. Data that crosses a boundary (API body, TOML, LLM output, the
  storyboard) is a Pydantic model, validated once where it enters.
- Constants get a name, and the name says the unit or the reason: `RESUME_WINDOW = timedelta(minutes=50)`,
  `MAX_CHUNK = 350`. A bare number is fine only where its meaning is plain.

## Async

- Wrap subprocesses the way `engines/ffmpeg.run` and `engines/worker.run_worker` do. On
  `CancelledError`, kill the child, wait for it, and re-raise.
- `httpx.AsyncClient` always gets an explicit `timeout`. Open it with `async with`, around the
  batch, not per call.
- Don't swallow `CancelledError`. The runner uses `cancelling()` to tell a shutdown (re-queue) from a
  user's cancel.
- Run concurrent work through `asyncio.gather` under a semaphore sized from config, as `clips` and
  `fal.run` do.

## Errors

- One exception class per module or provider (`FfmpegError`, `FalError`, `GpuBusy`). Raise it with a
  message a user can act on.
- Catch the narrowest exception that can actually happen. A broad `except Exception` exists only
  where one failure must not stop the rest (the job loop, the keychain, a worker's top level), and
  says so in `# noqa: BLE001 - reason`.
- Use `raise … from None` when the new message already says everything, and `from e` when the cause
  helps debugging.
