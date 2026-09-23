"""Real models on this machine's GPU (~3 minutes): `uv run pytest -m gpu`."""

import pytest

from lanternist.config import Paths, Settings, settings
from lanternist.db import LOCAL
from lanternist.engines.ffmpeg import probe
from lanternist.pipeline import Pipeline
from lanternist.storyboard import CastMember, Line, Scene, Storyboard

pytestmark = pytest.mark.gpu


async def test_two_scene_film(tmp_path):
    base = settings()
    cfg = Settings(
        **{
            **base.model_dump(),
            "paths": Paths(library=tmp_path, voices=base.paths.voices),
            "fake_engines": False,
        }
    )
    sb = Storyboard(
        title="GPU smoke",
        style="soft watercolour storybook illustration, no text",
        subtitles="burned",
        cast=[CastMember(id="pip", name="Pip", look="small orange fox cub with a blue scarf")],
        scenes=[
            Scene(
                n=1,
                narration=[Line(text="Pip lived at the edge of a quiet pine forest.")],
                visual="Wide shot of a fox cub sitting at the edge of a pine forest at dusk",
                cast=["pip"],
            ),
            Scene(
                n=2,
                narration=[Line(text="Every evening, he watched the fireflies rise.")],
                visual="Medium shot of the fox cub looking up at glowing fireflies",
                cast=["pip"],
                motion="fireflies drift upward, the cub's tail sways",
                sound="crickets, soft wind",
                mode="video",
            ),
        ],
    )
    film = await Pipeline(cfg, owner=LOCAL).render(sb)
    info = probe(Pipeline(cfg, owner=LOCAL).store.path(film.film))
    assert info["width"] == 1920 and info["height"] == 1080 and info["has_audio"]
    assert 6 < info["duration"] < 20
