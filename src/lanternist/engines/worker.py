"""Run a model inside its own venv as a batch subprocess.

The engines pin incompatible transformers versions, so each runs in the venv it was installed
in. A worker reads a JSON job, loads its model once, works through the items, and exits; exiting
is the one VRAM release that never fails. It reports on stdout as lines prefixed with MARK, so
library chatter on stdout is ignored; stderr goes to a log file.
"""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

MARK = "@@LX "
WORKERS = Path(__file__).resolve().parent.parent / "workers"


class EngineError(RuntimeError):
    pass


async def run_worker(python: Path, script: str, job: dict, workdir: Path,
                     on_event: Callable[[dict], None] | None = None) -> list[dict]:
    """Run workers/<script> with `job`; returns the 'item' events in order."""
    workdir.mkdir(parents=True, exist_ok=True)
    job_path = workdir / f"{Path(script).stem}-job.json"
    log_path = workdir / f"{Path(script).stem}.log"
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=1))

    items, error = [], None
    with open(log_path, "wb") as log:  # noqa: ASYNC230 - the worker's stderr, handed to the subprocess
        proc = await asyncio.create_subprocess_exec(
            str(python), str(WORKERS / script), str(job_path),
            stdout=asyncio.subprocess.PIPE, stderr=log, limit=1 << 20,
        )
        try:
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip("\n")
                if not line.startswith(MARK):
                    continue
                event = json.loads(line[len(MARK):])
                if event.get("event") == "item":
                    items.append(event)
                elif event.get("event") == "error":
                    error = event.get("message", "worker error")
                if on_event:
                    on_event(event)
            rc = await proc.wait()
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise

    if error or rc != 0:
        tail = log_path.read_text(errors="replace")[-3000:]
        raise EngineError(f"{script} failed (exit {rc}): {error or ''}\n--- log tail ---\n{tail}")
    return items
