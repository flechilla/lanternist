"""The whole pipeline with fake engines: no GPU, a few seconds."""

import pytest

from lanternist.config import Paths, Settings
from lanternist.engines.ffmpeg import probe
from lanternist.pipeline import Pipeline
from lanternist.storyboard import CastMember, Line, Scene, Storyboard


@pytest.fixture
def cfg(tmp_path):
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "demo.wav").write_bytes(b"RIFF fake")
    return Settings(paths=Paths(library=tmp_path / "lib", voices=[voices]), fake_engines=True)


def story(modes=("still", "video", "still")) -> Storyboard:
    return Storyboard(
        title="Test", cast=[CastMember(id="a", name="Ann", look="girl in a red coat")],
        scenes=[Scene(n=i, narration=[Line(text=f"Scene {i} has a few words to say out loud here.")],
                      visual=f"picture {i}", cast=["a"], mode=m) for i, m in enumerate(modes, 1)],
        subtitles="burned")


async def test_render_then_cache_then_edit(cfg):
    events = []
    p = Pipeline(cfg, events.append)
    film = await p.render(story())
    info = probe(p.store.path(film.film))
    assert info["has_audio"] and info["width"] == 1920 and info["height"] == 1080
    assert info["duration"] == pytest.approx(film.duration, abs=0.1)
    assert film.srt and film.vtt

    # A second run is all cache hits.
    events.clear()
    again = await p.render(story())
    assert again.film == film.film
    assert not [e for e in events if e.status == "done"]

    # Editing one scene's picture redraws only that keyframe.
    events.clear()
    edited = story()
    edited.scenes[2].visual = "a different picture"
    await p.render(edited)
    redrawn = [e.scene for e in events if e.stage == "keyframes" and e.status == "done"]
    assert redrawn == [3]
    assert not [e for e in events if e.stage == "narration" and e.status == "done"]
