"""The picture check: a vision model's verdict on every picture, and a failing one drawn again."""

import json

from sqlalchemy import select

from lanternist.config import Settings
from lanternist.db import StepRun
from lanternist.pipeline import RETAKE, Pipeline

TWICE = json.dumps(
    {
        "seen": [{"who": "Ann", "count": 2}],
        "duplicated": ["Ann"],
        "unexpected": [],
        "missing": [],
        "wrong_size": [],
        "text": False,
        "verdict": "fail",
        "reason": "Ann appears twice.",
    }
)


def checking(cfg: Settings) -> Settings:
    return cfg.model_copy(
        update={"defaults": cfg.defaults.model_copy(update={"checker": "openrouter/fake/cheap"})}
    )


def check_runs(db) -> list[StepRun]:
    with db.session() as s:
        return list(s.execute(select(StepRun).where(StepRun.stage == "check")).scalars())


async def test_a_picture_that_fails_its_check_is_drawn_again_with_a_new_seed(fake_cfg, db, fakes, make_story):
    sb = make_story(("still",))
    first = sb.scene_seed(sb.scenes[0])
    fakes.openrouter.replies = [TWICE]  # the second look at it passes
    events = []
    b = await Pipeline(checking(fake_cfg), events.append, db=db).board(sb)
    assert b.redrawn == {1: "Ann appears twice."} and not b.flagged
    assert sb.scenes[0].seed == first + RETAKE
    assert len([e for e in events if e.stage == "keyframes" and e.status == "done"]) == 2
    assert any("drawing again: scene 1: Ann appears twice." in e.message for e in events)
    # The checker is shown the picture, and asked about who should be in it.
    asked = fakes.openrouter.chats[-1]["messages"][1]["content"]
    assert asked[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "- Ann: girl in a red coat" in asked[1]["text"]
    assert [r.status for r in check_runs(db)] == ["done", "done"]

    # Verdicts are cached with the pictures: a second board asks nothing and draws nothing.
    fakes.openrouter.chats.clear()
    again = await Pipeline(checking(fake_cfg), db=db).board(sb)
    assert not fakes.openrouter.chats and not again.redrawn and again.keyframes == b.keyframes


async def test_a_picture_still_failing_after_the_last_redraw_is_flagged(fake_cfg, db, fakes, make_story):
    sb = make_story(("still",))
    first = sb.scene_seed(sb.scenes[0])
    fakes.openrouter.replies = [TWICE] * 3
    b = await Pipeline(checking(fake_cfg), db=db).board(sb)
    assert b.flagged == {1: "Ann appears twice."} and sb.scenes[0].seed == first + 2 * RETAKE


async def test_without_a_checker_nothing_is_asked(fake_cfg, db, fakes, make_story):
    b = await Pipeline(fake_cfg, db=db).board(make_story())
    assert not fakes.openrouter.chats and not b.redrawn and not check_runs(db)


def test_a_board_job_keeps_the_new_seed_as_a_version(client, wait, make_story):
    from lanternist import providers

    assert (
        client.put(
            "/api/settings", json={"changes": {"defaults.checker": "openrouter/fake/cheap"}}
        ).status_code
        == 200
    )
    sid = client.post("/api/stories", json={"storyboard": make_story(("still",)).model_dump()}).json()[
        "story"
    ]["id"]
    providers.transport(Settings(fake_engines=True))  # the app's fake OpenRouter, to steer
    world = providers.fake_world()
    assert world is not None
    world.openrouter.replies = [TWICE]
    job = wait(client.post(f"/api/stories/{sid}/board").json()["id"])
    assert job["result"]["redrawn"] == {"1": "Ann appears twice."} and job["result"]["version"] == 2
    story = client.get(f"/api/stories/{sid}").json()
    assert story["version"] == 2 and story["storyboard"]["scenes"][0]["seed"] is not None
    assert story["board"]["scenes"][0]["keyframe"] == job["result"]["keyframes"][0]
