"""The narrator's voices: reference recordings in the voices folders, which clone engines copy.

A voice is `<name>.wav`, plus an optional `<name>.txt` transcript that makes the clone closer. The
first folder in `paths.voices` holding the name wins, and new recordings go into the first folder.
"""

from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .store import file_sha


@dataclass
class Voice:
    name: str
    wav: Path
    text: str | None
    sha: str


def find_voice(cfg: Settings, name: str) -> Voice:
    for d in cfg.paths.voices:
        wav = d / f"{name}.wav"
        if wav.is_file():
            txt = wav.with_suffix(".txt")
            transcript = txt.read_text(encoding="utf-8").strip() if txt.is_file() else None
            return Voice(name, wav, transcript or None, file_sha(wav))
    raise FileNotFoundError(
        f"no voice '{name}': looked for {name}.wav in " + ", ".join(str(d) for d in cfg.paths.voices)
    )


def list_voices(cfg: Settings) -> list[dict]:
    seen, out = set(), []
    for d in cfg.paths.voices:
        for wav in sorted(d.glob("*.wav")) if d.is_dir() else []:
            if wav.stem not in seen:
                seen.add(wav.stem)
                out.append(
                    {"name": wav.stem, "path": str(wav), "has_transcript": wav.with_suffix(".txt").is_file()}
                )
    return out
