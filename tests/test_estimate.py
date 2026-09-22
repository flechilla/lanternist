"""The estimate before a board or render, and the budget that stops a remote stage before it spends."""

import time

import pytest

from lanternist.db import to_micros
from lanternist.estimate import estimate
from lanternist.pipeline import BudgetExceeded, Pipeline


def lines(quote: dict) -> dict:
    return {line["stage"]: line for line in quote["lines"]}


async def test_a_board_on_fal_is_priced_step_by_step_then_free_once_made(
    fake_cfg, db, fakes, story_row, make_story
):
    sb = make_story(("still", "video"))
    sb.models.image = "fal/flux-2-klein-9b"
    p = Pipeline(fake_cfg, db=db, story_id=story_row)
    before = estimate(p, sb, "board")
    pics = lines(before)["keyframes"]
    # The cast sheet at $0.006/MP, then two keyframes at (2.089 + 1) MP x $0.011.
    assert pics["todo"] == 3 and pics["cost_micros"] == 6_291 + 2 * 33_979
    assert lines(before)["narration"]["local"] and lines(before)["narration"]["cost_micros"] == 0
    assert before["total_micros"] == pics["cost_micros"] and not before["measured"]
    assert before["price_date"] == "2026-09-21" and before["budget_micros"] == to_micros("5")

    await p.board(sb)
    after = estimate(p, sb, "board")
    assert after["total_micros"] == 0 and after["measured"] and after["spent_micros"] > 0
    # The render adds only the one video scene, on the local model: GPU time, no money.
    motion = lines(estimate(p, sb, "render"))["motion"]
    assert motion["todo"] == 1 and motion["cost_micros"] == 0 and motion["gpu_seconds"] > 0


async def test_a_stage_over_budget_stops_before_spending_and_carries_on_once_raised(
    fake_cfg, db, fakes, story_row, make_story
):
    sb = make_story(("still", "video"))
    sb.models.image = "fal/nano-banana-pro"  # $0.15 a picture: three of them is $0.45
    p = Pipeline(fake_cfg, db=db, story_id=story_row, budget_micros=to_micros("0.30"))
    with pytest.raises(BudgetExceeded, match=r"needs \$0\.15 more") as e:
        await p.board(sb)
    assert e.value.info() == {
        "stage": "keyframes",
        "need_micros": 450_000,
        "spent_micros": 0,
        "budget_micros": 300_000,
        "short_micros": 150_000,
    }
    assert not fakes.fal.submits  # nothing was asked of fal

    p.budget_micros = to_micros("1")
    await p.board(sb)
    assert len(fakes.fal.submits) == 3


def test_a_cached_story_costs_nothing(fake_cfg, db, make_story):
    quote = estimate(Pipeline(fake_cfg, db=db), make_story(), "render")
    assert quote["total_micros"] == 0 and "budget_micros" not in quote  # all local, and no story row


# ------------------------------------------------------------------------------------ the API
def finished(client, job_id: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while (job := client.get(f"/api/jobs/{job_id}").json())["status"] in ("queued", "running"):
        assert time.time() < deadline, job
        time.sleep(0.1)
    return job


def test_the_estimate_and_the_budget_through_the_api(client, wait, make_story):
    sb = make_story(("still", "video")).model_dump()
    sb["models"]["image"] = "fal/nano-banana-2"
    sid = client.post("/api/stories", json={"storyboard": sb}).json()["story"]["id"]

    quote = client.get(f"/api/stories/{sid}/estimate", params={"kind": "board"}).json()
    assert quote["total_usd"] == 0.36  # three pictures at 2K, $0.12 each
    assert client.get(f"/api/stories/{sid}").json()["budget"] == {"usd": 5.0, "default": True, "spent_usd": 0}

    assert client.put(f"/api/stories/{sid}/budget", json={"usd": 0.2}).json()["usd"] == 0.2
    job = client.post(f"/api/stories/{sid}/board").json()
    assert job["estimate"]["total_usd"] == 0.36  # the estimate shown before it ran is kept on the job
    failed = finished(client, job["id"])
    assert failed["status"] == "failed" and failed["result"]["budget"]["short_usd"] == pytest.approx(0.16)
    assert "needs $0.16 more" in failed["error"]

    client.put(f"/api/stories/{sid}/budget", json={"usd": 1})
    wait(client.post(f"/api/stories/{sid}/board").json()["id"])
    detail = client.get(f"/api/stories/{sid}").json()
    assert detail["budget"]["spent_usd"] > 0
    assert client.get("/api/stories").json()[0]["spent_usd"] == detail["budget"]["spent_usd"]
    assert client.put(f"/api/stories/{sid}/budget", json={"usd": None}).json()["default"] is True
    assert client.put(f"/api/stories/{sid}/budget", json={"usd": -1}).status_code == 422
