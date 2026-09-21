"""The fal and OpenRouter clients against the in-process fakes: no keys, no network."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest

from lanternist import registry
from lanternist.config import Paths, Settings
from lanternist.db import Database, StepRun, now
from lanternist.providers.fake import FakeWorld, sample
from lanternist.providers.fal import Fal, FalError, RunSpec
from lanternist.providers.openrouter import OpenRouter, OpenRouterError

KLING = "fal-ai/kling-video/v3/standard/image-to-video"


@pytest.fixture
def world() -> FakeWorld:
    return FakeWorld()


@pytest.fixture
def cfg(tmp_path) -> Settings:
    return Settings(paths=Paths(library=tmp_path / "lib"))


@pytest.fixture
def db(cfg) -> Database:
    d = Database(cfg.library / "lanternist.db")
    d.migrate()
    return d


@pytest.fixture
def fal(cfg, db, world) -> Fal:
    return Fal(cfg, db, key="test-key", transport_=world.transport())


def runs(db) -> list[StepRun]:
    with db.session() as s:
        return s.query(StepRun).order_by(StepRun.id).all()


def spec(**kw) -> RunSpec:
    return RunSpec(**{"stage": "motion", "model_id": "fal/kling-v3-standard", "step_key": "key1",
                      "unit": "output_second", "unit_price": Decimal("0.084")} | kw)


async def wait_for(cond, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError
        await asyncio.sleep(0.01)


# ------------------------------------------------------------------------------------ fal queue
async def test_a_request_is_logged_priced_and_downloaded(fal, db, world, tmp_path):
    seen = []
    res = await fal.run(KLING, {"prompt": "a cat", "start_image_url": "https://x/y.png", "duration": "5"},
                        spec(), on_status=lambda st, _: seen.append(st))
    assert {"IN_QUEUE", "IN_PROGRESS"} <= set(seen) and not res.resumed
    assert res.billable_units == 5.0 and res.cost_micros == 420_000
    [run] = runs(db)
    assert (run.status, run.provider, run.request_id, run.cost_source) == ("done", "fal", res.request_id, "computed")
    assert run.urls["cancel"].endswith("/cancel") and run.meta["billable_units_from"] == "result"
    assert run.meta["endpoint"] == KLING and run.finished_at and run.wall_seconds is not None
    sent = world.fal.requests[res.request_id]
    assert sent.endpoint == KLING and sent.arguments["duration"] == "5"
    dest = await fal.download(res.data["video"]["url"], tmp_path / "clip.mp4")
    assert dest.stat().st_size > 1000


async def test_billable_units_can_come_from_the_status_response(fal, db, world):
    world.fal.billable_units_on = "status"
    res = await fal.run(KLING, {"duration": "10"}, spec())
    assert res.billable_units == 10.0 and runs(db)[0].meta["billable_units_from"] == "status"
    world.fal.billable_units_on = "none"
    res = await fal.run(KLING, {"duration": "10"}, spec(step_key="key2"))
    assert res.cost_micros is None and runs(db)[1].cost_source == "none"


async def test_every_request_asks_fal_to_expire_its_media(cfg, db, world):
    captured = []

    async def handle(request):
        captured.append(request)
        return await world.handle(request)

    fal = Fal(cfg, db, key="test-key", transport_=httpx.MockTransport(handle))
    await fal.run(KLING, {"duration": "5"}, spec())
    submit = next(r for r in captured if r.method == "POST" and r.url.host == "queue.fal.run")
    assert json.loads(submit.headers["x-fal-object-lifecycle-preference"]) == {"expiration_duration_seconds": 86400}
    assert submit.headers["authorization"] == "Key test-key"


async def test_a_restart_resumes_instead_of_paying_again(fal, db, world):
    world.fal.polls_before_done = 10_000
    task = asyncio.create_task(fal.run(KLING, {"duration": "5"}, spec()))
    await wait_for(lambda: world.fal.submits)
    await wait_for(lambda: runs(db) and runs(db)[0].status == "running")
    task.cancel()   # a server shutdown: not the user's cancel
    with pytest.raises(asyncio.CancelledError):
        await task
    assert world.fal.cancels == [] and runs(db)[0].status == "running"

    world.fal.polls_before_done = 0
    res = await fal.run(KLING, {"duration": "5"}, spec())
    assert res.resumed and len(world.fal.submits) == 1 and res.request_id == world.fal.submits[0]
    assert [r.status for r in runs(db)] == ["done"]


async def test_a_request_too_old_to_resume_is_submitted_again(fal, db, world):
    world.fal.polls_before_done = 10_000
    task = asyncio.create_task(fal.run(KLING, {"duration": "5"}, spec()))
    await wait_for(lambda: runs(db))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    db.update_run(runs(db)[0].id, created_at=now() - timedelta(hours=2))
    world.fal.polls_before_done = 0
    res = await fal.run(KLING, {"duration": "5"}, spec())
    assert not res.resumed and len(world.fal.submits) == 2
    old, new = runs(db)
    assert old.status == "failed" and "expired" in old.error and new.status == "done"


async def test_the_users_cancel_cancels_at_fal(fal, db, world):
    world.fal.polls_before_done = 10_000
    task = asyncio.create_task(fal.run(KLING, {"duration": "5"}, spec(user_cancelled=lambda: True)))
    await wait_for(lambda: runs(db))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert world.fal.cancels == world.fal.submits and runs(db)[0].status == "cancelled"


async def test_bad_input_fails_with_the_field_named(fal, db, world):
    world.fal.fail_submit.append((422, {"detail": [{"loc": ["body", "duration"], "msg": "Input should be '5' or '10'",
                                                    "type": "literal_error"}]}))
    with pytest.raises(FalError, match=r"field duration") as e:
        await fal.run(KLING, {"duration": "7"}, spec())
    assert e.value.status == 422 and not e.value.retryable and runs(db) == []


async def test_rate_limits_and_server_errors_are_retried(fal, db, world, monkeypatch):
    monkeypatch.setattr("lanternist.providers.fal.backoff", lambda *a, **k: 0)
    world.fal.fail_submit += [(429, {"detail": "concurrent_requests_limit"}), (503, {"detail": "runner down"})]
    res = await fal.run(KLING, {"duration": "5"}, spec())
    assert runs(db)[0].status == "done" and res.request_id in world.fal.submits


async def test_a_refused_result_marks_the_run_failed(fal, db, world):
    world.fal.fail_result[KLING] = "The prompt was flagged"
    with pytest.raises(FalError, match="content_policy_violation"):
        await fal.run(KLING, {"duration": "5"}, spec())
    [run] = runs(db)
    assert run.status == "failed" and "flagged" in run.error


async def test_a_rejected_key(cfg, db, world):
    ok, detail = await Fal(cfg, db, key="bad", transport_=world.transport()).check()
    assert not ok and "rejected" in detail
    ok, _ = await Fal(cfg, db, key="good", transport_=world.transport()).check()
    assert ok


async def test_no_key_is_a_clear_error(cfg, db):
    with pytest.raises(FalError, match="no fal key"):
        Fal(cfg, db)


# ------------------------------------------------------------------------------------ files
async def test_uploads_are_reused(fal, world, tmp_path):
    f = tmp_path / "cast.png"
    f.write_bytes(b"\x89PNG fake")
    url = await fal.upload(f, asset="abc.png")
    assert await fal.upload(f, asset="abc.png") == url and len(world.fal.uploads) == 1
    assert world.fal.media[url][0] == b"\x89PNG fake"


async def test_upload_falls_back_when_the_cdn_refuses(fal, world, tmp_path, monkeypatch):
    monkeypatch.setattr("lanternist.providers.fal.backoff", lambda *a, **k: 0)
    f = tmp_path / "voice.wav"
    f.write_bytes(b"RIFF")
    orig = world.fal._upload
    world.fal._upload = lambda request: httpx.Response(500, json={"detail": "down"})
    url = await fal.upload(f, ttl_hours=1)
    assert url == "https://v3.fal.media/files/gcs/voice.wav"
    world.fal._upload = orig


# ------------------------------------------------------------------------------------ prices
async def test_price_sync_records_changes_only(cfg, db, fal, world):
    world.fal.deprecated.add("fal-ai/veo3.1/fast/image-to-video")
    world.fal.prices[KLING] = ("0.09", "seconds")
    lines = await registry.sync_prices(cfg, db, fal)
    by_model = {x["model"]: x for x in lines}
    assert by_model["fal/kling-v3-standard"]["changed"] and by_model["fal/kling-v3-standard"]["matches"]
    assert by_model["fal/veo-3.1-fast"]["status"] == "deprecated"
    assert "fal/flux-2-klein-9b#text_to_image" in by_model
    entries = registry.load(cfg.library, db)
    assert str(entries["fal/kling-v3-standard"].price.usd) == "0.09"
    assert entries["fal/veo-3.1-fast"].status == "deprecated"
    again = await registry.sync_prices(cfg, db, fal)
    assert not any(x["changed"] for x in again)


# ------------------------------------------------------------------------------------ OpenRouter
@pytest.fixture
def router(cfg, world) -> OpenRouter:
    return OpenRouter(cfg, key="sk-or-test", transport_=world.transport())


async def test_structured_chat_is_strict_and_reports_cost(router, world):
    schema = {"type": "object", "properties": {"title": {"type": "string"}, "n": {"type": "integer"}},
              "required": ["title", "n"], "additionalProperties": False}
    res = await router.chat("fake/frontier", [{"role": "user", "content": "hi"}], schema=schema, temperature=0.4,
                            reasoning={"effort": "none"})
    assert json.loads(res.text) == {"title": "text", "n": 1}
    assert res.cost_usd and res.cost_usd > 0 and res.provider == "FakeProvider"
    body = world.openrouter.chats[0]
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"data_collection": "deny", "require_parameters": True}
    assert body["reasoning"] == {"effort": "none"} and body["temperature"] == 0.4


async def test_plain_chat_doesnt_force_parameters(router, world):
    res = await router.chat("fake/cheap", [{"role": "user", "content": "write"}])
    assert res.text.startswith("TITLE:") and world.openrouter.chats[0]["provider"] == {"data_collection": "deny"}


async def test_out_of_credit_is_not_retried(router, world):
    world.openrouter.replies.append((402, {"error": {"code": 402, "message": "Insufficient credits",
                                                     "metadata": {"limit_source": "openrouter_credits"}}}))
    with pytest.raises(OpenRouterError, match="out of credit") as e:
        await router.chat("fake/frontier", [{"role": "user", "content": "x"}])
    assert not e.value.retryable and len(world.openrouter.chats) == 1


async def test_rate_limits_and_errors_after_200_are_retried(router, world, monkeypatch):
    monkeypatch.setattr("lanternist.providers.openrouter.backoff", lambda *a, **k: 0)
    world.openrouter.replies += [(429, {"error": {"code": 429, "message": "slow down"}}),
                                 (200, {"error": {"code": 502, "message": "provider hiccup"}}), "fine"]
    res = await router.chat("fake/frontier", [{"role": "user", "content": "x"}])
    assert res.text == "fine" and len(world.openrouter.chats) == 3


async def test_moderation_is_reported_with_reasons(router, world):
    world.openrouter.replies.append((403, {"error": {"code": 403, "message": "flagged",
                                                     "metadata": {"reasons": ["violence"]}}}))
    with pytest.raises(OpenRouterError, match="reasons: violence"):
        await router.chat("fake/frontier", [{"role": "user", "content": "x"}])


async def test_an_empty_answer_out_of_tokens_is_an_error(router, world):
    world.openrouter.replies.append((200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                                           "usage": {"completion_tokens_details": {"reasoning_tokens": 4000}}}))
    with pytest.raises(OpenRouterError, match="4000 tokens"):
        await router.chat("fake/frontier", [{"role": "user", "content": "x"}])


async def test_key_usage_and_the_model_list(cfg, router, world):
    ok, detail, info = await router.check()
    assert ok and "$1.25 of a $10.00 limit" in detail and info["limit_remaining"] == 8.75
    ok, detail, _ = await OpenRouter(cfg, key="bad", transport_=world.transport()).check()
    assert not ok and "rejected the key" in detail
    models = await router.models(refresh=True)
    assert [m["id"] for m in models] == ["fake/frontier", "fake/cheap"]
    world.openrouter.models.pop()
    assert len(await router.models()) == 2          # cached for a day
    assert len(await router.models(refresh=True)) == 1


async def test_no_openrouter_key(cfg, world):
    with pytest.raises(OpenRouterError, match="no OpenRouter key"):
        await OpenRouter(cfg, transport_=world.transport()).chat("x", [])


def test_sample_fits_the_schema():
    s = {"type": "object", "properties": {"a": {"type": "array", "items": {"enum": ["x", "y"]}, "minItems": 2},
                                          "b": {"type": ["number", "null"]}, "c": {"type": "boolean"}}}
    assert sample(s) == {"a": ["x", "x"], "b": 1.0, "c": False}
