"""lanternist: doctor · import · write · board · render · serve"""

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from .config import settings
from .storyboard import Storyboard, slugify

app = typer.Typer(no_args_is_help=True, add_completion=False)

MARK = {"ok": "✓", "warn": "!", "fail": "✗"}


def _load(path: Path) -> Storyboard:
    return Storyboard.model_validate_json(path.read_text(encoding="utf-8"))


def _printer():
    t0 = time.time()

    def emit(e):
        if e.status in ("cached",) and e.scene is not None:
            return
        where = f" scene {e.scene}" if e.scene is not None else ""
        count = f" {e.done}/{e.total}" if e.total else ""
        msg = f" {e.message}" if e.message else ""
        print(f"[{time.time() - t0:6.1f}s] {e.stage:<9} {e.status:<8}{count}{where}{msg}", flush=True)

    return emit


@app.command()
def doctor():
    """Check that every engine, model and tool a film needs is ready."""
    from .doctor import run_checks

    checks = asyncio.run(run_checks(settings()))
    for c in checks:
        print(f" {MARK[c.status]} {c.name:<9} {c.detail}")
    if any(c.status == "fail" for c in checks):
        raise typer.Exit(1)


@app.command("import")
def import_(
    story: Path,
    out: Annotated[Path | None, typer.Option("-o", "--out")] = None,
    mode: Annotated[str, typer.Option(help="still | video")] = "still",
    language: str = "en",
):
    """Convert a prototype story (.txt + .prompts/.cast/.motion sidecars) into a storyboard JSON."""
    from .importers.prototype import import_story

    sb = import_story(story, mode=mode, language=language)
    out = out or Path(f"{slugify(sb.title)}.json")
    out.write_text(sb.model_dump_json(indent=2), encoding="utf-8")
    print(f"{len(sb.scenes)} scenes -> {out}")


@app.command()
def write(
    idea: str,
    out: Annotated[Path | None, typer.Option("-o", "--out")] = None,
    language: Annotated[str, typer.Option("--lang")] = "en",
    audience: str = "kids_5_8",
    kind: str = "bedtime",
    minutes: float = 3.0,
    style: str = "watercolour",
    notes: str = "",
    mode: Annotated[str, typer.Option(help="still | video | hybrid")] = "still",
):
    """Write a storyboard from a one-line idea with the local LLM."""
    from .writer import Brief, write_storyboard

    brief = Brief(idea=idea, language=language, audience=audience, kind=kind, minutes=minutes, style=style,
                  notes=notes, mode=mode)
    sb = asyncio.run(write_storyboard(settings(), brief, emit=lambda m: print(f"  {m}", flush=True)))
    out = out or Path(f"{slugify(sb.title)}.json")
    out.write_text(sb.model_dump_json(indent=2), encoding="utf-8")
    print(f"{sb.title}: {len(sb.scenes)} scenes, {len(sb.cast)} characters -> {out}")


@app.command()
def board(story: Path):
    """Narrate the story and draw the cast sheet and every keyframe."""
    from .pipeline import Pipeline

    sb = _load(story)
    p = Pipeline(settings(), _printer())
    b = asyncio.run(p.board(sb))
    print(f"board ready: {len(b.keyframes)} keyframes, {b.timeline.total:.1f}s of film")
    for sc, kf, nar in zip(sb.scenes, b.keyframes, b.narration):
        print(f"  {sc.n:3d} {nar.duration:5.1f}s  {p.store.path(kf)}")


@app.command()
def render(
    story: Path,
    out: Annotated[Path | None, typer.Option("-o", "--out")] = None,
    mode: Annotated[str | None, typer.Option(help="still | video: override every scene's mode")] = None,
    subtitles: Annotated[str | None, typer.Option(help="off | sidecar | burned")] = None,
):
    """Render the whole film: board, motion, clips, mix."""
    from .pipeline import Pipeline

    sb = _load(story)
    if mode:
        for sc in sb.scenes:
            sc.mode = mode
    if subtitles:
        sb.subtitles = subtitles
    cfg = settings()
    p = Pipeline(cfg, _printer())
    film = asyncio.run(p.render(sb))
    out = out or cfg.library / "films" / f"{slugify(sb.title)}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p.store.path(film.film), out)
    if film.srt:
        shutil.copy2(p.store.path(film.srt), out.with_suffix(".srt"))
    print(f"{film.duration:.1f}s -> {out}")


@app.command()
def voices():
    """List the reference voices narration can clone."""
    from .pipeline import list_voices

    for v in list_voices(settings()):
        print(f"  {v['name']:<16} {v['path']}{'' if v['has_transcript'] else '  (no transcript)'}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8420, reload: bool = False):
    """Run the app: API, web UI and the render queue."""
    import uvicorn

    uvicorn.run("lanternist.api.app:app", host=host, port=port, reload=reload, log_level="info")


@app.command()
def schema():
    """Print the storyboard JSON schema."""
    json.dump(Storyboard.model_json_schema(), sys.stdout, indent=2)
