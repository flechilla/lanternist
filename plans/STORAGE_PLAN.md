# Lanternist: storage on R2

> **Status, 26 Sep 2026: done, merged as #34 (`feat/storage`), in one pull request, and checked against R2 (`lanternist-dev`). The questions in §4 are answered.** This is Phase C of `HOSTED_PLAN.md` (issue #16). Its one blocker, Phase B (#15), is on `main` as #33. Migration 0005 is this phase's (HOSTED_PLAN §1.15); Phases D and E take 0006 and later. The sketch is at https://claude.ai/artifact/YK2AkQiXCA3jAqMdVb38zu.
>
> **Measured before writing:**
> - **What a story weighs.** The lab library (`~/Lanternist-lab`, 20 films made on 22 Sep) holds 8.8 GB of assets. ffmpeg's scene clips are 4.49 GB of it (51%), the films 1.97 GB (22%), paid video from fal 1.55 GB (18%), pictures 0.70 GB (8%) and narration 0.05 GB. So about half of what a story weighs costs nothing to make again.
> - **The step cache is small.** 1,062 step records: 155 bytes at the median, 2.2 KB at most, 384 KB in all. A Postgres table holds them easily.
> - **Thumbnails** are about 29 KB at 384 px and 92 KB at 768 px (medians of the lab's `derived/`).
> - **A 38-scene film in fake mode** (12 video scenes) stores 130 files and writes 128 step records. Opening its Board looks up 90 step records, one per item, in 90 separate reads. Rendering it again with everything cached looks up 129 and stores nothing.
> - **botocore** 1.43.103 is a 20 MB wheel of 2,013 files and pulls in jmespath, python-dateutil and urllib3. Its signer takes the time from `get_current_datetime()` inside `add_auth`, with no way to pass one. An hour-stable URL (§1.5) needs a fixed time, so we'd have had to override that method or patch the function. We sign ourselves instead (§4, question 2).

**Goal:** in the hosted edition, every picture, clip, film and recording lives in R2 under its owner's prefix, and the step cache lives in Postgres. The pipeline stores and reads files through one `Store` interface and doesn't know where they live. The browser gets files straight from R2 through presigned URLs, and the API never touches a file's bytes, except for subtitles. The local edition keeps its folder, exactly as it is.

Definition of done (issue #16's exit):

1. **A full film in fake hosted mode** puts every file on the fake S3: every asset named in a `steps` row or a job's result is there, under the owner's prefix. With the disk cache wiped, the same film renders again from the cache and pays for nothing.
2. **The Board, the reel and the film play from presigned URLs.** `/api/assets/…` answers 302. The URL stays the same for the whole hour, serves ranges, and names downloads.
3. **User B never gets user A's cached step for free.** B's board submits to fal again, and `get_step` never returns A's row to B.
4. **One live R2 round trip** (`pytest -m live`, with your permission): put, head, a ranged GET through a URL signed at the top of the hour, a download name, list, and deleting a prefix.
5. **The local edition works as before.** No step key changes, the golden-key tests hold, and a copy of `~/Lanternist` opens after migration 0005 with its JSON step records where they were.

---

## 0. Where we are

- **One kind of store.** `Store(root)` in `store.py` is a folder: `assets/ab/<sha>.<ext>`, `steps/ab/<key>.json`, `derived/…` and `tmp/`. Phase B gave each owner a folder of their own: `cfg.library_for(owner)` is the library itself locally, and `lib/u/<id>` or `lib/shared` in hosted.
- **Everything is synchronous and local.** Engines read inputs with `ctx.store.path(asset)` (12 places) and hand outputs to `on_item`, a plain callback that stores them at once (10 places). `get_step` checks that every file a record names still exists: a missing file makes it a miss.
- **Three places build a store** besides the pipeline: `Pipeline.find` (the asset route), and the voice catalogue and sample routes in `api/app.py`, with `Store(eff.library_for(None))`.
- **`/api/assets/{asset}`** answers with the file. `Cache-Control` is `private` in hosted and `public` locally. `?w=` makes a thumbnail on first request, with ffmpeg, in the API process.
- **Jobs run in the API process.** The runner lives inside `lanternist serve` until Phase D brings `lanternist worker`.
- **Deleting a story** already deletes its versions and jobs (`ON DELETE CASCADE`), and keeps what it cost (`test_deleting_a_story_keeps_what_it_cost`). Its files and cache records stay, since other stories of the same user may share them.
- **Deleting an account** in WorkOS sets `deleted_at` and ends the sessions. Deleting stories and files is Phase I's (ACCOUNTS_PLAN §1.4).

## 1. Design

### 1.1 The layout on R2

One bucket per environment (question 1): `lanternist-dev` now, and staging and production in Phase G. Keys mirror `library_for`:

```
u/<user>/assets/ab/<sha>.<ext>          pictures, narration, paid video, films, subtitles, verdicts
u/<user>/derived/ab/<sha>-thumb@1-w384.jpg   thumbnails, made where the job runs (§1.6)
scratch/u/<user>/ab/<sha>.mp4           ffmpeg's scene clips: a lifecycle rule deletes them after 7 days
shared/assets/…  shared/derived/…       what belongs to no one: voice samples
```

- **Scratch goes at the top, not under the user.** An R2 lifecycle rule matches a key prefix, with no wildcards, so `u/*/scratch/` can't be written. One rule on `scratch/` covers everyone. HOSTED_PLAN §1.6 put scratch under the user's prefix; this is the one change to its layout.
- **An account is two prefixes:** `u/<user>/` and `scratch/u/<user>/`.
- **Objects carry their type and cache rule.** Each PUT sends `Content-Type` and `Cache-Control: private, max-age=31536000, immutable`. An asset never changes under its name, and a thumbnail's name carries `THUMBNAIL`'s version.
- **The bucket's rules:** `scratch-7-days` deletes `scratch/` after 7 days. R2's own default rule, which aborts unfinished multipart uploads after 7 days, stays: we never start one. No CORS rule, and no public access (§1.5 says why).

### 1.2 The `Store` interface

Two backends behind the same methods. The folder is today's `Store`. `R2Store` extends it: the folder is its disk cache, R2 holds the files, and Postgres holds the step records.

| Method | The folder (local) | `R2Store` (hosted) |
|---|---|---|
| `await put(src, move, scratch=False) -> asset` | moves the file in, as today | the same, then uploads it; returns once R2 has it |
| `await file(asset) -> Path` | where it is | the cached copy, or downloads it first (it looks in `assets/`, then `scratch/`) |
| `path(asset) -> Path` | where it is (the CLI and the local film copy) | where the cached copy would be |
| `get_step(key)`, `get_steps(keys)` | JSON files; a record whose file is gone is a miss, as today | one query on `steps`; a scratch record past its `expires_at` is a miss |
| `put_step(key, record, scratch=False)` | a JSON file | a `steps` row; scratch rows expire after 6 days, a day before their files |
| `tmp()` | `tmp/` | `tmp/` in the cache |
| `asset_key`, `presigned` (functions, for the API) | — | where an asset is on R2, and a presigned GET for it (§1.5) |

- **`store.of(cfg, db, owner)`** is the one place that picks the backend: the folder locally, and `R2Store` in hosted, with the owner's prefix, or `shared` for owner None. `Pipeline`, the asset route and the voice routes call it in place of `Store(cfg.library_for(…))`.
- **Reading and storing files becomes async.** `path()` in an engine becomes `await ctx.store.file(asset)`. `on_item` becomes `await on_item(out)`, and returns once the output is stored: uploaded, recorded, and any thumbnails made. Upload and download are network calls, and in Phase C jobs share the event loop with every API request and progress stream. The change is mechanical, at about 20 call sites, and goes in a commit of its own, with no change in behaviour.
- **An output is stored before anyone hears of it.** `_stage` uploads the file, then writes its record, then sends the item's `done` event. A step record therefore always means its files are on R2. The browser, told that a picture is done, finds it.
- **A record is trusted without a HEAD.** Files under `u/` go only when the account goes, and its rows go with them. Scratch clips expire, and their rows expire a day earlier. So `get_step` needs no network call, and a cached re-render of a 38-scene film costs 129 row reads and nothing else.
- **Lookups are batched.** `get_steps(keys)` reads many records in one query. `Pipeline.cached_many(items)` uses it, and `peek` and `_stage`'s cache pass go through it: a Board view costs about 6 queries (narration, cast sheet, portraits, pictures, motion), not 90. The database rule asks this of any page that lists rows.
- **A cancel doesn't lose a paid output.** Everything after fal bills (fetching the result, storing it, recording it) runs to its end however often the job is cancelled meanwhile (`engines.base.whole`), in the engines' own sub-steps (a video's shots, narration chunks, a cloned voice) as in `_stage`. A stopping server gives its jobs up to 30 s (`jobs.STOP_GRACE`) to finish that. Only a process killed outright can lose the item in flight, which the next run pays for again.

### 1.3 The step cache in Postgres (migration 0005, `steps`)

| Table | Change |
|---|---|
| `steps` | **new**: `owner_id` (→ `users`, `CASCADE`, `fk_steps_owner_id`), `key` (64), `record` (JSON), `created_at`, `expires_at` (nullable: scratch). Primary key `pk_steps` (`owner_id`, `key`) |
| `users` | one new row, `shared`, like `local`: it owns the records of what everyone shares, the voice samples. No one can sign in as it. |

- **Queries** (`/add-query`), each taking the owner first (invariant 10): `get_steps(owner, keys) -> dict[str, dict]`, `put_step(owner, key, record, expires_at)` and `forget_steps(owner)`. `put_step` inserts, and on a duplicate key (two workers making the same step in Phase D) updates the row. The unique key settles the race, as the database rule asks.
- **Expired rows stay** until the same step is made again and overwrites them. There are about 38 of them per film, a few KB, so no sweep is needed.
- **A local library gets the table empty.** Its step records stay JSON files in `steps/`, and nothing moves (`test_migration_on_a_copy_of_the_real_library`).
- **The downgrade** drops `steps` and the `shared` row.
- `HOSTED_PLAN §1.14` gains `expires_at` and the `shared` row.

### 1.4 The S3 client (`providers/s3.py`)

- **httpx, through `providers.transport(cfg)`,** like fal, OpenRouter and WorkOS. So fake mode serves a fake S3 with every line of the real client (invariant 8). No SDK.
- **Calls:** `put(key, path, sha256, type)`, `get(key, dest)` (streamed to a file), `head(key) -> int | None`, `delete(key)`, `list(prefix)` (ListObjectsV2, following `continuation-token`), `delete_prefix(prefix)` (DeleteObjects in batches of 1,000), and `presign(key, at, seconds, download)`.
- **Signing** is AWS Signature Version 4, region `auto`, service `s3`: headers for our own calls, the query string for presigned GETs. It's our own, about 50 lines of `hmac`, `hashlib` and `urllib.parse`, with no new dependency (question 2). It's tested against AWS's published SigV4 examples, whose signatures are fixed strings, and against R2 in the live test.
- **Integrity for free.** A PUT's `x-amz-content-sha256` is the file's SHA-256, which the store has already computed for the asset's name. R2 checks the body against it: the live test's wrong hash got `400 XAmzContentSHA256Mismatch`.
- **One PUT per file.** R2 takes up to 5 GB in a single PUT; a 4-minute film is 350–400 MB. The body streams from the file.
- **Errors:** `S3Error(ProviderError)`, with a sentence: "R2 refused the upload of u/…/film.mp4: check R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY". 429, 5xx and transport errors are retried with `providers.backoff()`. A 403 or 404 isn't.
- **Keys.** `keys.PLATFORM` gains `r2_key_id: R2_ACCESS_KEY_ID` and `r2: R2_SECRET_ACCESS_KEY`: from the environment only, and scrubbed by `redact()` (invariant 4). The access key id isn't a secret: S3's design puts it in every presigned URL, in `X-Amz-Credential`.
- **Config.** `[storage] endpoint` (`https://<account id>.r2.cloudflarestorage.com`), `bucket`, `cache_gb` (question 3) and `downloads` (files a stage fetches at once, 8), documented in `lanternist.example.toml`. Hosted refuses to start without the endpoint, the bucket or the keys, and says which to set. Fake mode fills them in.

### 1.5 Serving files

`/api/assets/{asset}` in hosted:

1. The asset must be the user's own (`u/<me>/assets/…`) or shared (`shared/assets/…`), found with a HEAD, own first. Otherwise 404, the same as for one that doesn't exist. The browser keeps the 302 until the hour ends (4 below), so a Board costs one HEAD per picture on its first view in an hour, and none after.
2. `?w=` answers with the thumbnail the job made (§1.6), or with the picture itself when there's none. The API never runs ffmpeg in hosted.
3. **A `.vtt` is answered by the API itself,** a few KB read from R2. A `<track>` loaded from another origin needs the `<video>` to fetch in CORS mode and the bucket to allow our origin. Relaying the one small file keeps the bucket without a CORS rule and the web app unchanged.
4. **Everything else is a 302 to a presigned GET** on R2's S3 endpoint. Presigned URLs don't work on custom domains, support ranges (films seek), and cost no egress.
   - **Signed at the top of the hour and valid for 2 hours.** Every request in the same hour gets the same URL, so the browser's cache keeps working, and each URL has at least an hour left when it's handed out. A film paused for longer than that reloads through the API.
   - **The 302 itself** is cacheable until the end of the hour (`private`), so a page reloaded within the hour doesn't ask again.
   - **A download** (`?download=name`) adds `response-content-disposition: attachment` with the name, UTF-8 included, as the query string's part of the signature. R2 honours it: the live test's `Película ñ-v3.mp4` came back as `filename*=UTF-8''Pel%C3%ADcula%20%C3%B1-v3.mp4`.
5. **The local edition** answers with the file, as today.

The browser follows the redirect with the fragment it asked for (`#t=2` on the reel's `<video>`), as the fetch standard says.

**Fake mode runs in a browser too.** The fake S3's endpoint is `<hosted url>/api/fake/s3`, a route registered only in fake mode, like `/api/auth/fake`. It hands the request to the same fake behind `providers.transport()`. The fake checks every signature and expiry, so a presigned URL that's wrong fails in fake mode as it would on R2. The tests follow the 302 through it.

### 1.6 Thumbnails and where the disk cache lives

- **Thumbnails are made as each picture is stored,** both widths (384 and 768), in `_stage`, before the item's `done` event. That's about 0.1 s of ffmpeg per picture, while fal draws the next. They're uploaded to `derived/` in hosted. Locally they're made the same way, and the route still makes one on demand for pictures drawn before this change.
- **Where jobs run, now and after Phase D:**

  | | Phase C (now) | After Phase D |
  |---|---|---|
  | Jobs | the runner inside `lanternist serve` | `lanternist worker` processes |
  | The disk cache | `<library>/u/<id>/…` on the server running `serve` | the same layout on each worker's volume |
  | Thumbnails | made by the job, in `serve` | made by the job, in the worker |
  | The API | HEADs, presigns, relays `.vtt` | the same, with no cache at all |

  Nothing moves in Phase D: the cache belongs to the store, and the store goes wherever the job runs.
- **The cache is bounded** at 20 GB (`[storage] cache_gb`, question 3). After each job, `store.trim(cfg)` deletes the least recently used files until the cache is under 80% of its size. A cache hit touches the file. Files used in the last hour are skipped, so a running job keeps its inputs. A file ffmpeg has open survives being unlinked on Linux anyway.

### 1.7 ffmpeg's intermediates

- **The clips stage stores with `scratch=True`:** its files go under `scratch/`, and their rows expire after 6 days.
- **A render after that re-encodes the clips it needs, at no charge.** A 4-minute film's clips take a few CPU minutes. The mix is cached by the clips' content, so the film itself is served from the cache if nothing changed.
- **Motion from fal isn't scratch.** It's paid for, so it stays with the pictures.

### 1.8 Deleting

- **A story:** its rows, as today. Its files and cache records stay under the owner's prefix, since the owner's other stories may share them, and no one else can reach them. They go with the account. A sweep for files no record names can come later, if the bill says so.
- **An account:** `store.forget(cfg, db, owner)` deletes `u/<user>/` and `scratch/u/<user>/` on R2, the owner's `steps` rows and their disk cache. It's idempotent: a second run finds nothing to delete. Phase I's account deletion calls it, along with the stories and the Stripe customer (question 4). The `user.deleted` webhook stays as Phase B left it.

### 1.9 Tests

Fakes, not mocks: the S3 client and the stores run against `FakeS3` in `providers/fake.py`, which keeps objects in a temp folder and checks signatures, payload hashes, expiry and ranges.

- **The client:**
  - AWS's published SigV4 examples, header and presigned, signed exactly;
  - put, get, a ranged get (206), head, delete, a list over more than 1,000 keys, delete a prefix;
  - a wrong secret gets 403, an expired URL 403, a body that doesn't match its hash 400;
  - `redact()` scrubs the R2 secret.
- **The stores:**
  - the folder behaves as before (the existing suite);
  - `put` uploads before `put_step` records;
  - `file` downloads on a miss, from `assets/` or `scratch/`;
  - a scratch row past its expiry is a miss;
  - `trim` keeps what was used in the last hour;
  - `forget` empties both prefixes and the rows, twice without error.
- **The exit tests:**
  - `test_a_hosted_film_keeps_every_file_on_the_bucket` (item 1): render, check every asset on the fake S3 under ann's prefix, wipe the disk cache, render again: nothing is submitted to fal or encoded.
  - `test_films_play_from_presigned_urls` (item 2): the film, a thumbnail, the subtitles and a download, following the 302. The same URL at 10:05 and 10:55, and a new one at 11:05. A range gives 206. The `download` name lands in `Content-Disposition`.
  - `test_each_user_pays_for_their_own_cache` (item 3) runs on the `steps` table now, and `get_steps` answers another owner's key with nothing.
  - `test_another_users_ids_answer_404` already covers `/api/assets` for bob.
- **The database:** the `steps` methods on SQLite and Postgres; migration 0005 from 0004 rows (`sqlite_only`); `test_models_match_the_migrations`; a copy of the real library; a Postgres round trip.
- **The API never runs ffmpeg in hosted:** the thumbnail route in hosted answers with no ffmpeg on `PATH`.
- **Live and opt-in** (`tests/test_live.py`, with your permission): the round trip in item 4 of the definition of done, against `lanternist-dev`, under a `test/<random>/` prefix it deletes afterwards. It costs a few hundred R2 operations, inside the free tier.

## 2. Steps

One pull request, `feat/storage` (question 5), with a commit per step below. The issue's two branches, `feat/s3` and `feat/r2-store`, become its commits.

### C1: the S3 client (≈ 1 day)

- [x] Plans and status: `ACCOUNTS_PLAN.md` done (#33); `HOSTED_PLAN.md` Phase B done and Phase C in progress; CLAUDE.md's plans list and README's plans line.
- [x] `providers/s3.py`, our own SigV4 signing, `S3Error`.
- [x] `FakeS3` in `providers/fake.py`, routed by `FakeWorld`.
- [x] `keys.PLATFORM` gains the R2 keys; `[storage]` in `config.py` and `lanternist.example.toml`.
- [x] The client's tests (AWS's five published signatures match exactly).
- [x] The live round trip against `lanternist-dev` (26 Sep, with your permission, inside R2's free tier):
  - a PUT with a key holding an `@`, as thumbnails have, then a HEAD;
  - a body that isn't its hash, refused with 400;
  - a ranged GET (206) through a URL signed at the top of the hour, with the object's type and `Cache-Control`;
  - the download name, UTF-8 included;
  - a URL signed three hours earlier, refused with 403;
  - a list, and deleting the prefix, which left nothing.

### C2: the R2 store (≈ 2 days)

- [x] **A commit of its own, with no change in behaviour:** `await ctx.store.file(…)` and `await on_item(…)` in the engines, `await store.put(…)` in `_stage`.
- [x] Migration 0005 (`/add-migration`), and the `steps` queries (`/add-query`).
- [x] `R2Store`, `store.of`, `get_steps` in `peek` and `_stage`, scratch clips, `trim`, `forget`.
- [x] Thumbnails made as pictures are stored.
- [x] `/api/assets` in hosted: HEAD, 302 to an hour-stable presigned URL, downloads, `.vtt` relayed. The fake S3 route for fake mode.
- [x] `hosted_client` runs on the fake S3. The exit tests.
- [x] CLAUDE.md's map (`store.py`, `providers/`), `.claude/rules/pipeline.md` for the async store, README for `[storage]`.
- [x] A manual run in fake hosted mode in a browser, on a scratch config and a free port (26 Sep, port 8431, Chrome):
  - sign-in through the fake page, then a 3-scene story rendered;
  - the reel's and the Board's pictures all came from presigned URLs: 768 px thumbnails, 200s in the log;
  - the subtitles track loaded through the API, with its 3 cues;
  - the film's address answered 302, then 206 `video/mp4` from its presigned URL;
  - Download MP4 saved as `the-lantern-keeper-v1.mp4`.

  The `<video>` itself didn't start: Chrome keeps the automation tab hidden, and it defers media there. The server log shows the MP4 was never asked for.
- [x] The film played on a real tab, with its narration and subtitles (26 Sep, port 8431, on `main` after #34): a 4-scene story written and rendered for `ann@example.com` through the fake sign-in, its address a 302 to the fake bucket.
- **Not done, and not a box:** the plan asked for a hosted film on `lanternist-dev` in a browser, with
  fake models and real R2. Fake mode fakes every provider through `providers.transport()`, R2 included,
  so that can't run. A film on the real bucket needs the real hosted edition:
  - real models (the cheapest film all on fal is about $0.11);
  - sign-in through WorkOS staging, since the fake sign-in page is fake mode's only;
  - a writer on OpenRouter, or an imported storyboard;
  - your go-ahead for the spend.

  The live round trip already shows the real endpoint serving presigned GETs with ranges, types and
  download names. The first film on a real bucket fits Phase G's staging run.

**Exit** (the definition of done above): items 1–5, with `scripts/check` and `scripts/check postgres` green. Then this plan's and HOSTED_PLAN's boxes and status lines, and a comment on #16.

## 3. Where the build departed from the design

- **No memory of HEAD answers in the process.** The browser already keeps each 302 until the hour
  ends, so a second in-process cache saved little, and it could have gone stale after a delete.
- **The API asks R2 through the S3 client, not an `R2Store`.** Key names and presigning are
  functions in `store.py` (`asset_key`, `derived_key`, `presigned`), so the API makes no cache
  folders, now or after Phase D.
- **`trim` runs after each job only,** not at start as well: nothing grows the cache while the
  server is down.
- **The local edition makes thumbnails as pictures are stored too,** one code path for both
  editions. The route still makes one on request for a picture drawn before this change.
  `test_a_picture_is_served_small_from_thumbnails_made_with_it` replaces the test that expected the
  first request to make it.
- **`Pipeline.find` is gone.** Locally there's one folder to look in; hosted asks R2.
- **The estimate batches its lookups too,** as do the picture check's "all cached?" and the portraits
  in `picture_items`: the estimate runs on every story page and at every enqueue. Opening a story and
  its estimate costs the same step lookups for 12 scenes as for 3 (fewer than 20), where one lookup
  per item made it 37 for 12
  (`test_opening_a_story_looks_up_its_steps_in_as_many_queries_for_12_scenes_as_for_3`).
- **`put_step` inserts first and updates on a conflict.** Updating first took SQLite's write lock
  before the insert, so another writer couldn't land; `test_two_workers_recording_one_step_at_once_keep_one_record`
  makes the race happen on both databases.
- **The folder store takes `scratch` and ignores it,** since only R2 lets files expire. Ruff's
  unused-argument check (ARG002) is silenced on those two lines, each with its reason.
- **Found by the self-review, and fixed:**
  - **A user's cancel could lose a paid output,** in both editions. Storing an output now awaits an
    upload and two thumbnails before its record, and a cancel in between kept the file but not the
    record, so the next run paid again. `whole()` now finishes storing an output before the
    cancel goes on (`test_a_cancel_while_an_output_is_stored_still_records_it`).
  - **`store.forget` would have deleted a local library:** there, the owner's folder is the library
    itself. It now refuses outside hosted.
  - **Deleting a prefix read no errors.** R2 answers DeleteObjects with a 200 that can still name
    keys it kept, and a missing bucket listed as empty. Both now raise with the key or the bucket.
  - **The voice catalogue asked once per voice;** now once in all.
  - **`files()` fetched every clip at once;** now `[storage] downloads` at a time.
  - **The per-owner layout lived in three places;** now `config.owner_folder` and its two folder
    names.
  - **A thumbnail cost two or three HEADs;** now one: the thumbnail under the user's prefix, which
    shows it's theirs.
  - Smaller: the migration's downgrade uses a table construct rather than SQL, and a test lost a
    reused name.
- **Found by the second self-review, and fixed:**
  - **The engines' own paid sub-steps were outside that protection:** each shot of a video, each
    narration chunk, a cloned voice. `whole()` moved to `engines/base.py`, and `FalEngine.keep_step`
    fetches, stores and records such a step whole.
    `test_a_cancel_while_a_paid_shot_is_stored_doesnt_pay_for_it_again`.
  - **A second cancel got through `whole()`,** and the Cancel buttons can be clicked twice. It now
    waits out any number of cancels, and `Runner.cancel` ignores a job already being cancelled.
  - **A server stopping mid-store dropped the store:** `Runner.stop` now waits for its jobs, up to
    `STOP_GRACE`.
  - **Fetching a result fal had billed was unprotected,** in both editions, from before this
    branch: fal counts a request done once it answers, so a cancel during the download paid again.
    The fetch is inside `whole()` now too.
  - **The voice catalogue still read prices once per voice;** it builds each voice's engine from the
    one entry, and costs 4 queries for 9 voices. `cached_samples` is the one lookup of samples.
  - **Deleting under a missing bucket failed with an IndexError;** it says the bucket is missing, and
    a kept key's message says what to check.
  - **The asset route asked for thumbnails under `shared/`,** where none can be.
- **Found by a third, narrow self-review of that commit, and fixed:**
  - **A failure while finishing took the cancel's place.** The runner then marked a stopped job
    failed rather than queued, and its lane never saw the cancel and ran the next job after `stop()`.
    `whole()` now waits with `asyncio.wait`, which never raises the work's error, and always passes
    the cancel on, with the failure as its cause.
  - **fal's result was still cancelled after fal had billed.** Once `poll()` sees a request complete,
    a user's cancel leaves its run open, and the next run resumes it rather than paying again. The
    fake fal can hold a result back (`result_gate`) for the test.
  - The message for files R2 kept suggests checking the token only for `AccessDenied`; the voice
    catalogue lost a wrapper and a second engine build; the cancel guard and the no-thumbnail lookup
    have tests.
- **Found by a fourth self-review, before the PR, and fixed:**
  - **fal marked a run done before its connection closed.** Closing awaits, so a cancel landing there
    left the run done and its result never stored, and the next run paid again. This was in `main`
    too. The run is now marked done after the close
    (`test_a_cancel_while_fals_connection_closes_resumes_rather_than_paying_again`, through the fake
    transport's `close_gate`).
  - **A store that failed as its job stopped was silent;** `whole()` now logs it, as the next run
    will pay for that step again.
  - The fake S3 takes an error code per kept key, so the plain "delete again" message has its test;
    the film on the real bucket is written up above rather than left as a box.
- **A step record that names a file R2 no longer has** raises `StoreError` rather than being a
  miss: only a hand deletion on the bucket could cause it, and a HEAD for every record to rule it
  out would cost every cached re-render a request per file.

Departures from HOSTED_PLAN and the issue, decided in this plan:
- Scratch lives at `scratch/u/<user>/`, not under `u/<user>/` (§1.1).
- `steps` has `expires_at`, and a `shared` row in `users` owns the samples' records (§1.3).
- Subtitles are relayed by the API, not redirected (§1.5).
- Store calls that move bytes are async (§1.2).
- A Board's cache lookups are batched (§1.2).

## 4. Questions, answered on 26 Sep 2026

Each answer was the recommendation.

1. **R2 buckets: one per environment, set up by Claude.** `lanternist-dev` now, staging and production in Phase G. A dev key can't reach users' films, and each bucket has its own rules. R2 tokens can be limited to buckets but not to prefixes, so one bucket for every environment would have let any key reach production. What was done on 26 Sep:
   - `wrangler` was already signed in to the account (OAuth, with R2 access), so no browser approval was needed. The account holds other projects' buckets too, which is why the token is scoped to one bucket.
   - `lanternist-dev` was created. R2 placed it in ENAM (eastern North America). Production's location hint follows the server's location in Phase G.
   - Its rules: `scratch-7-days`, and R2's own default rule, which aborts unfinished uploads after 7 days.
   - `.env` (gitignored) gained `CLOUDFLARE_ACCOUNT_ID` and empty `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` lines.
   - **Still yours:** create an R2 API token in the dashboard (R2 object storage → Manage API tokens), **Object Read & Write**, limited to `lanternist-dev`, and put its two values on those lines. Never in a chat or an issue.
2. **Signing: our own SigV4,** about 50 lines of `hmac`, `hashlib` and `urllib.parse`, pinned by AWS's published examples and the live test. No new dependency, as `.claude/rules/remote.md` prefers ("Don't add an SDK"). botocore, as HOSTED_PLAN planned, would have added 20 MB and 3 more packages, and a subclass copying its `add_auth` to sign at a fixed hour.
3. **The disk cache: 20 GB** (`[storage] cache_gb`), least recently used first, trimmed after each job to 16 GB. That's about 13 renders' worth of working files (a 4-minute film's clips and inputs are about 1.5 GB), on a CX43's 160 GB disk.
4. **Deleting an account: `store.forget`, built and tested now,** for Phase I's account deletion to call along with the stories and the Stripe customer. Deleting files from the `user.deleted` webhook now would leave stories whose pictures are gone, and there are no users to delete before the beta.
5. **One pull request** for the phase, `feat/storage`, as for Phase B.

## 5. Sources (read 26 Sep 2026)

- R2 presigned URLs (1 s to 7 days; the S3 endpoint only; GET, HEAD, PUT, DELETE): https://developers.cloudflare.com/r2/api/s3/presigned-urls/
- R2 lifecycle rules (a prefix, no wildcards; objects go within 24 hours of expiry; S3 API and wrangler): https://developers.cloudflare.com/r2/buckets/object-lifecycles/
- R2's S3 API (DeleteObjects, ListObjectsV2, CreateBucket, PutBucketCors and PutBucketLifecycleConfiguration implemented): https://developers.cloudflare.com/r2/api/s3/api/
- R2 API tokens (Object Read & Write scoped to buckets; the S3 key pair from a token): https://developers.cloudflare.com/r2/api/tokens/
- AWS SigV4 for S3, with the worked examples the tests pin: https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html · https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
