"""The R2 client: SigV4 pinned by AWS's published examples, and every call against the fake S3, which
checks signatures, payload hashes and expiry as R2 does."""

import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from lanternist import keys
from lanternist.providers import s3 as s3mod
from lanternist.providers.s3 import EMPTY, S3, UNSIGNED, S3Error, Signer, attachment

# AWS's worked examples (sig-v4-header-based-auth.html, sigv4-query-string-auth.html): their keys, their
# requests on 24 May 2013, and the signatures AWS computed.
AWS = Signer("AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", region="us-east-1")
AT = datetime(2013, 5, 24, tzinfo=UTC)
HOST = "examplebucket.s3.amazonaws.com"
DATED = {"host": HOST, "x-amz-content-sha256": EMPTY, "x-amz-date": "20130524T000000Z"}


def test_signing_matches_aws_examples():
    assert (
        AWS.signature("GET", "/test.txt", {}, DATED | {"range": "bytes=0-9"}, EMPTY, AT)
        == "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )
    body = "44ce7dd67c959e0d3524ffac1771dfbba87d2b6b4b4e99e42034a8b803f8b072"  # "Welcome to Amazon S3."
    put = {
        "date": "Fri, 24 May 2013 00:00:00 GMT",
        "host": HOST,
        "x-amz-content-sha256": body,
        "x-amz-date": "20130524T000000Z",
        "x-amz-storage-class": "REDUCED_REDUNDANCY",
    }
    assert (
        AWS.signature("PUT", "/test%24file.text", {}, put, body, AT)
        == "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd"
    )
    assert (
        AWS.signature("GET", "/", {"lifecycle": ""}, DATED, EMPTY, AT)
        == "fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543"
    )
    assert (
        AWS.signature("GET", "/", {"max-keys": "2", "prefix": "J"}, DATED, EMPTY, AT)
        == "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7"
    )


def test_presigning_matches_the_aws_example():
    query = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": "AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request",
        "X-Amz-Date": "20130524T000000Z",
        "X-Amz-Expires": "86400",
        "X-Amz-SignedHeaders": "host",
    }
    assert (
        AWS.signature("GET", "/test.txt", query, {"host": HOST}, UNSIGNED, AT)
        == "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
    )


def test_a_download_name_keeps_its_accents():
    assert attachment('La tortuga "que" temía.mp4') == (
        'attachment; filename="La tortuga _que_ tem_a.mp4"; '
        "filename*=UTF-8''La%20tortuga%20%22que%22%20tem%C3%ADa.mp4"
    )


@pytest.fixture
def s3(fake_cfg, fakes) -> S3:
    return S3(fake_cfg)


def _file(tmp_path, data: bytes, name: str = "f.bin"):
    path = tmp_path / name
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


async def test_put_get_head_delete(s3, fakes, tmp_path):
    src, sha = _file(tmp_path, b"a picture's bytes")
    key = "u/ann/derived/ab/ab12-thumb@1-w384.jpg"  # "@" is encoded in the path, and signed that way
    await s3.put(key, src, sha, "image/jpeg", "private, max-age=31536000, immutable")
    assert await s3.head(key) == len(b"a picture's bytes")
    assert fakes.s3.meta[f"{s3.bucket}/{key}"] == {
        "content-type": "image/jpeg",
        "cache-control": "private, max-age=31536000, immutable",
    }
    dest = tmp_path / "back" / "copy.jpg"
    assert await s3.get(key, dest) and dest.read_bytes() == b"a picture's bytes"
    assert await s3.read(key) == b"a picture's bytes"
    await s3.delete(key)
    assert await s3.head(key) is None
    assert await s3.read(key) is None
    assert not await s3.get(key, tmp_path / "gone.jpg") and not (tmp_path / "gone.jpg").exists()


async def test_a_body_that_isnt_its_hash_is_refused(s3, tmp_path):
    src, _ = _file(tmp_path, b"what was sent")
    with pytest.raises(S3Error) as e:
        await s3.put(
            "u/ann/assets/x.png", src, hashlib.sha256(b"something else").hexdigest(), "image/png", ""
        )
    assert e.value.status == 400 and e.value.type == "XAmzContentSHA256Mismatch"


async def test_a_wrong_secret_is_refused_and_not_retried(fake_cfg, fakes, monkeypatch, tmp_path):
    client = S3(fake_cfg)
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "not-the-one-the-bucket-knows")  # the fake now checks this one
    with pytest.raises(S3Error) as e:
        await client.head("u/ann/assets/x.png")
    assert e.value.status == 403 and e.value.type == "SignatureDoesNotMatch" and not e.value.retryable
    assert "R2_SECRET_ACCESS_KEY" in str(e.value)
    assert fakes.s3.requests == ["HEAD u/ann/assets/x.png"]


async def test_a_server_error_is_retried(s3, fakes, monkeypatch, tmp_path):
    monkeypatch.setattr(s3mod, "backoff", lambda *a, **k: 0)
    src, sha = _file(tmp_path, b"bytes")
    fakes.s3.fail = [503, 500]
    await s3.put("u/ann/assets/x.png", src, sha, "image/png", "")
    assert await s3.read("u/ann/assets/x.png") == b"bytes"
    assert fakes.s3.requests[:3] == ["PUT u/ann/assets/x.png"] * 3


async def test_listing_and_deleting_a_prefix_page_through_the_keys(s3, fakes, tmp_path):
    fakes.s3.page = 2  # R2 pages at 1,000; five keys over pages of two show the paging
    src, sha = _file(tmp_path, b"x")
    ann = [f"u/ann/assets/0{i}/0{i}.png" for i in range(5)]
    for key in [*ann, "u/bob/assets/00/00.png", "scratch/u/ann/aa/aa.mp4"]:
        await s3.put(key, src, sha, "image/png", "")
    assert await s3.keys("u/ann/") == ann
    assert await s3.delete_prefix("u/ann/") == 5
    assert await s3.keys("u/") == ["u/bob/assets/00/00.png"]
    assert await s3.keys("scratch/") == ["scratch/u/ann/aa/aa.mp4"]
    assert await s3.delete_prefix("u/ann/") == 0


async def test_a_presigned_url_serves_ranges_and_names_downloads(s3, fakes, tmp_path):
    src, sha = _file(tmp_path, b"0123456789")
    await s3.put("u/ann/assets/ff/ff.mp4", src, sha, "video/mp4", "private, max-age=31536000, immutable")
    at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    url = s3.presign("u/ann/assets/ff/ff.mp4", at, 7200, attachment("film.mp4"))
    assert url == s3.presign("u/ann/assets/ff/ff.mp4", at, 7200, attachment("film.mp4"))
    assert keys.platform_secret("r2", fake=True) not in url
    async with httpx.AsyncClient(transport=fakes.transport()) as browser:  # no key: only the URL
        r = await browser.get(url, headers={"range": "bytes=2-5"})
    assert r.status_code == 206 and r.content == b"2345"
    assert r.headers["content-range"] == "bytes 2-5/10"
    assert r.headers["content-disposition"] == "attachment; filename=\"film.mp4\"; filename*=UTF-8''film.mp4"
    assert r.headers["content-type"] == "video/mp4"


async def test_a_presigned_url_expires_and_cant_be_changed(s3, fakes, tmp_path):
    src, sha = _file(tmp_path, b"film")
    await s3.put("u/ann/assets/ff/ff.mp4", src, sha, "video/mp4", "")
    at = datetime.now(UTC) - timedelta(hours=2, seconds=1)
    async with httpx.AsyncClient(transport=fakes.transport()) as browser:
        expired = await browser.get(s3.presign("u/ann/assets/ff/ff.mp4", at, 7200))
        url = s3.presign("u/ann/assets/ff/ff.mp4", datetime.now(UTC), 7200)
        elsewhere = await browser.get(url.replace("u/ann/", "u/bob/"))
    assert expired.status_code == 403 and "expired" in expired.text
    assert elsewhere.status_code == 403 and "SignatureDoesNotMatch" in elsewhere.text


def test_no_keys_or_bucket_says_what_to_set(cfg, monkeypatch):
    with pytest.raises(S3Error, match=r"\[storage\] endpoint"):
        S3(cfg)
    monkeypatch.setattr(cfg.storage, "endpoint", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setattr(cfg.storage, "bucket", "lanternist-dev")
    with pytest.raises(S3Error, match="R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY"):
        S3(cfg)


def test_redact_hides_the_r2_secret(monkeypatch):
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "r2secretvalue0123456789abcdef")
    assert keys.redact("refused with r2secretvalue0123456789abcdef") == "refused with <r2 secret …cdef>"


async def test_a_download_is_retried_and_leaves_no_partial_file(s3, fakes, monkeypatch, tmp_path):
    monkeypatch.setattr(s3mod, "backoff", lambda *a, **k: 0)
    src, sha = _file(tmp_path, b"clip bytes")
    await s3.put("scratch/u/ann/cc/cc.mp4", src, sha, "video/mp4", "")
    fakes.s3.fail = [502]
    dest = tmp_path / "cache" / "cc.mp4"
    assert await s3.get("scratch/u/ann/cc/cc.mp4", dest) and dest.read_bytes() == b"clip bytes"
    fakes.s3.fail = [403]  # a "no" isn't retried, and nothing is left half written
    with pytest.raises(S3Error):
        await s3.get("scratch/u/ann/cc/cc.mp4", tmp_path / "cache" / "again.mp4")
    assert sorted(p.name for p in dest.parent.iterdir()) == ["cc.mp4"]


async def test_deleting_a_prefix_says_which_files_r2_kept(s3, fakes, tmp_path):
    src, sha = _file(tmp_path, b"x")
    for key in ("u/ann/assets/00/00.png", "u/ann/assets/01/01.png"):
        await s3.put(key, src, sha, "image/png", "")
    fakes.s3.undeletable = {"u/ann/assets/01/01.png"}  # R2 answers 200, with an <Error> for this one
    with pytest.raises(
        S3Error, match=r"kept 1 of the files under u/ann/ \(u/ann/assets/01/01.png: AccessDenied\)"
    ):
        await s3.delete_prefix("u/ann/")
    assert await s3.keys("u/ann/") == ["u/ann/assets/01/01.png"]


async def test_listing_a_bucket_that_isnt_there_says_so(s3, fakes):
    fakes.s3.fail = [404]
    with pytest.raises(S3Error, match="no bucket lanternist-fake"):
        await s3.keys("u/ann/")
