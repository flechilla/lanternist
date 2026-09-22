"""The Storyboard: one JSON document that the writer produces, the editor edits and the renderer reads.

It replaces the prototype's story .txt plus .prompts/.cast/.motion sidecars. Narration is in the
story's language; visual, motion and sound prompts are always English, which image and video
models follow best.
"""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

Mode = Literal["still", "video"]
CastKind = Literal["character", "object"]
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


def _ambience_id(v: str) -> str:
    return v.strip() if v.strip() == "none" else _model_id(v)


# The ambience model, or "none" for silent video scenes. Empty means the default.
AmbienceId = Annotated[str, AfterValidator(_ambience_id)]


class CastMember(BaseModel):
    id: str = Field(description="short lowercase slug, e.g. 'luna'")
    name: str
    look: str = Field(description="English visual description restated in every prompt showing them")
    kind: CastKind = Field(
        "character",
        description="an object the story turns on is locked by its look alone, off the cast sheet",
    )


class Place(BaseModel):
    id: str = Field(description="short lowercase slug, e.g. 'windmill'")
    name: str
    look: str = Field(description="English description of the setting, restated in every picture set there")


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
    place: str = Field("", description="id of the place it's set in, if the story names its places")
    camera: Camera = "auto"
    mode: Mode = "still"
    seed: int | None = None
    video_seed: int | None = Field(None, description="a new take of the scene's video; None follows `seed`")
    continues: bool = Field(
        False,
        description="another shot of the same paragraph as the scene before: a short pause and a cut, not a fade",
    )

    @property
    def text(self) -> str:
        return " ".join(line.text.strip() for line in self.narration if line.text.strip())


class Models(BaseModel):
    """Which model makes each stage; empty means the default from Settings."""

    writer: WriterId = Field("", description="ollama/<model> or openrouter/<model id>; rewrites use it too")
    writer_effort: Effort | None = Field(
        None, description="the writer's reasoning effort; None is the model's default"
    )
    tts: ModelId = Field("", description="narrates; `Storyboard.voice` is one of its voices")
    image: ModelId = Field("", description="draws the cast sheet and the pictures")
    image_quality: str | None = Field(None, description="the picture model's quality option, e.g. 2K")
    video: ModelId = Field("", description="animates the video scenes")
    video_quality: str | None = Field(None, description="the video model's quality option, e.g. 768P")
    ambience: AmbienceId = Field(
        "", description="scores video scenes whose model makes no sound of its own; 'none' leaves them silent"
    )


class Storyboard(BaseModel):
    title: str
    language: str = "en"
    audience: Audience = "kids_5_8"
    kind: str = "bedtime"
    style: str = Field("", description="English style suffix appended to every picture prompt")
    voice: str = Field(
        "demo", description="a preset of the narration model, or a recording in voices/ it clones"
    )
    seed: int = 7
    subtitles: Subtitles = "sidecar"
    cast: list[CastMember] = Field(default_factory=list)
    # Overrides the cast sheet prompt built from `cast` (imported stories carry their own).
    cast_sheet_prompt: str | None = None
    # Each character drawn alone from the cast sheet, and each picture given only the portraits of
    # who is in it. Off, every picture gets the whole cast sheet, and draws characters who aren't in it.
    portraits: bool = False
    places: list[Place] = Field(default_factory=list)
    models: Models = Field(default_factory=Models)
    scenes: list[Scene]

    def scene_seed(self, scene: Scene) -> int:
        return scene.seed if scene.seed is not None else self.seed + scene.n

    def video_seed(self, scene: Scene) -> int:
        """The seed of the scene's video: its own after a new take, else the picture's."""
        return scene.video_seed if scene.video_seed is not None else self.scene_seed(scene)

    def has_cast_sheet(self) -> bool:
        return bool(self.cast_sheet_prompt or self.characters)

    @property
    def characters(self) -> list[CastMember]:
        """The cast on the cast sheet: everyone but the objects."""
        return [c for c in self.cast if c.kind == "character"]

    def renumber(self) -> "Storyboard":
        for i, s in enumerate(self.scenes, 1):
            s.n = i
        return self


def slugify(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "story"
