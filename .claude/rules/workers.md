---
paths:
  - "src/lanternist/workers/**"
  - "src/lanternist/engines/worker.py"
---

# Engine workers

A worker is a standalone script that `engines/worker.run_worker` starts **inside another venv**: Qwen3-TTS
in its venv, klein in a diffusers venv. Those venvs pin torch and transformers versions that can't
coexist with ours, so:

- **Import only the standard library at the top**, and the engine's own libraries inside `main()`.
  Never import `lanternist`, pydantic, httpx or anything from this project's venv.
- **Protocol:** read the JSON job from `sys.argv[1]`. Print events as `@@LX {json}` lines: `loaded`,
  one `item` per output, `done`, and `error` with the traceback tail. Exit non-zero on failure. Other
  stdout is ignored; stderr goes to the log. `test_every_worker_speaks_the_runners_protocol` pins the
  marker to `engines.worker.MARK`.
- **Load the model once, then loop over `items`.** Exiting frees the VRAM, so a worker never lingers
  or serves.
- **Report real measurements** the pipeline builds on: durations per chunk, sizes, seconds taken.
  Never estimates.
- Tests can't run workers without the GPU venvs. Keep the logic in the worker minimal, and keep the
  shaping of jobs and results in the pipeline, where tests can reach it. After changing a worker,
  say in the PR that `uv run pytest -m gpu` passed on the GPU machine.
- These scripts restate a few lines each (`emit`, the `__main__` guard). That's the one sanctioned
  duplication in the repo, because they can't share a module with the app; `.jscpd.json` excludes
  this folder.
