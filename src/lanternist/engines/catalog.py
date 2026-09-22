"""Which engine runs a registry entry, and what each model offers the pickers.

Local models map by id to their engine, fal models by adapter family. The prices the pickers show
come from each engine's own estimate, so the price on a picker is the price the estimator uses.
"""

from decimal import Decimal

from .. import registry
from ..config import Settings
from ..db import Database, to_usd
from ..keys import get_key
from ..registry import ModelEntry
from ..voices import find_voice
from .base import Engine, Item, TtsEngine, VideoEngine, keyframe_size
from .fal_audio import FalMmaudio
from .fal_image import FalImage
from .fal_video import FalVideo
from .local import LocalKlein, LocalLtx, LocalQwenTts

FAL_IMAGE = {"klein", "nano_banana", "seedream", "flux2"}
FAL_VIDEO = {"kling", "veo", "wan", "wan3", "ltx", "h3"}


def entry(cfg: Settings, db: Database | None, model_id: str, capability: str) -> ModelEntry:
    try:
        e = registry.get(model_id, cfg.library, db)
    except KeyError as err:
        raise ValueError(str(err).strip("'\"")) from None
    if e.capability != capability:
        raise ValueError(f"{model_id} is a {e.capability} model, not {capability}")
    return e


def _no_adapter(e: ModelEntry) -> ValueError:
    return ValueError(
        f"{e.id} has no engine here (family {e.family!r}): check registry/*.toml or models.toml"
    )


def image(cfg: Settings, db: Database | None, model_id: str, quality: str | None = None) -> Engine:
    return _image(cfg, db, entry(cfg, db, model_id, "image.keyframe"), quality)


def _image(cfg: Settings, db: Database | None, e: ModelEntry, quality: str | None) -> Engine:
    if e.provider == "local":
        return LocalKlein(cfg, e)
    if e.family in FAL_IMAGE:
        return FalImage(cfg, e, db, quality)
    raise _no_adapter(e)


def tts(cfg: Settings, db: Database | None, model_id: str, voice: str, language: str) -> TtsEngine:
    e = entry(cfg, db, model_id, "tts.speak")
    if e.provider == "local":
        return LocalQwenTts(cfg, e, find_voice(cfg, voice), language)
    raise _no_adapter(e)


def video(cfg: Settings, db: Database | None, model_id: str, quality: str | None = None) -> VideoEngine:
    return _video(cfg, db, entry(cfg, db, model_id, "video.image_to_video"), quality)


def _video(cfg: Settings, db: Database | None, e: ModelEntry, quality: str | None) -> VideoEngine:
    if e.provider == "local":
        return LocalLtx(cfg, e)
    if e.family in FAL_VIDEO:
        return FalVideo(cfg, e, db, quality)
    raise _no_adapter(e)


def ambience(cfg: Settings, db: Database | None, model_id: str) -> Engine:
    e = entry(cfg, db, model_id, "audio.ambience")
    if e.family == "mmaudio":
        return FalMmaudio(cfg, e, db)
    raise _no_adapter(e)


# ---------------------------------------------------------------------------------- the pickers
def _available(cfg: Settings, e: ModelEntry) -> bool:
    return e.provider == "local" or bool(get_key(e.provider, fake=cfg.fake_engines).value)


def _picture(cfg: Settings) -> Item:
    """A keyframe with the cast sheet as its reference, as most scenes are drawn."""
    w, h = keyframe_size(cfg)
    return Item("s001", None, 1, {"prompt": "", "seed": 0, "width": w, "height": h, "refs": ["cast"]})


def _image_row(cfg: Settings, db: Database | None, e: ModelEntry) -> dict:
    def per_picture(quality: str | None) -> dict:
        est = _image(cfg, db, e, quality).estimate([_picture(cfg)])
        return {"usd": to_usd(est.micros) if e.remote else None, "gpu_seconds": est.gpu_seconds or None}

    q = e.quality
    return {
        "per": "picture",
        **per_picture(None),
        "quality": {
            "param": q.param,
            "default": q.default,
            "options": [{"id": o, "label": q.labels.get(o, o), **per_picture(o)} for o in q.options],
        }
        if q
        else None,
    }


def _second(seconds: float = 10.0) -> Item:
    """A scene's clip of `seconds`, planned as its model would bill it."""
    return Item("s001", None, 1, {"seconds": seconds, "shots": [seconds]})


def _video_row(cfg: Settings, db: Database | None, e: ModelEntry) -> dict:
    def per_second(quality: str | None) -> dict:
        eng = _video(cfg, db, e, quality)
        est = eng.estimate([_second()])  # ten seconds, so a price per second reads cleanly
        return {
            "usd": to_usd(est.micros // 10) if e.remote else None,
            "gpu_seconds": est.gpu_seconds / 10 or None,
        }

    q, d = e.quality, e.durations
    return {
        "per": "second of video",
        "sound": e.audio == "ambience",
        "lengths": d.lengths() if d else [],
        **per_second(None),
        "quality": {
            "param": q.param,
            "default": q.default,
            "options": [{"id": o, "label": q.labels.get(o, o), **per_second(o)} for o in q.options],
        }
        if q
        else None,
    }


def _ambience_row(cfg: Settings, db: Database | None, e: ModelEntry) -> dict:
    est = ambience(cfg, db, e.id).estimate([_second()])
    return {"per": "second of sound", "usd": to_usd(est.micros // 10), "gpu_seconds": None, "quality": None}


def catalog(cfg: Settings, db: Database | None, capability: str) -> dict:
    """Every model a stage can use, with what it costs and whether it can run here now."""
    defaults = {
        "tts.speak": cfg.defaults.tts,
        "image.keyframe": cfg.defaults.image,
        "video.image_to_video": cfg.defaults.video,
        "audio.ambience": cfg.defaults.ambience,
    }
    if capability not in defaults:
        raise ValueError(f"no model list for '{capability}'")
    rows = []
    for e in registry.by_capability(capability, cfg.library, db):
        row = {
            "id": e.id,
            "label": e.label,
            "provider": e.provider,
            "local": e.provider == "local",
            "available": _available(cfg, e),
            "status": e.status,
            "notes": e.notes,
            "licence": e.licence,
            "commercial_use": e.commercial_use,
        }
        if capability == "image.keyframe":
            row |= _image_row(cfg, db, e)
        elif capability == "video.image_to_video":
            row |= _video_row(cfg, db, e)
        elif capability == "audio.ambience":
            row |= _ambience_row(cfg, db, e)
        rows.append(row)
    rows.sort(key=lambda r: (not r["local"], Decimal(str(r.get("usd") or 0))))
    return {"default": defaults[capability], "models": rows}
