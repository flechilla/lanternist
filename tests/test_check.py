"""The picture check: a vision model's verdict on every picture, and a failing one drawn again."""

import asyncio
import json

import pytest
from sqlalchemy import select

from lanternist import check
from lanternist.check import CheckError
from lanternist.cli import _flagged, _keep_redraws
from lanternist.config import Settings
from lanternist.db import Job, StepRun, to_micros
from lanternist.doctor import needs, ollama_models
from lanternist.jobs import Progress, Runner
from lanternist.pipeline import Board, BudgetExceeded, Event, Pipeline, timing
from lanternist.storyboard import CastMember, Storyboard, next_seed

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


def with_defaults(cfg: Settings, **changes: str) -> Settings:
    return cfg.model_copy(update={"defaults": cfg.defaults.model_copy(update=changes)})


def checking(cfg: Settings, model: str = "openrouter/fake/cheap") -> Settings:
    return with_defaults(cfg, checker=model)


def with_portraits(sb: Storyboard) -> Storyboard:
    """Scene 1 with Ann and Bo, each drawn from a portrait of their own."""
    sb.cast.append(CastMember(id="bo", name="Bo", look="boy in a blue cap"))
    sb.scenes[0].cast, sb.portraits = ["a", "bo"], True
    return sb


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


async def test_the_progress_shows_a_failed_picture_until_its_redraw_lands(fake_cfg, db, fakes, make_story):
    fakes.openrouter.replies = [TWICE]
    job = db.add_job(None, "board", None, {}, None)
    progress = Progress(db, job.id)
    seen = []

    def follow(e: Event) -> None:
        progress.stage(e)
        if e.scene == 1 and e.stage in ("keyframes", "check"):
            steps = progress.snap["scenes"]["1"]
            check = steps.get("check", {})
            seen.append(
                (e.stage, e.status, check.get("state"), check.get("note"), steps["keyframes"].get("asset"))
            )

    await Pipeline(checking(fake_cfg), follow, db=db, job_id=job.id).board(make_story(("still",)))
    failed = next(
        i for i, (stage, _, state, _, _) in enumerate(seen) if stage == "check" and state == "failed"
    )
    assert seen[failed][3] == "Ann appears twice."
    # Drawn again: the old picture stays up beside the verdict until the new one lands.
    old = seen[failed][4]
    assert [(status, state, picture == old) for stage, status, state, _, picture in seen[failed + 1 :]][
        :3
    ] == [
        ("queued", "failed", True),
        ("working", "failed", True),
        ("done", "failed", False),
    ]
    steps = progress.snap["scenes"]["1"]
    # Two pictures and two verdicts: the page tells a verdict on the old picture by its fewer tries.
    assert steps["keyframes"]["tries"] == steps["check"]["tries"] == 2
    assert steps["check"]["state"] == "done" and "note" not in steps["check"]
    assert progress.snap["stages"]["check"]["model"] == "Fake Cheap"  # the checker by its name


async def test_a_fail_with_no_reason_is_still_a_fail(fake_cfg, db, fakes, make_story):
    fakes.openrouter.replies = [TWICE.replace('"Ann appears twice."', '""')]
    job = db.add_job(None, "board", None, {}, None)
    progress = Progress(db, job.id)
    states = []

    def follow(e: Event) -> None:
        progress.stage(e)
        if e.stage == "check" and e.status == "done":
            states.append(progress.snap["scenes"]["1"]["check"]["state"])

    b = await Pipeline(checking(fake_cfg), follow, db=db, job_id=job.id).board(make_story(("still",)))
    assert b.redrawn == {1: ""}
    assert states == ["failed", "done"]


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


NO_PICTURES = (404, {"error": {"code": 404, "message": "No endpoints found that support image input"}})


async def test_with_portraits_only_the_failing_picture_is_drawn_again(fake_cfg, db, fakes, make_story):
    sb = with_portraits(make_story(("still",)))
    first = sb.scene_seed(sb.scenes[0])
    fakes.openrouter.replies = [TWICE]
    events = []
    b = await Pipeline(checking(fake_cfg), events.append, db=db).board(sb)
    assert b.redrawn == {1: "Ann appears twice."} and sb.scenes[0].seed == next_seed(first)
    # The sheet and the portraits come from the cache; only the picture is drawn again.
    drawn = [e.stage for e in events if e.status == "done" and e.stage in ("cast", "portraits", "keyframes")]
    assert drawn == ["cast", "portraits", "portraits", "keyframes", "keyframes"]


async def test_a_checker_that_cant_see_pictures_says_to_pick_another(fake_cfg, db, fakes, make_story):
    fakes.openrouter.replies = [NO_PICTURES]
    with pytest.raises(
        CheckError, match=r"couldn't judge scene 1's picture.*Pick a checker that takes pictures"
    ):
        await Pipeline(checking(fake_cfg), db=db).board(make_story(("still",)))


async def test_a_checker_openrouter_doesnt_list_says_to_pick_another(fake_cfg, db, fakes, make_story):
    with pytest.raises(CheckError, match=r"can't use openrouter/fake/nowhere.*Pick a checker"):
        await Pipeline(checking(fake_cfg, "openrouter/fake/nowhere"), db=db).board(make_story(("still",)))


@pytest.mark.parametrize(
    ("reply", "says"),
    [
        # The key is no reason to change checkers; a model that won't take a picture is.
        (
            (401, {"error": {"code": 401, "message": "User not found."}}),
            "OpenRouter rejected the key: User not found.",
        ),
        (
            (400, {"error": {"code": 400, "message": "Image input is not supported."}}),
            f"OpenRouter error 400: Image input is not supported. {check.PICK_ANOTHER}",
        ),
    ],
)
async def test_a_check_that_fails_says_what_to_do_about_it(fake_cfg, db, fakes, make_story, reply, says):
    fakes.openrouter.replies = [reply]
    with pytest.raises(CheckError) as e:
        await Pipeline(checking(fake_cfg), db=db).board(make_story(("still",)))
    assert str(e.value) == (
        f"The picture check with openrouter/fake/cheap couldn't judge scene 1's picture: {says}"
    )


async def test_a_fail_given_before_the_check_broke_draws_that_picture_again(fake_cfg, db, fakes, make_story):
    sb = make_story(("still", "still"))
    seeds = [sb.scene_seed(sc) for sc in sb.scenes]
    fakes.openrouter.replies = [TWICE, NO_PICTURES]  # one picture fails; the other can't be judged
    p = Pipeline(checking(fake_cfg), db=db)
    with pytest.raises(CheckError):
        await p.board(sb)
    [n] = p.redrawn
    assert sb.scenes[n - 1].seed == next_seed(seeds[n - 1])
    # The next board draws that picture again and asks about it, rather than only flagging the one
    # that failed, whose verdict is cached.
    assert not (await Pipeline(checking(fake_cfg), db=db).board(sb)).flagged


async def test_a_check_that_breaks_on_its_last_look_draws_nothing_past_the_limit(
    fake_cfg, db, fakes, make_story
):
    sb = make_story(("still", "still"))
    limit = [next_seed(next_seed(sb.scene_seed(sc))) for sc in sb.scenes]
    assert check.MAX_REDRAWS == 2
    fakes.openrouter.replies = [TWICE] * 4 + [TWICE, NO_PICTURES]  # both fail twice; then one breaks
    with pytest.raises(CheckError):
        await Pipeline(checking(fake_cfg), db=db).board(sb)
    assert [sc.seed for sc in sb.scenes] == limit  # the last look's fail is only flagged, as it would be


def test_the_doctor_counts_the_checkers_provider_and_model(fake_cfg):
    local = with_defaults(fake_cfg, writer="ollama/qwen3.8:latest")
    assert not needs(local)["openrouter"] and needs(checking(local))["openrouter"]
    remote = with_defaults(fake_cfg, writer="openrouter/fake/cheap")
    assert not needs(remote)["ollama"] and needs(checking(remote, "ollama/llava:latest"))["ollama"]
    # It looks for the models the defaults run on, not a configured one nothing uses.
    assert ollama_models(checking(remote, "ollama/llava:latest")) == ["llava:latest"]
    assert ollama_models(checking(local, "ollama/llava:latest")) == ["qwen3.8:latest", "llava:latest"]
    assert ollama_models(remote) == [fake_cfg.ollama.model]


async def test_a_cached_board_needs_no_prices(fake_cfg, db, fakes, make_story, monkeypatch):
    sb = make_story(("still",))
    await Pipeline(checking(fake_cfg), db=db).board(sb)

    async def offline(self):
        raise AssertionError("a board with every verdict cached asked for prices")

    monkeypatch.setattr(check.Checker, "price", offline)
    assert not (await Pipeline(checking(fake_cfg), db=db).board(sb)).flagged


def job_row(db, story_id: str, version: int, kind: str = "board") -> Job:
    with db.session() as s:
        job = Job(story_id=story_id, kind=kind, version=version, params={}, progress={})
        s.add(job)
        s.commit()
        s.refresh(job)
        return job


@pytest.mark.parametrize("edit_lands", ["while the job ran", "as the seeds are saved"])
async def test_the_new_seeds_keep_an_edit_saved_while_the_job_ran(
    fake_cfg, db, story_row, make_story, lands_first, edit_lands
):
    before = make_story(("still", "still"))
    started = db.add_version(story_row, before.model_dump(), note="the version the board runs")
    p = Pipeline(fake_cfg, db=db, story_id=story_row)
    await p.draw(before)
    # While the board runs, the user retitles the story and changes scene 2's picture.
    edited = before.model_copy(deep=True)
    edited.title, edited.scenes[1].visual = "Retitled", "a different picture"

    def save_the_edit() -> None:
        db.add_version(story_row, edited.model_dump(), note="saved while it ran")

    if edit_lands == "while the job ran":
        save_the_edit()
    else:  # at the same moment as the seeds: they're applied once more, to the edit
        lands_first(db, save_the_edit)
    after = before.model_copy(deep=True)
    after.scenes[0].seed, after.scenes[1].seed = 111, 222
    p.redrawn = {1: "twice", 2: "twice"}
    runner = Runner(fake_cfg, db)
    assert runner.keep_redraws(p, job_row(db, story_row, started), before, after) == (started + 2, [1])
    _, row = db.storyboard(story_row)
    latest, note = Storyboard.model_validate(row.storyboard), row.note
    assert latest.title == "Retitled" and latest.scenes[1].visual == "a different picture"
    # Scene 1's picture is still the one checked, so it takes its new seed; scene 2 was redrawn by
    # the edit, so its check no longer applies, and the note doesn't claim it.
    assert [sc.seed for sc in latest.scenes] == [111, None]
    assert note == "the picture check drew scene 1 again"

    # When every scene drawn again was edited meanwhile, nothing is saved.
    p.redrawn = {2: "twice"}
    assert runner.keep_redraws(p, job_row(db, story_row, started), before, after) is None


async def test_a_look_edited_while_the_job_ran_keeps_its_new_seed_out(fake_cfg, db, story_row, make_story):
    before = with_portraits(make_story(("still",)))
    started = db.add_version(story_row, before.model_dump(), note="the version the board runs")
    p = Pipeline(fake_cfg, db=db, story_id=story_row)
    await p.draw(before)
    edited = before.model_copy(deep=True)
    edited.cast[1].look = "boy in a red cap"  # a new cast sheet and portraits, so a new picture
    db.add_version(story_row, edited.model_dump(), note="saved while it ran")
    after = before.model_copy(deep=True)
    after.scenes[0].seed = 111
    p.redrawn = {1: "twice"}
    assert Runner(fake_cfg, db).keep_redraws(p, job_row(db, story_row, started), before, after) is None


def stop_when_drawing_again(e: Event) -> None:
    """Stops the board as a cancel would, just after the check gave a picture its new seed."""
    if e.message.startswith("drawing again"):
        raise asyncio.CancelledError


@pytest.mark.parametrize(
    ("ending", "job_takes_it"), [("error", False), ("shutdown", True), ("cancel", False)]
)
async def test_a_board_stopped_after_a_redraw_keeps_its_new_seed(
    fake_cfg, db, fakes, story_row, make_story, ending, job_takes_it
):
    """The new seed is saved however the board stops. A shutdown queues the job again, so it moves to
    that version and runs from the new seed; a job that failed or was cancelled keeps the version whose
    pictures it drew, which the story page shows its pictures for."""
    sb = make_story(("still",))
    first = sb.scene_seed(sb.scenes[0])
    started = db.add_version(story_row, sb.model_dump(), note="the version the board runs")
    job, runner = job_row(db, story_row, started), Runner(fake_cfg, db)
    if ending == "error":
        fakes.openrouter.replies = [TWICE, NO_PICTURES]  # the second look fails outright
        p = Pipeline(checking(fake_cfg), db=db, story_id=story_row)
    else:
        fakes.openrouter.replies = [TWICE]
        p = Pipeline(checking(fake_cfg), stop_when_drawing_again, db=db, story_id=story_row)
        if ending == "cancel":
            runner.cancel_requested.add(job.id)
    with pytest.raises((CheckError, asyncio.CancelledError)):
        await runner.checked_board(p, job, sb)
    story, row = db.storyboard(story_row)
    assert story.version == started + 1
    assert Storyboard.model_validate(row.storyboard).scenes[0].seed == next_seed(first)
    assert db.get_job(job.id).version == (started + 1 if job_takes_it else started)


def job_with_a_redraw(client, wait, fakes, story: Storyboard, kind: str) -> tuple[str, dict]:
    """A board or render job, through the API, whose check fails its one picture once."""
    changes = {"defaults.checker": "openrouter/fake/cheap"}
    assert client.put("/api/settings", json={"changes": changes}).status_code == 200
    sid = client.post("/api/stories", json={"storyboard": story.model_dump()}).json()["story"]["id"]
    fakes.openrouter.replies = [TWICE]
    return sid, wait(client.post(f"/api/stories/{sid}/{kind}").json()["id"])


def test_a_render_job_names_its_film_for_the_version_its_check_saved(client, wait, fakes, make_story):
    _, job = job_with_a_redraw(client, wait, fakes, make_story(("still",)), "render")
    assert job["version"] == 2 and job["result"]["version"] == 2 and job["result"]["path"].endswith("-v2.mp4")
    assert "made_from" not in job["result"]


def test_a_board_job_keeps_the_new_seed_as_a_version(client, wait, fakes, make_story):
    sid, job = job_with_a_redraw(client, wait, fakes, make_story(("still",)), "board")
    assert job["result"]["redrawn"] == {"1": "Ann appears twice."} and job["result"]["version"] == 2
    assert job["version"] == 2  # nothing else was saved meanwhile: the job made version 2
    story = client.get(f"/api/stories/{sid}").json()
    assert story["version"] == 2 and story["storyboard"]["scenes"][0]["seed"] is not None
    assert story["board"]["scenes"][0]["keyframe"] == job["result"]["keyframes"][0]


def test_a_checker_that_isnt_an_llm_is_refused(client):
    r = client.put("/api/settings", json={"changes": {"defaults.checker": "gpt"}})
    assert r.status_code == 422 and "an LLM is ollama/<model> or openrouter/<model id>" in r.json()["detail"]


def test_the_cli_writes_back_only_the_new_seeds(tmp_path, make_story):
    path = tmp_path / "story.json"
    sb = make_story(("still", "still"))
    path.write_text(sb.model_dump_json(), encoding="utf-8")
    sb.subtitles, sb.scenes[1].mode, sb.scenes[1].seed = (
        "burned",
        "video",
        999,
    )  # --subtitles, --mode, a redraw
    _keep_redraws(path, sb, {2: "twice"})
    saved = Storyboard.model_validate_json(path.read_text(encoding="utf-8"))
    assert saved.subtitles == "sidecar" and [s.mode for s in saved.scenes] == ["still", "still"]
    assert [s.seed for s in saved.scenes] == [None, 999]


def test_the_cli_names_the_pictures_still_failing(capsys):
    tl = timing.timeline([1.0, 1.0], 0.5, 0.5, 1.5, 0.8)
    _flagged(Board([], None, [], tl, flagged={1: "text"}))
    assert "scene 1 still fails its check: text" in capsys.readouterr().out
