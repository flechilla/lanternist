"""The writer on Ollama and OpenRouter, against the in-process fakes: no keys, no network, no GPU."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from pydantic import ValidationError

from lanternist import llm, providers
from lanternist.config import Paths, Settings
from lanternist.db import Job, StepRun, Story, to_micros, to_usd
from lanternist.llm import Calls, LLMError, pick_effort, strict_schema
from lanternist.providers.fake import FAKE_STORY
from lanternist.providers.openrouter import OpenRouterError
from lanternist.storyboard import Models
from lanternist.writer import (
    Brief,
    RewrittenScene,
    WriterBoard,
    board_prompt,
    inline_schema,
    json_text,
    rewrite_scene,
    write_storyboard,
)

IDEA = "A lighthouse cat is scared of the dark, until an old gull shows her the stars."


@pytest.fixture
def cfg(tmp_path) -> Settings:
    return Settings(paths=Paths(library=tmp_path / "lib"), fake_engines=True)


@pytest.fixture
def world(cfg):
    providers.transport(cfg)  # creates the fake world fake mode uses
    return providers.fake_world()


@pytest.fixture
def leases(monkeypatch) -> list[str]:
    taken: list[str] = []

    @asynccontextmanager
    async def fake_lease(cfg, owner, need_gb):
        taken.append(owner)
        yield

    monkeypatch.setattr(llm, "lease", fake_lease)
    return taken


def brief(**kw) -> Brief:
    # 0.4 minutes is 60 words: the fake story's length, so no revision round.
    return Brief(idea=IDEA, minutes=0.4, **kw)


def fake_cost(prompt: int, completion: int) -> int:
    """What the fake OpenRouter reports for a call, in micros."""
    return to_micros(round(prompt * 3e-6 + completion * 15e-6, 8))


def empty_reply(cost: float) -> dict:
    """An answer cut off by the token limit before it wrote anything: still paid for."""
    return {
        "id": "gen-x",
        "model": "fake/frontier",
        "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "length"}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 32000,
            "cost": cost,
            "completion_tokens_details": {"reasoning_tokens": 32000},
        },
    }


def write_runs(db) -> list[StepRun]:
    with db.session() as s:
        return s.query(StepRun).order_by(StepRun.id).all()


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for v in node.values():
            yield from _objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v)


def test_strict_schema_closes_every_object():
    schema = strict_schema(inline_schema(WriterBoard))
    objects = list(_objects(schema))
    assert len(objects) == 5  # the board, a cast member, a place, a scene, a shot
    for o in objects:
        assert o["additionalProperties"] is False and set(o["required"]) == set(o["properties"])
    assert "default" not in json.dumps(strict_schema(inline_schema(RewrittenScene)))
    # A property named "title" or "default" survives: only schema keywords are touched.
    assert "title" in schema["properties"]


def test_pick_effort_uses_what_the_model_supports():
    luna = {"reasoning": {"supported_efforts": ["max", "xhigh", "high", "medium", "low", "none"]}}
    mandatory = {"reasoning": {"mandatory": True, "supported_efforts": ["high", "medium", "low"]}}
    assert pick_effort("high", luna) == "high"
    assert pick_effort(None, luna) is None  # the model's own default
    assert pick_effort("none", mandatory) == "low"  # can't switch reasoning off: the lowest it has
    assert pick_effort("max", mandatory) == "high"
    assert pick_effort("minimal", luna) == "low"  # nearest; a tie goes up
    assert pick_effort("high", {}) is None  # no effort control at all


def test_the_writer_and_effort_are_checked_wherever_they_enter():
    assert brief(writer=" openrouter/x/y ").writer == "openrouter/x/y"
    for bad in ("gpt-5", "openrouter/", "local/qwen"):
        with pytest.raises(ValidationError, match="an LLM is ollama/<model> or openrouter/<model id>"):
            brief(writer=bad)
        with pytest.raises(ValidationError, match="an LLM is"):  # a storyboard saved from the editor
            Models(writer=bad)
    with pytest.raises(ValidationError, match="effort"):
        brief(effort="huge")
    with pytest.raises(ValidationError, match="writer_effort"):
        Models(writer_effort="huge")


def test_replies_are_unwrapped_before_validation():
    assert json_text('<think>which cat?</think>\n```json\n{"title": "T"}\n```') == '{"title": "T"}'
    assert json_text('```\n{"a": 1}\n```') == '{"a": 1}'
    assert json_text(' {"a": 1} ') == '{"a": 1}'


def test_a_story_without_a_title_is_storyboarded_as_untitled():
    _, user = board_prompt(brief(), None, ["The cat looks up at the stars."])
    assert user.startswith("Story: (untitled)\n")  # was "Story: None"


async def test_openrouter_writer_end_to_end(cfg, db, world, leases):
    calls = Calls(db)
    sb = await write_storyboard(cfg, brief(writer="openrouter/fake/frontier", effort="high"), calls=calls)
    assert len(sb.scenes) == 4 and sb.cast and sb.models.writer == "openrouter/fake/frontier"
    assert sb.models.writer_effort == "high"
    assert leases == []  # nothing touched the GPU
    story, board = world.openrouter.chats
    assert "response_format" not in story and story["temperature"] == 0.8
    fmt = board["response_format"]["json_schema"]
    assert fmt["strict"] and fmt["name"] == "storyboard" and fmt["schema"]["additionalProperties"] is False
    assert board["provider"] == {"data_collection": "deny", "require_parameters": True}
    assert board["reasoning"] == {"effort": "high", "exclude": True} and board["max_tokens"] == 32000
    assert world.ollama.chats == []

    runs = write_runs(db)
    assert [(r.stage, r.provider, r.status, r.cost_source) for r in runs] == [
        ("write", "openrouter", "done", "reported")
    ] * 2
    assert [r.cost_micros for r in runs] == [
        fake_cost(r.meta["tokens_in"], r.meta["tokens_out"]) for r in runs
    ]
    assert all(r.meta["effort"] == "high" for r in runs)
    info = calls.summary()
    assert calls.cost_micros == sum(r.cost_micros for r in runs)
    assert info == {
        "writer": "openrouter/fake/frontier",
        "cost_usd": to_usd(calls.cost_micros),
        "calls": 2,
        "tokens_in": sum(r.meta["tokens_in"] for r in runs),
        "tokens_out": sum(r.meta["tokens_out"] for r in runs),
    }


async def test_parameters_follow_the_model(cfg, db, world, leases):
    await write_storyboard(cfg, brief(writer="openrouter/fake/reasoner", effort="none"))
    for body in world.openrouter.chats:
        assert "temperature" not in body  # the model doesn't take one
        assert body["reasoning"] == {"effort": "low", "exclude": True}
        assert body["max_tokens"] == 16384  # no limit listed: the safe default
    world.openrouter.chats.clear()
    await write_storyboard(cfg, brief(writer="openrouter/fake/cheap", effort="high"))
    for body in world.openrouter.chats:
        assert "max_tokens" not in body and "reasoning" not in body  # it takes neither
        assert body["temperature"] in (0.8, 0.4)


async def test_a_schema_goes_only_with_parameters_one_provider_takes(cfg, db, world, leases):
    # Like Claude Opus 5: the providers with structured output take no temperature, the one that takes a
    # temperature has no structured output, and the model list shows the union of the two.
    world.openrouter.models.append(
        {
            "id": "fake/split",
            "name": "Fake Split",
            "pricing": {"prompt": "0.000005", "completion": "0.000025"},
            "supported_parameters": ["structured_outputs", "response_format", "reasoning", "temperature"],
            "reasoning": {"supported_efforts": ["high", "medium", "low"]},
            "endpoints": [
                ["structured_outputs", "response_format", "reasoning", "max_tokens"],
                ["temperature", "response_format", "reasoning", "max_tokens"],
            ],
        }
    )
    await write_storyboard(cfg, brief(writer="openrouter/fake/split", effort="low"))
    story, board = world.openrouter.chats
    assert story["temperature"] == 0.8  # no schema: a provider that lacks it ignores it
    assert "temperature" not in board and board["reasoning"]["effort"] == "low"
    assert board["max_tokens"] == 16384 and board["provider"]["require_parameters"] is True


async def test_without_the_provider_list_the_models_own_parameters_are_used(cfg, db, world, leases, caplog):
    world.openrouter.endpoints_down = True
    with caplog.at_level(logging.WARNING, logger="lanternist.llm"):
        await write_storyboard(cfg, brief(writer="openrouter/fake/frontier", effort="low"))
    board = world.openrouter.chats[1]
    assert (
        board["temperature"] == 0.4 and board["reasoning"]["effort"] == "low" and board["max_tokens"] == 32000
    )
    assert "no provider list for fake/frontier" in caplog.text


async def test_ollama_path_is_unchanged(cfg, db, world, leases):
    calls = Calls(db)
    sb = await write_storyboard(cfg, brief(), calls=calls)
    assert sb.models.writer == "ollama/qwen3.8:latest" and len(sb.scenes) == 4
    assert leases == ["ollama"]  # one lease around the whole story
    story, board = world.ollama.chats
    assert story["think"] is False and "format" not in story and board["format"]["type"] == "object"
    assert "additionalProperties" not in board["format"]  # Ollama gets the plain inlined schema
    assert world.openrouter.chats == []
    with db.session() as s:
        runs = s.query(StepRun).all()
        assert [(r.provider, r.cost_micros, r.cost_source) for r in runs] == [("ollama", None, "none")] * 2
    assert calls.cost_micros is None


async def test_the_default_writer_comes_from_settings(cfg, db, world, leases):
    cfg.defaults.writer = "openrouter/fake/cheap"
    sb = await write_storyboard(cfg, brief())
    assert sb.models.writer == "openrouter/fake/cheap" and leases == []


async def test_rewrites_use_the_storys_writer(cfg, db, world, leases):
    sb = await write_storyboard(cfg, brief(writer="openrouter/fake/cheap"))
    world.openrouter.chats.clear()
    cfg.defaults.writer = "openrouter/fake/frontier"  # a different default must not matter
    world.openrouter.replies.append(
        json.dumps(
            {
                "narration": "  A new   line. ",
                "visual": "a new picture",
                "motion": "waves",
                "sound": "wind",
                "cast": [sb.cast[0].id, "nobody"],
                "place": "the moon",
                "camera": "push_in",
            }
        )
    )
    assert sb.scenes[1].place  # the fake writer sets every shot in its one place
    scene = await rewrite_scene(cfg, sb, 2, "make it windier")
    assert [c["model"] for c in world.openrouter.chats] == ["fake/cheap"]
    assert scene.text == "A new line." and scene.cast == [sb.cast[0].id] and scene.camera == "push_in"
    assert scene.place == ""  # moved somewhere the story has no place for: its visual describes it
    assert "writer_effort" not in world.openrouter.chats[0]["messages"][1]["content"]  # not shown to the LLM


async def test_a_length_stop_retries_with_more_room(cfg, db, world, leases):
    story = {
        "id": "gen-y",
        "model": "fake/frontier",
        "choices": [{"message": {"role": "assistant", "content": FAKE_STORY}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "cost": 0.012345},
    }
    world.openrouter.replies += [empty_reply(0.5), story]
    calls = Calls(db)
    await write_storyboard(cfg, brief(writer="openrouter/fake/frontier"), calls=calls)
    assert [c["max_tokens"] for c in world.openrouter.chats[:2]] == [32000, 64000]
    first = calls.replies[0]  # the wasted attempt is paid for, so it's counted
    assert (first.cost_micros, first.tokens_in, first.tokens_out, first.reasoning_tokens) == (
        512_345,
        110,
        32_200,
        32_000,
    )
    assert write_runs(db)[0].cost_micros == 512_345


@pytest.mark.parametrize(
    ("writer", "replies", "max_tokens", "paid"),
    [
        ("openrouter/fake/reasoner", [0.5], [16384], 500_000),  # already at its limit: no retry
        ("openrouter/fake/frontier", [0.5, 0.25], [32000, 64000], 750_000),  # the retry ran out too
    ],
)
async def test_a_length_stop_that_fails_still_records_what_it_cost(
    cfg, db, world, leases, writer, replies, max_tokens, paid
):
    world.openrouter.replies += [empty_reply(c) for c in replies]
    with pytest.raises(LLMError, match="spent its whole token budget"):
        await write_storyboard(cfg, brief(writer=writer), calls=Calls(db))
    assert [c["max_tokens"] for c in world.openrouter.chats] == max_tokens
    (run,) = write_runs(db)
    assert (run.status, run.cost_micros, run.cost_source) == ("failed", paid, "reported")
    assert db.spend_micros() == paid


async def test_failed_calls_are_logged(cfg, db, world, leases):
    world.openrouter.replies.append(
        (403, {"error": {"code": 403, "message": "flagged", "metadata": {"reasons": ["violence"]}}})
    )
    with pytest.raises(OpenRouterError, match="refused"):
        await write_storyboard(cfg, brief(writer="openrouter/fake/frontier"), calls=Calls(db))
    (run,) = write_runs(db)
    assert run.status == "failed" and "violence" in run.error and run.cost_micros is None


async def test_a_cancelled_call_is_recorded_as_cancelled(cfg, db, world, leases):
    calls = Calls(db)
    writer = llm.make(cfg, "openrouter/fake/cheap", calls=calls)
    run_id = calls.start(writer)
    calls.failed(run_id, asyncio.CancelledError(), 1.5)
    (run,) = write_runs(db)
    assert (run.status, run.error, run.cost_micros, run.wall_seconds) == ("cancelled", None, None, 1.5)


async def test_an_unknown_model_fails_before_any_call(cfg, db, world, leases):
    with pytest.raises(LLMError, match="isn't an OpenRouter model"):
        await write_storyboard(cfg, brief(writer="openrouter/fake/nothing"))
    assert world.openrouter.chats == []


async def test_catalog_orders_and_prices_the_writers(cfg, db, world):
    cfg.openrouter.recommended = ["fake/cheap"]
    cat = await llm.catalog(cfg, db)
    ids = [m["id"] for m in cat["models"]]
    assert ids == [
        "ollama/qwen3.8:latest",
        "openrouter/fake/cheap",
        "openrouter/fake/frontier",
        "openrouter/fake/reasoner",
    ]  # no embeddings, no :batch
    assert cat["default"] == "ollama/qwen3.8:latest"
    assert cat["models"][0]["usd_per_minute"] == 0 and cat["models"][1]["recommended"]
    frontier = cat["models"][2]
    assert frontier["basis"] == "typical" and frontier["model"] == "fake/frontier"
    assert [e["id"] for e in frontier["efforts"]] == ["none", "low", "medium", "high", "max"]
    assert frontier["efforts"][0] == {"id": "none", "name": "Off"}
    # 700 tokens in at $3 per million and 2900 out at $15: $0.0021 + $0.0435.
    assert (frontier["usd_per_minute"], frontier["price_in"], frontier["price_out"]) == (0.0456, 3.0, 15.0)
    assert cat["providers"]["openrouter"]["configured"]


async def test_the_default_writer_is_listed_even_when_nobody_offers_it(cfg, db, world):
    cfg.defaults.writer = "openrouter/retired/model"
    first = (await llm.catalog(cfg, db))["models"][0]
    assert (
        first["id"] == "openrouter/retired/model" and first["unavailable"] and first["usd_per_minute"] is None
    )


async def test_measured_tokens_replace_the_typical_ones(cfg, db, world, leases):
    with db.session() as s:
        st = Story(slug="s", title="S", language="en", version=0)
        s.add(st)
        s.flush()
        job = Job(story_id=st.id, kind="write", params={"minutes": 0.5}, progress={}, status="done")
        s.add(job)
        s.commit()
        sid, jid = st.id, job.id
    await write_storyboard(cfg, brief(writer="openrouter/fake/frontier"), calls=Calls(db, sid, jid))
    with db.session() as s:
        runs = s.query(StepRun).filter_by(job_id=jid).all()
        tin, tout = sum(r.meta["tokens_in"] for r in runs), sum(r.meta["tokens_out"] for r in runs)
    measured = db.writer_tokens_per_minute()["openrouter/fake/frontier"]
    assert measured == {"in": round(tin / 0.5), "out": round(tout / 0.5), "jobs": 1}
    frontier = next(
        m for m in (await llm.catalog(cfg, db))["models"] if m["id"] == "openrouter/fake/frontier"
    )
    assert frontier["basis"] == "measured"
    per_minute = Decimal("0.000003") * measured["in"] + Decimal("0.000015") * measured["out"]
    assert frontier["usd_per_minute"] == to_usd(to_micros(per_minute))
