"""The whole pipeline with fake engines: no GPU, a few seconds."""

import pytest

from lanternist.engines.ffmpeg import probe
from lanternist.pipeline import Pipeline


async def test_render_then_cache_then_edit(fake_cfg, make_story):
    events = []
    p = Pipeline(fake_cfg, events.append)
    film = await p.render(make_story(subtitles="burned"))
    info = probe(p.store.path(film.film))
    assert info["has_audio"] and info["width"] == 1920 and info["height"] == 1080
    assert info["duration"] == pytest.approx(film.duration, abs=0.1)
    assert film.srt and film.vtt

    # A second run is all cache hits.
    events.clear()
    again = await p.render(make_story(subtitles="burned"))
    assert again.film == film.film
    assert not [e for e in events if e.status == "done"]

    # Editing one scene's picture redraws only that keyframe.
    events.clear()
    edited = make_story(subtitles="burned")
    edited.scenes[2].visual = "a different picture"
    await p.render(edited)
    redrawn = [e.scene for e in events if e.stage == "keyframes" and e.status == "done"]
    assert redrawn == [3]
    assert not [e for e in events if e.stage == "narration" and e.status == "done"]
