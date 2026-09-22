"""lanternist: doctor · import · write · board · render · serve · keys · models"""

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from .config import settings
from .storyboard import Effort, Mode, Storyboard, Subtitles, slugify

app = typer.Typer(no_args_is_help=True, add_completion=False)
keys_app = typer.Typer(no_args_is_help=True, help="API keys for remote models (OpenRouter, fal.ai).")
app.add_typer(keys_app, name="keys")

MARK = {"ok": "✓", "warn": "!", "fail": "✗"}


def _load(path: Path) -> Storyboard:
    return Storyboard.model_validate_json(path.read_text(encoding="utf-8"))


def _printer():
    t0 = time.time()

    def emit(e):
        if e.status == "cached" and e.scene is not None:
            return
        where = f" scene {e.scene}" if e.scene is not None else ""
        count = f" {e.done}/{e.total}" if e.total else ""
        msg = f" {e.message}" if e.message else ""
        print(f"[{time.time() - t0:6.1f}s] {e.stage:<9} {e.status:<8}{count}{where}{msg}", flush=True)

    return emit


def _db():
    from .db import Database

    db = Database(settings().library / "lanternist.db")
    db.migrate()
    return db


def _effective():
    from .prefs import effective

    db = _db()
    return effective(settings(), db), db


@app.command()
def doctor():
    """Check that every engine, model and tool a film needs is ready."""
    from .doctor import run_checks

    checks = asyncio.run(run_checks(_effective()[0]))
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
    writer: Annotated[
        str,
        typer.Option(
            help="ollama/<model> or openrouter/<model id>; "
            "default: the one set in Settings, else the local model"
        ),
    ] = "",
    effort: Annotated[
        Effort | None, typer.Option(help="reasoning effort, for OpenRouter models that support it")
    ] = None,
):
    """Write a storyboard from a one-line idea, with the local LLM or an OpenRouter model."""
    from .llm import Calls
    from .text import word_count
    from .writer import Brief, write_storyboard

    cfg, db = _effective()
    brief = Brief(
        idea=idea,
        language=language,
        audience=audience,
        kind=kind,
        minutes=minutes,
        style=style,
        notes=notes,
        mode=mode,
        writer=writer,
        effort=effort,
    )
    calls = Calls(db)
    t0 = time.time()
    sb = asyncio.run(write_storyboard(cfg, brief, emit=lambda m: print(f"  {m}", flush=True), calls=calls))
    out = out or Path(f"{slugify(sb.title)}.json")
    out.write_text(sb.model_dump_json(indent=2), encoding="utf-8")
    words = sum(word_count(sc.text) for sc in sb.scenes)
    info = calls.summary()
    cost = f"${info['cost_usd']:.4f}" if info["cost_usd"] is not None else "free"
    print(
        f"{sb.title}: {len(sb.scenes)} scenes, {len(sb.cast)} characters, {words} words "
        f"(target {brief.target_words}) -> {out}"
    )
    print(
        f"written by {sb.models.writer} in {time.time() - t0:.0f}s: {info['calls']} calls, "
        f"{info['tokens_in']} tokens in, {info['tokens_out']} out, {cost}"
    )


@app.command()
def board(story: Path):
    """Narrate the story and draw the cast sheet and every keyframe."""
    from .pipeline import Pipeline

    sb = _load(story)
    p = Pipeline(settings(), _printer())
    b = asyncio.run(p.board(sb))
    print(f"board ready: {len(b.keyframes)} keyframes, {b.timeline.total:.1f}s of film")
    for sc, kf, nar in zip(sb.scenes, b.keyframes, b.narration, strict=True):
        print(f"  {sc.n:3d} {nar.duration:5.1f}s  {p.store.path(kf)}")


@app.command()
def render(
    story: Path,
    out: Annotated[Path | None, typer.Option("-o", "--out")] = None,
    mode: Annotated[Mode | None, typer.Option(help="override every scene's mode")] = None,
    subtitles: Annotated[Subtitles | None, typer.Option()] = None,
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


# ---------------------------------------------------------------------------------- keys
@keys_app.command("set")
def keys_set(
    provider: Annotated[str, typer.Argument(help="openrouter | fal")],
    key: Annotated[str, typer.Option(prompt=True, hide_input=True, help="the API key")],
):
    """Store a key in the OS keychain (or a 0600 file when there is no keychain)."""
    from .keys import PROVIDERS, set_key

    if provider not in PROVIDERS:
        raise typer.BadParameter(f"one of: {', '.join(PROVIDERS)}")
    where = set_key(provider, key)
    print(f"{provider} key saved in the {where}")
    keys_status()


@keys_app.command("clear")
def keys_clear(provider: Annotated[str, typer.Argument(help="openrouter | fal")]):
    """Remove a stored key."""
    from .keys import PROVIDERS, clear_key, get_key

    if provider not in PROVIDERS:
        raise typer.BadParameter(f"one of: {', '.join(PROVIDERS)}")
    clear_key(provider)
    left = get_key(provider)
    print(
        f"{provider} key removed"
        + (f"; {PROVIDERS[provider]} in the environment still sets one" if left.source == "env" else "")
    )


@keys_app.command("status")
def keys_status():
    """Show which keys are set, where they come from, and whether each provider accepts them."""
    from .doctor import provider_rows

    for r in asyncio.run(provider_rows(_effective()[0])):
        if not r["configured"]:
            print(f" · {r['label']:<11} no key")
            continue
        print(
            f" {MARK['ok' if r['ok'] else 'fail']} {r['label']:<11} {r['detail']} "
            f"(from {r['source']}, …{r['last4']})"
        )


# ---------------------------------------------------------------------------------- models
@app.command()
def models(
    capability: Annotated[
        str | None,
        typer.Option(help="tts.speak | image.keyframe | video.image_to_video | audio.ambience | writer.chat"),
    ] = None,
    sync: Annotated[
        bool, typer.Option(help="refresh fal prices and status first (needs the fal key)")
    ] = False,
):
    """List the models each stage can use, with today's prices."""
    from . import registry

    cfg, db = _effective()
    if sync:
        lines = asyncio.run(registry.sync_prices(cfg, db))
        changed = [x for x in lines if x["changed"]]
        print(f"synced {len(lines)} fal endpoints, {len(changed)} changed")
        for x in lines:
            if x["price"] is None:
                print(f"  ! {x['model']}: fal returned no price for {x['endpoint']}")
            elif x["drift"]:
                print(f"  ! {x['model']}: {x['drift']}; check the model page")
            if x["status"] != "active":
                print(f"  ! {x['model']}: {x['endpoint']} is {x['status']}")
        print()
    if capability == "writer.chat":
        _writer_models(cfg, db)
        return
    defaults = {cfg.defaults.tts, cfg.defaults.image, cfg.defaults.video, cfg.defaults.ambience}
    for cap in registry.CAPABILITIES[1:]:
        if capability and cap != capability:
            continue
        print(cap)
        for e in registry.by_capability(cap, cfg.library, db):
            p = e.price
            price = f"${p.usd}/{p.unit}" if p.usd is not None else f"{p.gpu_seconds} GPU-s/{p.unit}"
            when = f" · list {p.synced}" if p.synced else ""
            if b := e.billing.get(""):
                when += f" · fal bills ${b.unit_price} per {b.unit} ({b.synced})"
            flags = " ".join(
                f
                for f in (
                    "default" if e.id in defaults else "",
                    "" if e.status == "active" else e.status,
                    "personal use" if e.commercial_use is False else "",
                )
                if f
            )
            print(
                f"  {'*' if e.id in defaults else ' '} {e.id:<30} {price:<28}{when}{f'  [{flags}]' if flags else ''}"
            )
        print()
    if not capability:
        _writer_models(cfg, db)


def _writer_models(cfg, db) -> None:
    from .llm import catalog

    print("writer.chat")
    cat = asyncio.run(catalog(cfg, db))
    for name, st in cat["providers"].items():
        if st.get("error"):
            print(f"    {name}: {st['error']}")
    listed = [m for m in cat["models"] if m["local"] or m["recommended"] or m["id"] == cat["default"]]
    for m in listed:
        if m["local"]:
            price = "free, local"
        elif m["price_in"] is None:
            price = "not listed"
        else:
            price = (
                f"${m['price_in']:.2f} in / ${m['price_out']:.2f} out per 1M tokens, "
                f"≈ ${m['usd_per_minute'] * 3:.3f} per 3-minute story ({m['basis']})"
            )
        print(f"  {'*' if m['id'] == cat['default'] else ' '} {m['id']:<44} {price}")
    remote = sum(1 for m in cat["models"] if m["provider"] == "openrouter")
    print(
        f"    {remote} OpenRouter models support structured output"
        + ("; pin favourites with openrouter.recommended" if not cfg.openrouter.recommended else "")
    )
