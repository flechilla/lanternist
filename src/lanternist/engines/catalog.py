"""Which engine runs a registry entry, and what each model offers the pickers.

Local models map by id to their engine, fal models by adapter family. The prices the pickers show
come from each engine's own estimate, so the price on a picker is the price the estimator uses.
"""

from collections.abc import Callable
from decimal import Decimal

from .. import prefs, registry, text
from ..config import Settings
from ..db import Database, to_usd
from ..keys import get_key
from ..registry import ModelEntry
from ..store import Store
from ..voices import find_voice, list_voices
from ..writer import CHARS_PER_WORD, narration_seconds, wpm
from .base import Engine, Item, TtsEngine, VideoEngine, gpu_estimate, keyframe_size
from .fal_audio import FalMmaudio
from .fal_image import FalImage
from .fal_tts import FalTts, chars_estimate
from .fal_video import FalVideo
from .local import LocalKlein, LocalLtx, LocalQwenTts

FAL_IMAGE = {"klein", "nano_banana", "seedream", "flux2"}
FAL_VIDEO = {"kling", "veo", "wan", "wan3", "ltx", "h3"}
FAL_TTS = {"qwen_tts", "elevenlabs", "minimax", "chatterbox"}
SAMPLE_SEED = 7  # a sample is one take: the same line in the same voice is made once


def entry(cfg: Settings, db: Database | None, model_id: str, capability: str) -> ModelEntry:
    try:
        e = registry.get(model_id, cfg.library, db, cfg.hosted_edition)
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
    """The narration engine speaking `voice`: FileNotFoundError when it's a recording that isn't
    there, VoiceError when the model has no such voice."""
    e = entry(cfg, db, model_id, "tts.speak")
    if e.provider == "local":
        return LocalQwenTts(cfg, e, find_voice(cfg, voice), language)
    if e.family in FAL_TTS:
        return FalTts(cfg, e, db, voice, language)
    raise _no_adapter(e)


def sample_item(eng: TtsEngine, language: str) -> Item:
    """A voice sample: the language's sample line, keyed like any narration, so it's made once."""
    line = text.SAMPLES.get(language, text.SAMPLES["en"])
    chunks = eng.chunks(line)
    return Item(
        "sample",
        eng.key("tts", chunks=chunks, seed=SAMPLE_SEED),
        None,
        {"chunks": chunks, "seed": SAMPLE_SEED, "seconds": narration_seconds(line, language)},
    )


def sampler(cfg: Settings, db: Database | None, model_id: str, voice: str, language: str) -> TtsEngine:
    """The engine that makes `voice`'s sample. Only a remote one: a narrator on this machine would take
    the GPU for it, and the voice it clones is the recording, which plays as it is."""
    eng = tts(cfg, db, model_id, voice, language)
    if not eng.remote:
        raise ValueError("a narrator on this machine clones your recording: listen to the recording itself")
    return eng


def cached_sample(store: Store, eng: TtsEngine, language: str) -> str | None:
    """The sample's audio if it was made before."""
    rec = store.get_step(sample_item(eng, language).key or "")
    return rec["assets"]["audio"] if rec else None


def voices(cfg: Settings, db: Database | None, store: Store, model_id: str, language: str) -> dict:
    """The voices a narration model offers: its presets and, if it clones, the recordings in voices/
    (none in the hosted edition, which clones no one's voice). Each comes with its sample when one was
    made; `sample_usd` is what making one costs."""
    e = entry(cfg, db, model_id, "tts.speak")

    def sample(voice: str) -> str | None:
        if e.provider == "local":
            return None  # the recording itself is the sample
        return cached_sample(store, tts(cfg, db, e.id, voice, language), language)

    recordings = list_voices(cfg) if e.clone and not cfg.hosted_edition else []
    price = None
    if e.remote and (e.voices or recordings):
        first = e.voices[0] if e.voices else recordings[0]["name"]
        eng = tts(cfg, db, e.id, first, language)
        price = to_usd(eng.estimate([sample_item(eng, language)]).micros)
    return {
        "model": e.id,
        "label": e.label,
        "local": e.provider == "local",
        "clone": e.clone,
        "speaks": not e.languages or language in e.languages,
        "presets": [{"id": v, "label": v.replace("_", " "), "sample": sample(v)} for v in e.voices],
        "recordings": [r | {"sample": sample(r["name"])} for r in recordings],
        "sample_usd": price,
    }


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


def _qualities(e: ModelEntry, price: Callable[[str | None], dict]) -> dict:
    """The row's price at the default quality, and the quality options with their own prices."""
    q = e.quality
    return {
        **price(None),
        "quality": {
            "param": q.param,
            "default": q.default,
            "options": [{"id": o, "label": q.labels.get(o, o), **price(o)} for o in q.options],
        }
        if q
        else None,
    }


def _image_row(cfg: Settings, db: Database | None, e: ModelEntry) -> dict:
    def per_picture(quality: str | None) -> dict:
        est = _image(cfg, db, e, quality).estimate([_picture(cfg)])
        return {"usd": to_usd(est.micros) if e.remote else None, "gpu_seconds": est.gpu_seconds or None}

    return {"per": "picture", **_qualities(e, per_picture)}


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

    return {"per": "second of video", "sound": e.audio == "ambience", **_qualities(e, per_second)}


def _tts_row(e: ModelEntry) -> dict:
    """Priced per minute of English narration: characters for remote models, GPU time for local ones."""
    est = chars_estimate(e, [wpm("en") * CHARS_PER_WORD]) if e.remote else gpu_estimate(e, units=60, items=1)
    return {
        "per": "minute of narration",
        "usd": to_usd(est.micros) if e.remote else None,
        "gpu_seconds": est.gpu_seconds or None,
        "quality": None,
    }


def _ambience_row(cfg: Settings, db: Database | None, e: ModelEntry) -> dict:
    est = ambience(cfg, db, e.id).estimate([_second()])
    return {"per": "second of sound", "usd": to_usd(est.micros // 10), "gpu_seconds": None, "quality": None}


def catalog(cfg: Settings, db: Database | None, capability: str) -> dict:
    """Every model a stage can use, with what it costs and whether it can run here now."""
    default = prefs.default_model(cfg, capability)
    rows = []
    for e in registry.by_capability(capability, cfg.library, db, cfg.hosted_edition):
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
        else:
            row |= _tts_row(e)
        rows.append(row)
    rows.sort(key=lambda r: (not r["local"], Decimal(str(r.get("usd") or 0))))
    return {"default": default, "models": rows}
