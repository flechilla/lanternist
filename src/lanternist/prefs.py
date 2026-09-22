"""Settings people change in the app, stored in the database's `settings` table.

A value saved here wins over lanternist.toml, which wins over the built-in default. Removing a
saved value falls back to the file. Only the keys in EDITABLE can be saved, and never API keys:
those live in the keychain (see keys.py).
"""

from pydantic import ValidationError

from . import registry
from .config import Settings, file_data
from .db import Database

EDITABLE = {
    "defaults.writer": "Writer model: empty for the local Ollama model, or ollama/<name>, openrouter/<id>",
    "defaults.tts": "Narration",
    "defaults.image": "Pictures",
    "defaults.video": "Video",
    "defaults.ambience": "Ambience, for video models with no sound of their own",
    "defaults.checker": "Picture check: a vision model looks at every picture before video is made from it, "
    "and has it drawn again when a character appears twice or someone extra walks in. openrouter/<id> or "
    "ollama/<name>; openrouter/openai/gpt-5.6-luna caught every such picture in our trials for under a tenth "
    "of a cent each. Empty: no check.",
    "defaults.budget_usd": "Budget per story for remote models, in USD",
    "openrouter.recommended": "Writer models pinned at the top of the picker",
    "openrouter.data_collection": "allow or deny providers that store prompts",
    "fal.max_concurrency": "fal requests running at once",
    "fal.media_ttl_hours": "Hours fal keeps the files it makes for us",
}
MODEL_KEYS = {
    "defaults.tts": "tts.speak",
    "defaults.image": "image.keyframe",
    "defaults.video": "video.image_to_video",
    "defaults.ambience": "audio.ambience",
}
# Model settings that may be "none", and what that means.
OFF = {"defaults.ambience": "Their scenes stay silent under the narration."}


def default_model(cfg: Settings, capability: str) -> str:
    """The model a stage uses when a story picks none."""
    key = next((k for k, c in MODEL_KEYS.items() if c == capability), None)
    if key is None:
        raise ValueError(f"no model list for '{capability}'")
    return _get(cfg, key)


def _apply(cfg: Settings, values: dict) -> Settings:
    data = cfg.model_dump()
    for key, value in values.items():
        section, field = key.split(".", 1)
        data[section][field] = value
    return Settings.model_validate(data)


def effective(cfg: Settings, db: Database) -> Settings:
    """`cfg` with the values saved in the app applied on top."""
    saved = {k: v for k, v in db.saved_settings().items() if k in EDITABLE}
    return _apply(cfg, saved) if saved else cfg


def _get(cfg: Settings, key: str):
    section, field = key.split(".", 1)
    return getattr(getattr(cfg, section), field)


def describe(cfg: Settings, db: Database) -> list[dict]:
    saved, written = db.saved_settings(), file_data()
    eff = effective(cfg, db)
    out = []
    for key, label in EDITABLE.items():
        section, field = key.split(".", 1)
        source = "app" if key in saved else "file" if field in written.get(section, {}) else "default"
        out.append(
            {
                "key": key,
                "label": label,
                "value": _get(eff, key),
                "source": source,
                "capability": MODEL_KEYS.get(key),
                "off": OFF.get(key),
            }
        )
    return out


def _check_model(key: str, value, library) -> None:
    if key in OFF and value == "none":
        return
    entry = registry.get(value, library)  # KeyError names the known ids
    if entry.capability != MODEL_KEYS[key]:
        raise ValueError(f"{value} is a {entry.capability} model, not {MODEL_KEYS[key]}")


def update(cfg: Settings, db: Database, changes: dict) -> None:
    """Save `changes`; a value of None removes the saved value. All or nothing."""
    unknown = sorted(set(changes) - set(EDITABLE))
    if unknown:
        raise ValueError(f"can't change {', '.join(unknown)} here")
    current = {k: v for k, v in db.saved_settings().items() if k in EDITABLE}
    merged = {**current, **{k: v for k, v in changes.items() if v is not None}}
    for k, v in changes.items():
        if v is None:
            merged.pop(k, None)
    try:
        new = _apply(cfg, merged)
    except ValidationError as e:
        raise ValueError(
            "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        ) from None
    for key in changes:
        if key in MODEL_KEYS:
            try:
                _check_model(key, _get(new, key), cfg.library)
            except KeyError as e:
                raise ValueError(str(e).strip("'\"")) from None
    if new.defaults.budget_usd < 0 or new.fal.max_concurrency < 1 or new.fal.media_ttl_hours <= 0:
        raise ValueError("budget must be ≥ 0, concurrency ≥ 1, and media hours > 0")
    for key, value in changes.items():
        if value is None:
            db.delete_setting(key)
        else:
            db.set_setting(key, value)
