"""Settings, read from lanternist.toml over defaults that match this machine.

Lookup order: $LANTERNIST_CONFIG, ./lanternist.toml, ~/.config/lanternist/lanternist.toml.
Every key is optional; see lanternist.example.toml for the full set.
"""

import os
import re
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .storyboard import WriterId


def _expand(v):
    return Path(os.path.expanduser(str(v)))


class Paths(BaseModel):
    model_config = ConfigDict(validate_default=True)
    library: Path = Path("~/Lanternist")
    # Reference voices: <name>.wav plus an optional <name>.txt transcript. First match wins.
    voices: list[Path] = [Path("~/Lanternist/voices"), Path("~/ai/bedtime-stories/voices")]

    @field_validator("library", mode="after")
    @classmethod
    def _lib(cls, v):
        return _expand(v)

    @field_validator("voices", mode="after")
    @classmethod
    def _voices(cls, v):
        return [_expand(p) for p in v]


class Ollama(BaseModel):
    url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.8:latest"
    num_ctx: int = 16384
    vram_gb: float = 22


class ComfyUI(BaseModel):
    model_config = ConfigDict(validate_default=True)
    url: str = "http://127.0.0.1:8199"
    root: Path = Path("~/comfyui")

    @field_validator("root", mode="after")
    @classmethod
    def _root(cls, v):
        return _expand(v)


class VenvEngine(BaseModel):
    python: Path
    weights: Path
    vram_gb: float

    @field_validator("python", "weights", mode="after")
    @classmethod
    def _p(cls, v):
        return _expand(v)


class Ltx(BaseModel):
    unet: str = "ltx-2.5-22b-distilled-transformer-nvfp4.safetensors"
    text_encoder: str = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
    vae: str = "ltx-2.5-video-vae-bf16.safetensors"
    audio_vae: str = "ltx-2.5-audio-vae-bf16.safetensors"
    upscaler: str = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
    width: int = 1280
    height: int = 704
    fps: int = 24
    max_seconds: float = 20.0
    strength: float = 0.7
    vram_gb: float = 26


class Engines(BaseModel):
    qwen3tts: VenvEngine = VenvEngine(
        python=Path("~/ai/bedtime-stories/engines/qwen3tts/.venv/bin/python"),
        weights=Path("~/ai/bedtime-stories/engines/qwen3tts/weights"),
        vram_gb=8,
    )
    klein: VenvEngine = VenvEngine(
        python=Path("~/ai/qwen-image-2.1/.venv/bin/python"),
        weights=Path("~/ai/flux2-klein-9b/weights"),
        vram_gb=24,
    )
    ltx: Ltx = Ltx()


class Render(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 24
    xfade: float = 0.8  # crossfade, centred on each scene boundary
    gap: float = 0.45  # silence between paragraphs' narration
    chunk_gap: float = 0.25  # silence between synthesis chunks, and between the shots of a paragraph
    lead_in: float = 0.5  # silence before the first word
    tail: float = 1.5  # the last shot breathes after the final word
    ambience: float = 0.3  # generated sound, ducked under the voice
    loudness: float = -16.0  # the film's integrated loudness, LUFS: where spoken web video and podcasts sit
    hold_max: float = 1.0  # a remote clip may end on its last frame held this long, rather than pay for more
    encoder: str = "h264_nvenc"
    bitrate: str = "12M"


class Defaults(BaseModel):
    """The model each stage uses when a story doesn't pick one. Values saved on the Settings page win."""

    writer: WriterId = ""  # empty: the local Ollama model above
    tts: str = "local/qwen3-tts-1.7b"
    image: str = "local/flux2-klein-9b"
    video: str = "local/ltx-2.5-22b-nvfp4"
    # Scores video scenes whose model makes no sound of its own (Kling, Veo); "none" leaves them silent.
    ambience: str = "fal/mmaudio-v2"
    # A vision model that checks every picture before video is made from it, and has a faulty one
    # drawn again: openrouter/<id> or ollama/<tag>; empty skips the check.
    checker: str = ""
    budget_usd: float = 5.0  # per story, for remote models

    @field_validator("checker", mode="after")
    @classmethod
    def _checker(cls, v: str) -> str:
        v = v.strip()
        if v and not re.fullmatch(r"(ollama|openrouter)/\S+", v):
            raise ValueError(
                "the picture check is ollama/<model> or openrouter/<model id>, or empty for none"
            )
        return v


class OpenRouter(BaseModel):
    url: str = "https://openrouter.ai/api/v1"
    # Pinned at the top of the writer picker: the best value from the Phase B trials (M2_PLAN.md).
    recommended: list[str] = [
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "deepseek/deepseek-v4.1-flash",
        "openai/gpt-5.6-luna",
    ]
    data_collection: Literal["allow", "deny"] = "deny"  # route only to providers that don't store prompts
    title: str = "Lanternist"  # attribution headers OpenRouter shows for the app
    referer: str = "https://github.com/lanternist/lanternist"


class Fal(BaseModel):
    queue_url: str = "https://queue.fal.run"
    api_url: str = "https://api.fal.ai"
    rest_url: str = "https://rest.fal.ai"  # storage tokens for uploads
    max_concurrency: int = 4  # requests running at once; fal queues the rest
    media_ttl_hours: float = 24  # fal keeps media public forever unless told otherwise
    voice_ttl_hours: float = 1  # reference voice clips we upload


class Settings(BaseModel):
    paths: Paths = Paths()
    ollama: Ollama = Ollama()
    comfyui: ComfyUI = ComfyUI()
    engines: Engines = Engines()
    render: Render = Render()
    defaults: Defaults = Defaults()
    openrouter: OpenRouter = OpenRouter()
    fal: Fal = Fal()
    fake_engines: bool = Field(default_factory=lambda: os.environ.get("LANTERNIST_FAKE_ENGINES") == "1")

    @property
    def library(self) -> Path:
        return self.paths.library


def config_path() -> Path | None:
    candidates = [
        os.environ.get("LANTERNIST_CONFIG"),
        "lanternist.toml",
        "~/.config/lanternist/lanternist.toml",
    ]
    for c in candidates:
        if c and _expand(c).is_file():
            return _expand(c)
    return None


def file_data() -> dict:
    """The config file as written, without defaults filled in."""
    path = config_path()
    return tomllib.loads(path.read_text()) if path else {}


@lru_cache
def settings() -> Settings:
    return Settings.model_validate(file_data())
