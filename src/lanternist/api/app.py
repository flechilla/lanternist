"""The HTTP API, SSE progress, and the static web app, all in one process.

The local edition binds to localhost for one person. The hosted edition leaves out what belongs to
that person's machine (its keys, its doctor, its recordings), which live on the `local` router.
"""

import asyncio
import json
import mimetypes
import re
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .. import auth, keys, llm, prefs
from ..auth import Me
from ..config import settings
from ..db import Database, Job, StaleVersion, Story, StoryVersion, to_micros, to_usd
from ..engines import catalog as engines
from ..engines.ffmpeg import FfmpegError
from ..estimate import Kind, estimate
from ..jobs import Runner, is_terminal
from ..pipeline import Pipeline
from ..store import Store
from ..storyboard import Storyboard, next_seed, slugify
from ..text import LANGUAGES
from ..voices import find_voice
from ..writer import AUDIENCES, KINDS, STYLES, Brief

STATIC = Path(__file__).parent / "static"
ASSET = re.compile(r"^[0-9a-f]{64}\.[a-z0-9]{1,5}$")

cfg = settings()
db = Database(cfg.database_url, cfg.database.pool_size)
runner = Runner(cfg, db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.migrate()
    runner.start()
    yield
    await runner.stop()


app = FastAPI(title="Lanternist", lifespan=lifespan)
app.state.cfg, app.state.db = cfg, db  # for auth.current_user
local = APIRouter()  # the local edition's routes only: included below, unless hosted


if cfg.hosted_edition:

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        """Another site's page can't write through a signed-in visitor's cookie."""
        if auth.foreign_write(cfg, request):
            return JSONResponse({"detail": "writes come only from Lanternist's own pages"}, status_code=403)
        return await call_next(request)


@app.exception_handler(StaleVersion)
async def stale_version(_: Request, e: StaleVersion) -> JSONResponse:
    """A save, re-roll or new take made from a version another save has since replaced."""
    return JSONResponse({"detail": str(e)}, status_code=409)


# ---------------------------------------------------------------------------------- helpers
def job_dict(j: Job) -> dict:
    return {
        "id": j.id,
        "story_id": j.story_id,
        "version": j.version,
        "kind": j.kind,
        "status": j.status,
        "params": j.params,
        "progress": dollars(j.progress),
        "result": dollars(j.result),
        "error": j.error,
        "estimate": dollars(j.estimate),
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
    }


def dollars(obj):
    """Money as the API shows it: every `*_micros` field becomes `*_usd`, in dollars."""
    if isinstance(obj, dict):
        return {
            (k.removesuffix("_micros") + "_usd" if k.endswith("_micros") else k): (
                to_usd(v) if k.endswith("_micros") else dollars(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [dollars(v) for v in obj]
    return obj


def story_dict(st: Story) -> dict:
    return {
        "id": st.id,
        "slug": st.slug,
        "title": st.title,
        "language": st.language,
        "version": st.version,
        "created_at": st.created_at.isoformat(),
        "updated_at": st.updated_at.isoformat(),
    }


def _get(owner: str, story_id: str, version: int | None = None) -> tuple[Story, StoryVersion]:
    try:
        return db.storyboard(owner, story_id, version)
    except KeyError:
        raise HTTPException(404, "story or version not found") from None


def _pipeline(owner: str, story_id: str | None = None) -> Pipeline:
    return Pipeline(prefs.effective(cfg, db, owner), db=db, story_id=story_id, owner=owner)


def _quote(owner: str, story_id: str, version: int | None, kind: Kind) -> dict:
    """What a board or render of this version would cost now, in micro-dollars."""
    _, row = _get(owner, story_id, version)
    try:
        return estimate(_pipeline(owner, story_id), Storyboard.model_validate(row.storyboard), kind)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(422, str(e)) from None


def _enqueue(owner: str, story_id: str, kind: str, version: int | None, params: dict | None = None) -> dict:
    quote = None
    if kind in ("board", "render"):
        try:
            quote = _quote(owner, story_id, version, "board" if kind == "board" else "render")
        except HTTPException:
            quote = None  # the job itself fails with the reason, where the user sees it
    return job_dict(runner.enqueue(owner, story_id, kind, version, params, estimate=quote))


# ---------------------------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    return {"ok": True, "fake_engines": cfg.fake_engines}


@local.get("/api/doctor")
async def doctor(me: Me):
    from ..doctor import run_checks

    return [c.dict() for c in await run_checks(prefs.effective(cfg, db, me.id))]


# ---------------------------------------------------------------------------------- providers & settings
@local.get("/api/providers")
async def providers(me: Me):
    from ..doctor import provider_rows

    return await provider_rows(prefs.effective(cfg, db, me.id))


class KeyBody(BaseModel):
    key: str


def _provider(name: str) -> str:
    if name not in keys.PROVIDERS:
        raise HTTPException(404, f"unknown provider '{name}'")
    return name


@local.put("/api/providers/{name}/key")
async def set_provider_key(name: str, body: KeyBody, me: Me):
    from ..doctor import provider_rows

    try:
        stored = keys.set_key(_provider(name), body.key)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    row = next(r for r in await provider_rows(prefs.effective(cfg, db, me.id)) if r["name"] == name)
    return row | {"stored_in": stored}


@local.delete("/api/providers/{name}/key", status_code=204)
def clear_provider_key(name: str):
    keys.clear_key(_provider(name))


@app.get("/api/settings")
def get_settings(me: Me):
    return prefs.describe(cfg, db, me.id)


class SettingsBody(BaseModel):
    changes: dict


@app.put("/api/settings")
def put_settings(body: SettingsBody, me: Me):
    try:
        prefs.update(cfg, db, me.id, body.changes)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return prefs.describe(cfg, db, me.id)


@app.get("/api/models")
async def models(me: Me, capability: str = "writer.chat"):
    """The models a stage can use: writers live from Ollama and OpenRouter, media from the registry."""
    eff = prefs.effective(cfg, db, me.id)
    if capability == "writer.chat":
        return await llm.catalog(eff, db)
    try:
        return engines.catalog(eff, db, capability)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


@app.get("/api/me")
def whoami(me: Me):
    return {"id": me.id, "email": me.email, "role": me.role}


@app.get("/api/options")
def options():
    return {
        "languages": [{"id": k, "name": v} for k, v in LANGUAGES.items()],
        "audiences": [{"id": k, "name": v.split(":")[0]} for k, v in AUDIENCES.items()],
        "kinds": [{"id": k, "name": k.replace("_", " ")} for k in KINDS],
        "styles": [{"id": k, "name": k.replace("_", " "), "prompt": v} for k, v in STYLES.items()],
        "cameras": ["auto", "push_in", "pull_out", "pan_left", "pan_right", "static"],
        "fake_engines": cfg.fake_engines,
        "edition": cfg.edition,
    }


# ---------------------------------------------------------------------------------- stories
@app.get("/api/stories")
def list_stories(me: Me):
    spent = db.spend_by_story(me.id)
    return [
        {
            **story_dict(r.story),
            "scenes": len(r.storyboard.get("scenes", [])),
            "active_jobs": r.active,
            "progress": r.progress,
            "film": r.film.result if r.film else None,
            "film_version": r.film.version if r.film else None,
            "poster": (r.drawn.result or {}).get("poster") if r.drawn else None,
            "spent_usd": to_usd(spent.get(r.story.id, 0)),
        }
        for r in db.library(me.id)
    ]


class NewStory(BaseModel):
    brief: Brief | None = None
    storyboard: Storyboard | None = None


@app.post("/api/stories", status_code=201)
def create_story(body: NewStory, me: Me):
    source = body.storyboard or body.brief
    if source is None:
        raise HTTPException(422, "send a brief to write a story, or a storyboard to import one")
    if body.brief:
        try:
            llm.check_key(prefs.effective(cfg, db, me.id), body.brief.writer)
        except llm.LLMError as e:
            raise HTTPException(422, str(e)) from None
    title = body.storyboard.title if body.storyboard else "Writing…"
    imported = body.storyboard.model_dump() if body.storyboard else None
    story = story_dict(db.create_story(me.id, title, source.language, imported))
    job = _enqueue(me.id, story["id"], "write", None, body.brief.model_dump()) if body.brief else None
    return {"story": story, "job": job}


def writer_dict(owner: str, story_id: str, sb: Storyboard | None) -> dict | None:
    """Who wrote the story, and what writing it has cost: failed attempts too, since OpenRouter bills them."""
    writer = sb.models.writer if sb else None
    if not writer:
        return None  # imported, or written before stories recorded their writer
    provider, model = llm.parse(writer)
    return {
        "id": writer,
        "model": model,
        "local": provider == "ollama",
        "cost_usd": to_usd(db.spend_micros(owner, story_id=story_id, stage="write")),
    }


@app.get("/api/stories/{story_id}")
def get_story(story_id: str, me: Me, version: int | None = None):
    st = db.get_story(me.id, story_id)
    if st is None:
        raise HTTPException(404, "story not found")
    row = db.get_version(me.id, story_id, version or st.version) if st.version else None
    jobs = [job_dict(j) for j in db.story_jobs(me.id, story_id, limit=30)]
    versions = [
        {"version": v.version, "note": v.note, "created_at": v.created_at.isoformat()}
        for v in db.story_versions(me.id, story_id)
    ]
    # Validated, so a storyboard saved before a field existed comes back with its default.
    sb = Storyboard.model_validate(row.storyboard) if row else None
    board = _pipeline(me.id, story_id).peek(sb) if sb else None
    films = [j for j in jobs if j["kind"] == "render" and j["status"] == "done"]
    return {
        "story": story_dict(st),
        "version": row.version if row else 0,
        "storyboard": sb.model_dump() if sb else None,
        "board": board,
        "jobs": jobs,
        "versions": versions,
        "film": films[0] if films else None,
        "writer": writer_dict(me.id, story_id, sb),
        "budget": budget_dict(st),
    }


def budget_dict(st: Story) -> dict:
    """The story's budget (its own, or its owner's default from Settings) and what it has spent."""
    default_usd = prefs.effective(cfg, db, st.owner_id).defaults.budget_usd
    return {
        "usd": to_usd(db.budget_micros(st.owner_id, st.id, default_usd)),
        "default": st.budget_micros is None,
        "spent_usd": to_usd(db.spend_micros(st.owner_id, story_id=st.id)),
    }


@app.get("/api/stories/{story_id}/estimate")
def get_estimate(story_id: str, me: Me, kind: Kind = "render", version: int | None = None):
    return dollars(_quote(me.id, story_id, version, kind))


class BudgetBody(BaseModel):
    usd: float | None = Field(None, ge=0, description="None goes back to the default from Settings")


@app.put("/api/stories/{story_id}/budget")
def set_budget(story_id: str, body: BudgetBody, me: Me):
    st = db.set_budget(me.id, story_id, None if body.usd is None else to_micros(str(body.usd)))
    if st is None:
        raise HTTPException(404, "story not found")
    return budget_dict(st)


class SaveStory(BaseModel):
    storyboard: Storyboard
    base_version: int
    note: str = "edited"


@app.put("/api/stories/{story_id}")
def save_story(story_id: str, body: SaveStory, me: Me):
    body.storyboard.renumber()
    try:
        st, row = db.save_edit(me.id, story_id, body.storyboard.model_dump(), body.base_version, body.note)
    except KeyError:
        raise HTTPException(404, "story not found") from None
    return {"story": story_dict(st), "version": row.version}


@app.delete("/api/stories/{story_id}", status_code=204)
def delete_story(story_id: str, me: Me):
    for job_id in db.active_jobs(me.id, story_id):
        runner.cancel(me.id, job_id)
    if not db.delete_story(me.id, story_id):
        raise HTTPException(404, "story not found")


@app.post("/api/stories/{story_id}/scenes/{n}/rewrite")
def rewrite(story_id: str, n: int, me: Me, instruction: str = Body(..., embed=True)):
    st, _ = _get(me.id, story_id)
    return _enqueue(me.id, story_id, "rewrite", st.version, {"n": n, "instruction": instruction})


@app.post("/api/stories/{story_id}/scenes/{n}/reroll")
def reroll(story_id: str, n: int, me: Me):
    """A new seed for one scene's picture, then redraw it (everything else comes from the cache)."""

    def change(sb: Storyboard):
        sc = next((x for x in sb.scenes if x.n == n), None)
        if sc is None:
            raise HTTPException(404, f"no scene {n}")
        sc.seed = next_seed(sb.scene_seed(sc))

    _get(me.id, story_id)
    version = db.change_story(me.id, story_id, change, f"re-rolled scene {n}")
    return {"version": version, "job": _enqueue(me.id, story_id, "board", version)}


@app.post("/api/stories/{story_id}/scenes/{n}/retake")
def retake(story_id: str, n: int, me: Me):
    """A new take of one scene's video, then render (every other step comes from the cache)."""

    def change(sb: Storyboard):
        sc = next((x for x in sb.scenes if x.n == n), None)
        if sc is None or sc.mode != "video":
            raise HTTPException(404, f"no video scene {n}")
        sc.video_seed = next_seed(sb.video_seed(sc))

    _get(me.id, story_id)
    version = db.change_story(me.id, story_id, change, f"new take of scene {n}")
    return {"version": version, "job": _enqueue(me.id, story_id, "render", version)}


@app.post("/api/stories/{story_id}/cast/reroll")
def reroll_cast(story_id: str, me: Me):
    def change(sb: Storyboard):
        sb.seed = next_seed(sb.seed)

    _get(me.id, story_id)
    version = db.change_story(me.id, story_id, change, "re-rolled the cast sheet")
    return {"version": version, "job": _enqueue(me.id, story_id, "cast", version)}


@app.post("/api/stories/{story_id}/{kind}")
def run_stage(story_id: str, kind: str, me: Me, version: int | None = None):
    if kind not in ("cast", "board", "render"):
        raise HTTPException(404, "unknown action")
    _, row = _get(me.id, story_id, version)
    return _enqueue(me.id, story_id, kind, row.version)


# ---------------------------------------------------------------------------------- jobs
@app.get("/api/jobs")
def list_jobs(me: Me, active: bool = False):
    return [job_dict(j) for j in db.jobs(me.id, active, limit=50)]


def _job(owner: str, job_id: str) -> Job:
    j = db.get_job(owner, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return j


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, me: Me):
    return job_dict(_job(me.id, job_id))


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, me: Me):
    _job(me.id, job_id)
    return {"cancelled": runner.cancel(me.id, job_id)}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, me: Me):
    """The job's snapshots as they change, to its end. Another user's job is `gone`, as a deleted one is."""

    async def stream():
        last, idle = None, 0
        while True:
            if await request.is_disconnected():
                return
            # Off the event loop: over the network to Postgres, a query would hold up every request.
            j = await asyncio.to_thread(db.get_job, me.id, job_id)
            snap = job_dict(j) if j else None
            if snap is None:
                yield "event: gone\ndata: {}\n\n"
                return
            body = json.dumps(snap)
            if body != last:
                yield f"event: job\ndata: {body}\n\n"
                last, idle = body, 0
            else:
                idle += 1
                if idle % 30 == 0:
                    yield ": keep-alive\n\n"  # proxies drop silent streams
            if is_terminal(snap["status"]):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------------- assets & voices
@app.get("/api/assets/{asset}")
async def get_asset(asset: str, me: Me, download: str | None = None, w: int | None = Query(None, gt=0)):
    """One of the user's files, or one everyone shares (a voice's sample); with `w`, a picture as a
    smaller JPEG (`Pipeline.thumbnail`). Another user's file is not found, as a missing one is."""
    if not ASSET.match(asset):
        raise HTTPException(400, "bad asset id")
    pipeline = Pipeline(cfg, owner=me.id)
    path = pipeline.find(asset)
    if path is None:
        raise HTTPException(404, "asset not found")
    # An asset never changes under its name; a thumbnail can, when THUMBNAIL does, so it's checked daily.
    # A hosted user's file is theirs alone, so no cache in between may keep it for someone else.
    who = "private" if cfg.hosted_edition else "public"
    headers = {"Cache-Control": f"{who}, max-age=31536000, immutable"}
    if w is not None:
        try:
            path = await pipeline.thumbnail(asset, w)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except FfmpegError:
            raise HTTPException(
                500, f"The picture {asset} can't be read. Draw its scene again on the Board."
            ) from None
        headers = {"Cache-Control": f"{who}, max-age=86400"}
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if asset.endswith(".vtt"):
        media = "text/vtt"
    return FileResponse(
        path,
        media_type=media,
        headers=headers,
        filename=download or None,
        content_disposition_type="attachment" if download else "inline",
    )


@app.get("/api/voices/catalog")
def voice_catalog(me: Me, language: str = "en", tts: str = ""):
    """The voices a narration model offers, each with its sample if one was made."""
    eff = prefs.effective(cfg, db, me.id)
    try:
        return engines.voices(eff, db, Store(eff.library_for(None)), tts or eff.defaults.tts, language)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


class SampleBody(BaseModel):
    voice: str
    language: str = "en"
    tts: str = Field("", description="the narration model; empty is the default")


@app.post("/api/voices/sample")
def voice_sample(body: SampleBody, me: Me):
    """A voice's sample line: at once when it was made before, else a job in the fast lane (seconds).
    Samples are shared: the voice sounds the same to everyone."""
    if body.language not in LANGUAGES:
        raise HTTPException(422, f"no sample line in '{body.language}'")
    eff = prefs.effective(cfg, db, me.id)
    model = body.tts or eff.defaults.tts
    try:
        eng = engines.sampler(eff, db, model, body.voice, body.language)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(422, str(e)) from None
    if audio := engines.cached_sample(Store(eff.library_for(None)), eng, body.language):
        return {"audio": audio, "job": None}
    params = {"tts": model, "voice": body.voice, "language": body.language}
    return {"audio": None, "job": job_dict(runner.enqueue(me.id, None, "sample", None, params))}


@local.get("/api/voices/{name}/audio")
def voice_audio(name: str):
    try:
        v = find_voice(cfg, name)
    except FileNotFoundError:
        raise HTTPException(404, "no such voice") from None
    return FileResponse(v.wav, media_type="audio/wav")


@local.post("/api/voices", status_code=201)
def add_voice(name: str = Form(...), transcript: str = Form(""), audio: UploadFile = File(...)):  # noqa: B008
    slug = slugify(name)
    folder = cfg.paths.voices[0]
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f".{slug}.upload"
    raw.write_bytes(audio.file.read())
    dest = folder / f"{slug}.wav"
    # Any format in; 24 kHz mono out, which is what the TTS engines resample to anyway.
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-ac", "1", "-ar", "24000", str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    raw.unlink(missing_ok=True)
    if proc.returncode:
        raise HTTPException(422, f"couldn't read that audio: {proc.stderr[-300:]}")
    txt = dest.with_suffix(".txt")
    if transcript.strip():
        txt.write_text(transcript.strip() + "\n", encoding="utf-8")
    else:
        txt.unlink(missing_ok=True)
    return {"name": slug, "path": str(dest), "has_transcript": bool(transcript.strip())}


# Before the web app's catch-all route, which would answer first.
app.include_router(auth.router if cfg.hosted_edition else local)


# ---------------------------------------------------------------------------------- web app
@app.exception_handler(ValidationError)
async def _validation(_: Request, exc: ValidationError):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": exc.errors()}, status_code=422)


if (STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="static-assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    target = STATIC / path
    if path and target.is_file() and STATIC in target.resolve().parents:
        return FileResponse(target)
    index = STATIC / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(
        "<p>Lanternist API is running. Build the web app: <code>cd web && pnpm build</code>.</p>"
    )
