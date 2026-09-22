"""The picture check: a vision model's verdict on every picture, and a failing one drawn again."""

import json

import pytest
from sqlalchemy import select

from lanternist import check
from lanternist.cli import _checked
from lanternist.config import Settings
from lanternist.db import Job, StepRun, to_micros
from lanternist.jobs import Runner
from lanternist.pipeline import Board, BudgetExceeded, Pipeline, timing
from lanternist.storyboard import Storyboard, next_seed

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


def checking(cfg: Settings, model: str = "openrouter/fake/cheap") -> Settings:
    return cfg.model_copy(update={"defaults": cfg.defaults.model_copy(update={"checker": model})})


def check_runs(db) -> list[StepRun]:
    with db.session() as s:
        return list(s.execute(select(StepRun).where(StepRun.stage == "check")).scalars())


async def test_a_picture_that_fails_its_check_is_drawn_again_with_a_new_seed(fake_cfg, db, fakes, make_story):
    sb = make_story(("still",))
    first = sb.scene_seed(sb.scenes[0])
    fakes.openrouter.replies = [TWICE]  # the second look at it passes
    events = []
    p = Pipeline(checking(fake_cfg), events.append, db=db)
    b = await p.board(sb)
    assert b.redrawn == {1: "Ann appears twice."} and not b.flagged
    assert sb.scenes[0].seed == next_seed(first)
    assert len([e for e in events if e.stage == "keyframes" and e.status == "done"]) == 2
    assert any(e.message == "drawing again: scene 1: Ann appears twice." for e in events)
    assert [r.status for r in check_runs(db)] == ["done", "done"]

    # What the checker is sent: the picture, then who should be in it, for one strict verdict.
    body = fakes.openrouter.chats[-1]
    assert set(body) == {"model", "messages", "response_format", "provider", "temperature"}
    assert body["model"] == "fake/cheap" and body["temperature"] == 0.0
    assert body["response_format"]["json_schema"]["name"] == "picture_check"
    assert body["messages"][0] == {"role": "system", "content": check.SYSTEM}
    picture, asked = body["messages"][1]["content"]
    assert picture["type"] == "image_url" and picture["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )
    assert asked == {"type": "text", "text": check.question(sb, sb.scenes[0])}
    assert "- Ann: girl in a red coat" in asked["text"] and "a reflection in water" in asked["text"]


async def test_a_flagged_picture_is_not_drawn_again_on_the_next_board(fake_cfg, db, fakes, make_story):
    sb = make_story(("still",))
    first = sb.scene_seed(sb.scenes[0])
    fakes.openrouter.replies = [TWICE] * 3
    p = Pipeline(checking(fake_cfg), db=db)
    b = await p.board(sb)
    assert b.flagged == {1: "Ann appears twice."} and sb.scenes[0].seed == next_seed(next_seed(first))

    # Its verdict is cached: the next board flags it again, and asks and draws nothing.
    fakes.openrouter.chats.clear()
    events = []
    again = await Pipeline(checking(fake_cfg), events.append, db=db).board(sb)
    assert again.flagged == b.flagged and not again.redrawn and again.keyframes == b.keyframes
    assert not fakes.openrouter.chats and not [e for e in events if e.status == "done"]


def test_the_check_step_key_is_pinned(fake_cfg, make_story):
    """A change to what a verdict keys on asks the checker again about every picture."""
    sb = make_story(("still",))
    [item] = Pipeline(fake_cfg).check_items(sb, ["k" * 64 + ".png"], "openrouter/openai/gpt-5.6-luna")
    assert item.key == "6b65eca3598439b273e58a49745c43cb22b03dbea34d334edec030afca565f11"


async def test_the_check_stops_before_it_would_pass_the_budget(fake_cfg, db, fakes, story_row, make_story):
    p = Pipeline(checking(fake_cfg), db=db, story_id=story_row, budget_micros=0)
    with pytest.raises(BudgetExceeded) as e:
        await p.board(make_story(("still", "still")))
    # Two pictures at the fake model's prices: 1,500 tokens in at $0.1/M, 500 out at $0.4/M.
    assert e.value.info()["stage"] == "check" and e.value.need == 2 * to_micros("0.00035")
    assert not fakes.openrouter.chats


async def test_a_local_checker_is_shown_the_picture_through_ollama(fake_cfg, db, fakes, make_story):
    b = await Pipeline(checking(fake_cfg, "ollama/qwen3.8:latest"), db=db).board(make_story(("still",)))
    asked = fakes.ollama.chats[-1]["messages"][1]
    assert len(asked["images"]) == 1 and asked["content"].startswith("This picture was drawn")
    assert not b.flagged and not fakes.openrouter.chats


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
    assert job["version"] == 2  # nothing else was saved meanwhile: the job made version 2
    story = client.get(f"/api/stories/{sid}").json()
    assert story["version"] == 2 and story["storyboard"]["scenes"][0]["seed"] is not None
    assert story["board"]["scenes"][0]["keyframe"] == job["result"]["keyframes"][0]


def test_the_new_seeds_keep_an_edit_saved_while_the_job_ran(cfg, db, story_row, make_story):
    before = make_story(("still", "still"))
    started = db.add_version(story_row, before.model_dump(), note="the version the board runs")
    # While the board runs, the user retitles the story and changes scene 2's picture.
    edited = before.model_copy(deep=True)
    edited.title, edited.scenes[1].visual = "Retitled", "a different picture"
    db.add_version(story_row, edited.model_dump(), note="saved while it ran")
    after = before.model_copy(deep=True)
    after.scenes[0].seed, after.scenes[1].seed = 111, 222
    tl = timing.timeline([1.0, 1.0], 0.5, 0.5, 1.5, 0.8)
    board = Board([], None, [], tl, redrawn={1: "twice", 2: "twice"})
    with db.session() as s:
        job = Job(story_id=story_row, kind="board", version=started, params={}, progress={})
        s.add(job)
        s.commit()
        s.refresh(job)
    out = Runner(cfg, db).checked(job, before, after, board)
    with db.session() as s:
        _, row = db.storyboard(s, story_row)
        latest = Storyboard.model_validate(row.storyboard)
    assert out["version"] == started + 2 and "made_from" not in out
    assert latest.title == "Retitled" and latest.scenes[1].visual == "a different picture"
    # Scene 1's picture is still the one checked, so it takes its new seed; scene 2 was redrawn by
    # the edit, so its check no longer applies.
    assert [sc.seed for sc in latest.scenes] == [111, None]


def test_the_cli_writes_back_only_the_new_seeds(tmp_path, make_story, capsys):
    path = tmp_path / "story.json"
    sb = make_story(("still", "still"))
    path.write_text(sb.model_dump_json(), encoding="utf-8")
    sb.subtitles, sb.scenes[1].mode, sb.scenes[1].seed = (
        "burned",
        "video",
        999,
    )  # --subtitles, --mode, a redraw
    tl = timing.timeline([1.0, 1.0], 0.5, 0.5, 1.5, 0.8)
    _checked(path, sb, Board([], None, [], tl, redrawn={2: "twice"}, flagged={1: "text"}))
    saved = Storyboard.model_validate_json(path.read_text(encoding="utf-8"))
    assert saved.subtitles == "sidecar" and [s.mode for s in saved.scenes] == ["still", "still"]
    assert [s.seed for s in saved.scenes] == [None, 999]
    assert "scene 1 still fails its check: text" in capsys.readouterr().out
