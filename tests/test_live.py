"""Live checks against the real OpenRouter and fal APIs: `uv run pytest -m live -s`.

They need your keys (`lanternist keys set openrouter|fal`) and spend about a cent: one short
structured chat on the cheapest model, and one small klein picture. What they print settles the
details the docs left open: fal's unit names, which response carries the billable units, and
whether OpenRouter accepts `data_collection`.
"""

import os
from decimal import Decimal

import pytest

from lanternist import keys, registry
from lanternist.config import Paths, Settings
from lanternist.db import Database
from lanternist.providers.fal import Fal, RunSpec
from lanternist.providers.openrouter import OpenRouter

pytestmark = pytest.mark.live


def need(provider: str) -> None:
    if not keys.get_key(provider).value:
        pytest.skip(f"no {provider} key: run `lanternist keys set {provider}`")


@pytest.fixture
def cfg(tmp_path) -> Settings:
    return Settings(paths=Paths(library=tmp_path / "lib"))


@pytest.fixture
def db(cfg) -> Database:
    d = Database(cfg.library / "lanternist.db")
    d.migrate()
    return d


async def test_openrouter_key_models_and_a_strict_chat(cfg):
    need("openrouter")
    router = OpenRouter(cfg)
    ok, detail, _ = await router.check()
    print("\nOpenRouter key:", detail)
    assert ok
    models = await router.models(refresh=True)
    paid = [m for m in models if not m["id"].endswith(":free")]
    cheapest = min(paid, key=lambda m: float(m["pricing"]["prompt"]) + float(m["pricing"]["completion"]))
    print(f"{len(models)} models with structured output; cheapest: {cheapest['id']}")
    schema = {"type": "object", "properties": {"colour": {"type": "string"}}, "required": ["colour"],
              "additionalProperties": False}
    res = await router.chat(cheapest["id"], [{"role": "user", "content": "Name one colour. Answer in JSON."}],
                            schema=schema, max_tokens=200)
    print(f"answer {res.text!r} from {res.provider}; cost ${res.cost_usd}; data_collection=deny accepted")
    assert '"colour"' in res.text and res.cost_usd is not None


async def test_fal_prices_units_and_catalog(cfg, db):
    need("fal")
    lines = await registry.sync_prices(cfg, db)
    print()
    for x in lines:
        flag = f"  <- {x['drift']}" if x["drift"] else ""
        print(f"{x['model']:<40} {x['price']} per {x['api_unit']!r} [{x['status']}]{flag}")
    assert all(x["price"] is not None for x in lines)


async def test_fal_small_picture_upload_and_billing(cfg, db, tmp_path):
    need("fal")
    fal = Fal(cfg, db)
    entry = registry.get("fal/flux-2-klein-9b")
    res = await fal.run(entry.endpoint_for("text_to_image"),
                        {"prompt": "a small grey cat on a lighthouse railing, watercolour",
                         "image_size": {"width": 512, "height": 288}, "num_inference_steps": 4, "seed": 7},
                        RunSpec(stage="keyframes", model_id=entry.id, step_key="live-test", unit="megapixel",
                                unit_price=entry.price.tiers["text_to_image"]), ttl_hours=1)
    run = db.get_run(res.run_id)
    print(f"\nresult keys {sorted(res.data)}; billable units {res.billable_units} "
          f"(from {run.meta.get('billable_units_from')}); cost ${Decimal(res.cost_micros or 0) / 1_000_000}")
    image = await fal.download(res.data["images"][0]["url"], tmp_path / "cat.png")
    assert image.stat().st_size > 1000
    url = await fal.upload(image, asset="live-test.png", ttl_hours=1)
    print("uploaded to", url.split("/")[2])
    assert url.startswith("https://")


@pytest.mark.skipif(os.environ.get("LANTERNIST_LIVE_VIDEO") != "1",
                    reason="spends about $0.13: set LANTERNIST_LIVE_VIDEO=1")
async def test_fal_video_billing_units(cfg, db, tmp_path):
    """How fal bills an option that lowers the price: fewer billable units at the base price, or not.

    Wan 2.6 flash lists $0.05/s at 720p with audio, half that without. A 5 s silent clip should cost
    $0.125: 2.5 billable units at the $0.05 base price if options scale the units."""
    need("fal")
    fal = Fal(cfg, db)
    await registry.sync_prices(cfg, db, fal)
    entry = registry.get("fal/wan-2.6-flash", db=db)
    base = entry.billing[""]
    image = tmp_path / "frame.png"
    from lanternist.engines import fake

    await fake.image({"id": "f", "seed": 3, "width": 1280, "height": 720, "out": str(image)})
    url = await fal.upload(image, asset="live-frame.png", ttl_hours=1)
    res = await fal.run(entry.endpoint, {"prompt": "slow drift over a calm sea at dusk", "image_url": url,
                                         "duration": "5", **entry.defaults},
                        RunSpec(stage="motion", model_id=entry.id, step_key="live-video", unit=base.unit,
                                unit_price=base.unit_price), ttl_hours=1)
    cost = Decimal(res.cost_micros or 0) / 1_000_000
    print(f"\nWan 5 s, 720p, audio off: {res.billable_units} billable {base.unit} at ${base.unit_price} "
          f"= ${cost} (list price says $0.125)")
    video = await fal.download(res.data["video"]["url"], tmp_path / "wan.mp4")
    assert video.stat().st_size > 10_000 and res.billable_units is not None
