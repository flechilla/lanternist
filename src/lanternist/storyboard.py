"""The Storyboard: one JSON document that the writer produces, the editor edits and the renderer reads.

It replaces the prototype's story .txt plus .prompts/.cast/.motion sidecars. Narration is in the
story's language; visual, motion and sound prompts are always English, which image and video
models follow best.
"""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

Mode = Literal["still", "video"]
Camera = Literal["auto", "push_in", "pull_out", "pan_left", "pan_right", "static"]
Audience = Literal["toddlers", "kids_5_8", "kids_9_12", "teens", "adults"]
Subtitles = Literal["off", "sidecar", "burned"]
# OpenRouter's reasoning efforts, lowest first; each model supports some of them.
Effort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


def _writer_id(v: str) -> str:
    v = v.strip()
    if v and not re.fullmatch(r"(ollama|openrouter)/\S.*", v):
        raise ValueError("the writer is ollama/<model> or openrouter/<model id>")
    return v


# The model that writes a story: "ollama/<tag>" or "openrouter/<model id>". Empty means the default.
WriterId = Annotated[str, AfterValidator(_writer_id)]


def _model_id(v: str) -> str:
    v = v.strip()
    if v and not re.fullmatch(r"(local|fal)/\S+", v):
        raise ValueError("a media model is a registry id: local/<name> or fal/<name>")
    return v


# A media model from the registry (`lanternist models` lists them). Empty means the default.
ModelId = Annotated[str, AfterValidator(_model_id)]


class CastMember(BaseModel):
    id: str = Field(description="short lowercase slug, e.g. 'luna'")
    name: str
    look: str = Field(description="English visual description restated in every prompt showing them")


class Line(BaseModel):
    speaker: str = "narrator"
    text: str


class Scene(BaseModel):
    n: int
    narration: list[Line]
    visual: str = Field(description="English keyframe prompt: shot, setting, who does what")
    motion: str = Field("", description="English: what moves and how the camera moves")
    sound: str = Field("", description="English ambience only: no speech, no music")
    cast: list[str] = Field(default_factory=list, description="ids of cast members in the picture")
    camera: Camera = "auto"
    mode: Mode = "still"
    seed: int | None = None

    @property
    def text(self) -> str:
        return " ".join(line.text.strip() for line in self.narration if line.text.strip())


class Models(BaseModel):
    """Which model makes each stage; empty means the default from Settings."""

    writer: WriterId = Field("", description="ollama/<model> or openrouter/<model id>; rewrites use it too")
    writer_effort: Effort | None = Field(
        None, description="the writer's reasoning effort; None is the model's default"
    )
    image: ModelId = Field("", description="draws the cast sheet and the pictures")
    image_quality: str | None = Field(None, description="the picture model's quality option, e.g. 2K")


class Storyboard(BaseModel):
    title: str
    language: str = "en"
    audience: Audience = "kids_5_8"
    kind: str = "bedtime"
    style: str = Field("", description="English style suffix appended to every picture prompt")
    voice: str = "demo"
    seed: int = 7
    subtitles: Subtitles = "sidecar"
    cast: list[CastMember] = Field(default_factory=list)
    # Overrides the cast sheet prompt built from `cast` (imported stories carry their own).
    cast_sheet_prompt: str | None = None
    models: Models = Field(default_factory=Models)
    scenes: list[Scene]

    def scene_seed(self, scene: Scene) -> int:
        return scene.seed if scene.seed is not None else self.seed + scene.n

    def has_cast_sheet(self) -> bool:
        return bool(self.cast_sheet_prompt or self.cast)

    def renumber(self) -> "Storyboard":
        for i, s in enumerate(self.scenes, 1):
            s.n = i
        return self


def slugify(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "story"
