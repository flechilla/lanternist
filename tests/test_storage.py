"""The hosted edition's files on R2 (the fake S3 in fake mode) and its step cache in the database: a
film stored whole, served from presigned URLs, never another's, and deleted with its account
(plans/STORAGE_PLAN.md)."""

import asyncio
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit

from sqlalchemy import select, update
from test_accounts import BOB
from test_api import storyboard
from test_editions import PRESET

from lanternist import providers, store
from lanternist.config import Paths, Settings, Storage
from lanternist.db import Step, now
from lanternist.providers.s3 import S3, attachment


def _render(c, wait) -> tuple[str, str, dict]:
    """Ann's user id, a story of hers, and its render job."""
    ann = c.get("/api/me").json()["id"]
    sid = c.post("/api/stories", json={"storyboard": storyboard(voice=PRESET)}).json()["story"]["id"]
    return ann, sid, wait(c.post(f"/api/stories/{sid}/render").json()["id"])


def _object(url: str) -> str:
    """The object a presigned URL leads to."""
    return unquote(urlsplit(url).path)


def _steps(db, owner: str) -> list[Step]:
    with db.session() as s:
        return list(s.scalars(select(Step).where(Step.owner_id == owner)))


def test_a_hosted_film_keeps_every_file_on_the_bucket(hosted_client, wait):
    c = hosted_client
    db, cfg = c.app.state.db, c.app.state.cfg
    ann, sid, job = _render(c, wait)
    fakes, bucket = providers.fake_world(), S3(cfg).bucket

    on_r2 = set(fakes.s3.keys(bucket))
    assert all(k.startswith((f"u/{ann}/", f"scratch/u/{ann}/")) for k in on_r2)
    steps = _steps(db, ann)
    for step in steps:
        for asset in step.record["assets"].values():
            where = store.scratch_key(ann, asset) if step.expires_at else store.asset_key(ann, asset)
            assert where in on_r2, (where, step.record)
            if asset.endswith(".png"):  # made as the picture was stored, for the pages
                assert store.derived_key(ann, asset, "thumb@1-w384.jpg") in on_r2
    assert any(step.expires_at for step in steps)  # ffmpeg's scene clips, under scratch/
    for part in ("film", "srt", "vtt", "poster"):
        assert store.asset_key(ann, job["result"][part]) in on_r2

    # With the disk cache gone, the database's records and R2's files are the cache: nothing is made
    # again, nor paid for.
    shutil.rmtree(cfg.library_for(ann))
    submits, sent = len(fakes.fal.submits), len(fakes.s3.requests)
    again = wait(c.post(f"/api/stories/{sid}/render").json()["id"])
    assert again["result"]["film"] == job["result"]["film"]
    assert len(fakes.fal.submits) == submits
    assert not [r for r in fakes.s3.requests[sent:] if r.startswith("PUT")]

    # An edit makes its own scene again and reads the rest back from R2: pictures from assets/, clips
    # from scratch/.
    story = c.get(f"/api/stories/{sid}").json()
    sb = story["storyboard"]
    sb["scenes"][0]["narration"][0]["text"] = "Scene 1 now says something else entirely."
    c.put(f"/api/stories/{sid}", json={"storyboard": sb, "base_version": story["version"]})
    sent = len(fakes.s3.requests)
    edited = wait(c.post(f"/api/stories/{sid}/render").json()["id"])
    fetched = [r for r in fakes.s3.requests[sent:] if r.startswith("GET ")]
    assert any(r.startswith(f"GET scratch/u/{ann}/") for r in fetched)
    assert store.asset_key(ann, edited["result"]["film"]) in fakes.s3.keys(bucket)


def test_films_play_from_presigned_urls(hosted_client, wait):
    c = hosted_client
    ann, sid, job = _render(c, wait)
    film, vtt = job["result"]["film"], job["result"]["vtt"]

    r = c.get(f"/api/assets/{film}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["cache-control"].startswith("private, max-age=")
    assert f"/api/fake/s3/lanternist-fake/u/{ann}/assets/" in r.headers["location"]
    assert "X-Amz-Expires=7200" in r.headers["location"]
    played = c.get(r.headers["location"], headers={"Range": "bytes=0-99"})
    assert played.status_code == 206 and len(played.content) == 100
    assert played.headers["content-type"] == "video/mp4" and "private" in played.headers["cache-control"]

    saved = c.get(f"/api/assets/{film}", params={"download": "La tortuga que temía al mar-v1.mp4"})
    assert saved.headers["content-disposition"] == attachment("La tortuga que temía al mar-v1.mp4")

    # A <track> loads from our own origin, so subtitles come through the API.
    track = c.get(f"/api/assets/{vtt}", follow_redirects=False)
    assert track.status_code == 200 and track.headers["content-type"].startswith("text/vtt")
    assert track.text.startswith("WEBVTT")

    picture = c.get(f"/api/stories/{sid}").json()["board"]["scenes"][0]["keyframe"]
    small = c.get(f"/api/assets/{picture}?w=300", follow_redirects=False)
    assert _object(small.headers["location"]).endswith("-thumb@1-w384.jpg")
    assert c.get(small.headers["location"]).headers["content-type"] == "image/jpeg"

    assert c.get(f"/api/assets/{film}", headers=BOB, follow_redirects=False).status_code == 404


def test_an_address_stays_the_same_for_the_hour(hosted_client, wait, monkeypatch):
    c = hosted_client
    _, _, job = _render(c, wait)
    at: list[datetime] = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at[-1].astimezone(tz)

    monkeypatch.setattr(store, "datetime", Clock)

    def asked(hour: int, minute: int) -> tuple[str, str]:
        at.append(datetime(2026, 9, 26, hour, minute, tzinfo=UTC))
        r = c.get(f"/api/assets/{job['result']['film']}", follow_redirects=False)
        return r.headers["location"], r.headers["cache-control"]

    first, kept = asked(10, 5)
    assert "X-Amz-Date=20260926T100000Z" in first and kept == "private, max-age=3300"
    assert asked(10, 55)[0] == first  # the browser's cache still has it
    assert asked(11, 5)[0] != first


def test_the_hosted_api_serves_a_thumbnail_without_ffmpeg(hosted_client, wait, monkeypatch):
    c = hosted_client
    ann = c.get("/api/me").json()["id"]
    sid = c.post("/api/stories", json={"storyboard": storyboard(voice=PRESET)}).json()["story"]["id"]
    wait(c.post(f"/api/stories/{sid}/board").json()["id"])
    fakes, bucket = providers.fake_world(), S3(c.app.state.cfg).bucket
    picture = c.get(f"/api/stories/{sid}").json()["board"]["scenes"][0]["keyframe"]
    monkeypatch.setenv("PATH", "")  # no ffmpeg: the job made the thumbnails, the API only points at them
    r = c.get(f"/api/assets/{picture}?w=768", follow_redirects=False)
    assert r.status_code == 302 and _object(r.headers["location"]).endswith("-thumb@1-w768.jpg")
    # A picture drawn before thumbnails were made with it: the picture itself.
    for width in (384, 768):
        fakes.s3.file(bucket, store.derived_key(ann, picture, f"thumb@1-w{width}.jpg")).unlink()
    r = c.get(f"/api/assets/{picture}?w=768", follow_redirects=False)
    assert _object(r.headers["location"]).endswith(picture)
    assert c.get(f"/api/assets/{picture}.txt?w=10").status_code == 400


def test_expired_scratch_clips_are_encoded_again_for_nothing(hosted_client, wait):
    c = hosted_client
    db, cfg = c.app.state.db, c.app.state.cfg
    ann, sid, _ = _render(c, wait)
    fakes, bucket = providers.fake_world(), S3(cfg).bucket
    # A week on: the bucket's rule has deleted scratch/, and the clips' records expired a day earlier.
    for key in fakes.s3.keys(bucket, "scratch/"):
        fakes.s3.file(bucket, key).unlink()
    with db.session() as s:
        s.execute(
            update(Step).where(Step.expires_at.is_not(None)).values(expires_at=now() - timedelta(seconds=1))
        )
        s.commit()
    shutil.rmtree(cfg.library_for(ann))
    submits, sent = len(fakes.fal.submits), len(fakes.s3.requests)
    wait(c.post(f"/api/stories/{sid}/render").json()["id"])
    assert len(fakes.fal.submits) == submits  # nothing paid for again
    assert [r for r in fakes.s3.requests[sent:] if r.startswith(f"PUT scratch/u/{ann}/")]


def test_forgetting_an_account_deletes_its_files_records_and_cache_and_no_one_elses(hosted_client, wait):
    c = hosted_client
    db, cfg = c.app.state.db, c.app.state.cfg
    ann, _, _ = _render(c, wait)
    fakes, bucket = providers.fake_world(), S3(cfg).bucket
    bob = c.get("/api/me", headers=BOB).json()["id"]
    theirs = c.post("/api/stories", json={"storyboard": storyboard(voice=PRESET)}, headers=BOB).json()[
        "story"
    ]
    wait(c.post(f"/api/stories/{theirs['id']}/board", headers=BOB).json()["id"], headers=BOB)
    bobs = fakes.s3.keys(bucket, f"u/{bob}/")
    keys = [step.key for step in _steps(db, ann)]
    assert bobs and keys

    asyncio.run(store.forget(cfg, db, ann))
    assert fakes.s3.keys(bucket, f"u/{ann}/") == fakes.s3.keys(bucket, f"scratch/u/{ann}/") == []
    assert db.get_steps(ann, keys) == {} and not cfg.library_for(ann).exists()
    assert fakes.s3.keys(bucket, f"u/{bob}/") == bobs and _steps(db, bob)
    asyncio.run(store.forget(cfg, db, ann))  # again: nothing left, and no error


def test_trim_keeps_the_cache_under_its_size_and_spares_what_was_just_used(tmp_path):
    cfg = Settings(paths=Paths(library=tmp_path / "lib"), storage=Storage(cache_gb=1000 / 1e9))  # 1,000 bytes
    long_ago = time.time() - 3 * 3600
    files = []
    for n in range(5):
        f = cfg.library / "u" / "ann" / "assets" / "ab" / f"{n}.png"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 300)
        files.append(f)
    for n, f in enumerate(files[:4]):
        os.utime(f, (long_ago + n, long_ago + n))  # 0 was used longest ago; 4 just now
    (cfg.library / "u" / "ann" / "tmp").mkdir()
    (cfg.library / "u" / "ann" / "tmp" / "work.mp4").write_bytes(
        b"x" * 5000
    )  # a running job's: not the cache's

    assert store.trim(cfg) == 900  # 1,500 bytes, down to 80% of 1,000: the three used longest ago
    assert [f.exists() for f in files] == [False, False, False, True, True]
    assert store.trim(cfg) == 0  # under its size now

    for f in files[3:]:
        os.utime(f)  # both used just now
    (cfg.library / "u" / "bob" / "assets").mkdir(parents=True)
    (cfg.library / "u" / "bob" / "assets" / "big.mp4").write_bytes(b"x" * 1000)
    assert store.trim(cfg) == 0  # over its size, but everything in it may still be read


def test_opening_a_story_looks_up_its_steps_in_as_many_queries_for_12_scenes_as_for_3(
    hosted_client, wait, statements
):
    c = hosted_client
    lookups = []
    for n in (3, 12):
        sid = c.post("/api/stories", json={"storyboard": storyboard(n, voice=PRESET)}).json()["story"]["id"]
        wait(c.post(f"/api/stories/{sid}/board").json()["id"])
        with statements(c.app.state.db) as sent:
            assert c.get(f"/api/stories/{sid}").json()["board"]["scenes"][-1]["keyframe"]
            c.get(f"/api/stories/{sid}/estimate", params={"kind": "render"})
        lookups.append(len([q for q in sent if "FROM steps" in q]))
    assert lookups[0] == lookups[1] < 20
