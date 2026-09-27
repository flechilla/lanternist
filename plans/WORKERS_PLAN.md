# Lanternist: workers

> **Status, 27 Sep 2026: planned, and the questions in §4 are answered; the build hasn't started.** This is Phase D of `HOSTED_PLAN.md` (issue #17). Its blockers, Phases B (#33) and C (#34), are on `main`. Migration 0006 is this phase's; Phase E takes 0007 and later. The sketch is at https://claude.ai/artifact/BmAX8JnpDTXUzrNneCtTNq. It has a job's life across processes, a simulator of fair turns, the encode timings and OVHcloud compared with Hetzner.
>
> **Measured before writing (26 Sep):**
> - **ffmpeg's share of a film, without a GPU.** The lab's `kite-baseline` (19 video scenes, 3 min 26 s) was rendered again from its cache with `render.encoder = "libx264"`, in a scratch copy of the lab library. The copy was guarded so that only the clips and mix stages could run. Pinned to 8 threads (`taskset -c 0-3,16-19`, 4 Zen 5 cores with SMT):
>   - as rendered, every scene a video: clips 60.9 s, mix 76.6 s;
>   - with every scene a still: clips 48.1 s, mix 66.4 s.
>
>   Scaled to a 4-minute film that is **about 2.7 minutes of CPU for a video film, and 2.2 for a stills film**. On all 32 threads the video film took 52 s, and with NVENC on the 5090 (its 22 Sep render) 23 s. The same film's ffmpeg commands, replayed from a 71 MB package, reproduced the 8-thread times within 3%. That package times the encode on the OVH VPS (§4, question 1).
> - **The queue today.** Each lane polls `claim_job` every 5 s, or wakes at once when the same process enqueues. A job's progress is written to its row at most every 0.25 s, and the SSE stream reads the row every 0.5 s. So a browser can already follow a job run by another process, and only claiming, cancelling and stopping are tied to one process.
> - **The fakes don't cross processes.** `providers.transport()` builds one `FakeWorld` per process. The fake fal keeps its requests in a dict, and the fake S3 keeps its objects in a temp folder of its own. With `serve` and `worker` apart in fake mode, the API couldn't serve a file the worker stored, and a second worker couldn't resume the first one's fal request (§1.8).

**Goal:** jobs leave the API process. `lanternist worker` processes claim them from Postgres, stamp a heartbeat on them, and hand them back when told to stop. A deploy or a crash no longer stops a render. A worker that dies has its job taken by another after a minute, and fal's open requests are polled again, not paid for again. Each person gets a fair turn, and a cancel reaches whichever worker holds the job. The local edition keeps its queue inside `lanternist serve`.

Definition of done (issue #17's exit, and the local edition as it was):

1. **Two workers and three users take fair turns.** Whoever was served longest ago goes next, and nobody runs more than `[worker] per_user` renders at once.
2. **A worker killed during a video** (SIGKILL, mid-request at fal): another picks the job up after `[worker] stale_seconds` and finishes the film. fal gets one request per video step.
3. **A cancel from the web reaches the worker that holds the job,** within one heartbeat, and cancels its requests at fal.
4. **A deploy** (SIGTERM) hands running jobs back to the queue at once, after storing what fal already billed. The next worker claims them without waiting out a heartbeat.
5. **The local edition works as before.** `serve` runs its own queue, one render at a time, and a restart requeues at once. No step key changes. A copy of `~/Lanternist` opens after migration 0006.

---

## 0. Where we are

- **One `Runner`, inside `serve`.** `jobs.Runner` runs two lanes: the samples (`FAST`) and everything else, one job at a time each. `api/app.py` builds it at import and starts it in the lifespan, after `db.migrate()`.
- **Claiming is already safe across processes.** `claim_job(fast_kinds, fast)` is one `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED) RETURNING`, oldest first (`DB_PLAN.md` §1.4). Two workers never get the same job.
- **Starting requeues everything.** `Runner.start()` calls `requeue_running()`, which puts every running job back in the queue. With two processes, that would take a live worker's jobs.
- **Cancelling is in memory.** `Runner.cancel` adds the job to `cancel_requested`, a set, and cancels its task. Only this set tells a user's cancel, which cancels at fal, from a shutdown, which leaves the request running to be resumed (`providers/fal.py`). A queued job is cancelled in the database (`cancel_queued`).
- **Stopping is clean.** `Runner.stop()` cancels the running tasks and waits up to `STOP_GRACE` (30 s). A task cancelled by a shutdown writes its job back as `queued`. `engines.base.whole` finishes whatever runs after fal bills, however often the task is cancelled.
- **Resume is M2's.** A fal step writes its `step_runs` row before polling. A later run of the same step finds the owner's open row (`open_run`) and polls the same request, if it's less than 50 minutes old (`RESUME_WINDOW`). Finished steps come from the cache: `steps` rows and R2 in hosted (Phase C).
- **The disk cache is trimmed after each job** in hosted (`store.trim`), and never loses a file used in the last hour.
- **The encoder** is `h264_nvenc` by default, and `ffmpeg.encode` falls back to libx264 when NVENC fails. The encoder is part of the clips' and the mix's step keys.
- **The tests** run the app through `TestClient`, whose lifespan starts the runner. `hosted_client` gets its jobs run that way too.

## 1. Design

### 1.1 Two commands, one `Runner`

| Command | Local edition | Hosted edition |
|---|---|---|
| `lanternist serve` | the API and the queue in one process, as today: one render lane (the GPU) and the sample lane | the API only. It adds jobs, asks to cancel, and streams progress. |
| `lanternist worker` | exits with "the local edition runs its jobs inside `lanternist serve`" | claims and runs jobs: `[worker] renders` renders at once, and the sample lane |
| `lanternist db upgrade` | migrates. `serve` still does it at every start, since a local library upgrades itself. | the deploy's step. `serve` and `worker` check the revision at start, and on an old schema say "the database is at 0005 and this version needs 0006: run `lanternist db upgrade`". |

- **The same `Runner` in both.** It gains a name (`<host>-<pid>`) and a number of render tasks. `serve` makes one with 1 render locally and starts it. In hosted it makes one it never starts, for adding jobs and asking to cancel. `lanternist worker` makes one with `[worker] renders` and runs it until SIGTERM or SIGINT.
- **Several renders per worker.** A render mostly waits on fal. Its CPU work is ffmpeg's few minutes at the end (measured above), so one render per process would leave the machine idle. `[worker] renders = 2` to start with. The timing on the OVH VPS sets it (§4, question 1). The sample lane runs one sample at a time, as today.
- **Idle lanes poll.** No other process can wake a worker, so an idle lane asks for work every second for samples and every 2 s for renders: about 1.5 queries a second per idle worker. A lane with a free slot asks again at once when a job ends. The local edition keeps its in-process wake as well.
- **`db upgrade` comes forward from Phase G** (HOSTED_PLAN §1.11). Phase D is where two processes first start together, and two processes migrating at once would race.
- **No `workers` table.** A worker matters only while it holds a job, and its jobs' heartbeats show that. An idle worker that dies costs nothing. Phase G's alert on queue wait catches the case where no worker runs at all.

### 1.2 The job's row (migration 0006)

| Column or constraint | Type | Why |
|---|---|---|
| `worker` | String(64), nullable | who holds the job (`<host>-<pid>`); cleared when it goes back to the queue |
| `heartbeat_at` | DateTime, nullable | the holder's last heartbeat |
| `cancel_requested_at` | DateTime, nullable | the owner asked to cancel a running job; the holder hears of it at its next heartbeat |
| `slot` | Integer, nullable | which of the owner's render slots the job holds (§1.3) |
| `uq_jobs_owner_id_slot` | unique (`owner_id`, `slot`) | two claims can't take the same slot. NULLs never collide, on SQLite or Postgres. |
| `ck_jobs_slot_running` | check: `slot IS NULL OR status = 'running'` | a job holds a slot only while it runs. Code that takes a job out of running and forgets the slot fails loudly. |
| `ix_jobs_owner_id_started_at` | index | keeps the claim's "served longest ago" to one index lookup as the history grows |

- **`cancel_requested_at` is a time, not the issue's `cancel_requested` flag.** `.claude/rules/database.md` lists the portable types, and Boolean isn't one. A time also says when.
- **`slot` isn't in HOSTED_PLAN §1.14.** It's what lets the database settle the per-person limit (§1.3), and §1.14 gains it.
- The migration follows `/add-migration`: `batch_alter_table` for SQLite, every constraint named, a real downgrade. A test upgrades a database holding 0005's queued, running and done jobs, and loses none. A local library gets the columns empty: its running jobs from before are requeued at the next start anyway (§1.10).

### 1.3 Claiming: fair turns and a limit per person

`claim_job(worker, fast_kinds, fast, per_user)` stays one statement:

```sql
UPDATE jobs SET status = 'running', worker = :me, slot = :slot,
       heartbeat_at = :now, started_at = :now, error = NULL
WHERE id = (
  SELECT q.id FROM jobs q
  WHERE q.status = 'queued' AND q.kind NOT IN (:fast_kinds)
    AND (SELECT count(*) FROM jobs r
         WHERE r.owner_id = q.owner_id AND r.slot IS NOT NULL) < :per_user
  ORDER BY q.started_at NULLS LAST,          -- a job that ran before goes first
           (SELECT max(r.started_at) FROM jobs r
            WHERE r.owner_id = q.owner_id AND r.kind NOT IN (:fast_kinds))
           NULLS FIRST,                      -- then whoever was served longest ago
           q.created_at                      -- then the oldest
  LIMIT 1 FOR UPDATE SKIP LOCKED)
RETURNING *;
```

- **Fair means served longest ago.** A limit alone isn't enough. If the oldest job always goes first, someone who queues later waits behind everyone's backlog. In the sketch's example (Ann three renders, Bob two, Cleo two five minutes later, two workers), Cleo's first film starts after 16 minutes with the oldest first, and after 6 with fair turns.
- **A job that ran before goes to the front.** It was running when its worker died or stopped, its owner is watching it, and most of it comes from the cache.
- **The limit is settled by the database.** Two workers can each count the other's claim before it commits, so the count alone would let a person run two renders at once. The unique (`owner_id`, `slot`) turns that race into an `IntegrityError`. The claim then tries the owner's next slot, from 0 up to `per_user - 1`, and otherwise leaves it to the next poll. On Postgres the second claim of a slot waits for the first to commit, then fails. On SQLite, claims run one at a time anyway.
- **Samples have no slots and no limit:** a voice sample takes seconds. Phase F's limits deal with abuse.
- **`[worker] per_user = 1`** (§4, question 2) until Phase E's `plans.toml` gives each plan its own. Then the claim reads the owner's limit through `users.plan`.

### 1.4 Heartbeats, the lease and requeueing

| Setting | Value | What it does |
|---|---|---|
| `[worker] heartbeat_seconds` | 10 | one `UPDATE` stamps every job the worker holds, and returns what it needs to know (below) |
| lease | ¾ of `stale_seconds` | a worker that hasn't landed a heartbeat for this long stops its own jobs as a shutdown, before anyone may take them |
| `[worker] stale_seconds` | 60 | after this, the next heartbeat of any worker puts the job back in the queue |
| `POLL` | 1 s · 2 s | how often an idle lane asks for work: samples, renders |
| `STOP_GRACE` | 30 s | a stopping worker stores what fal already billed, then hands its jobs back (unchanged) |

- **The heartbeat also listens.** `db.heartbeat(worker, job_ids)` stamps `heartbeat_at` on the jobs the worker holds and still runs, and returns one answer for each job the worker thinks it holds:
  - *held*: carry on;
  - *cancel*: `cancel_requested_at` is set, so the worker cancels as the user's cancel, which cancels at fal too;
  - *lost*: back in the queue, or another worker's, so the worker stops it as a shutdown and leaves fal's requests for the new holder to resume;
  - *gone*: the row was deleted with its story, so the worker cancels it as the user's cancel. Nobody will resume it.

  It's one statement, plus a second only when a job is missing, to tell lost from gone.
- **`requeue_stale(older_than)` replaces `requeue_running`.** It puts back every running job whose heartbeat is older than `older_than`, or missing, and clears its worker and slot. It's one statement. Each worker runs it after its heartbeat, so a dead worker's job waits between `stale_seconds` and `stale_seconds + heartbeat_seconds` after its last heartbeat. The local `serve` calls it with zero at start, since no other process can hold a local job.
- **The lease protects the handover.** A worker cut off from the database can't heartbeat. It stops its jobs itself at 45 s, 15 s before anyone may take them at 60 s. If the cut outlasts the stop, the jobs' final writes fail, and the worker logs that another worker will take them.
- **Two settings, not constants.** Ops may want a faster handover, and the process tests need one in seconds (§1.11). `lanternist.example.toml` documents them.
- **The clocks:** every timestamp is `db.now()`, from the machine writing it. A handover measured in tens of seconds tolerates the clock skew between NTP-synced machines.

### 1.5 Cancelling across processes

- **`db.request_cancel(owner, job_id) -> bool`** replaces `cancel_queued`. A queued job becomes `cancelled`, as today. A running one gets `cancel_requested_at`. A job that has ended, or isn't the owner's, gets False. It takes the owner first (invariant 10).
- **`Runner.cancel`** asks the database, and when the job runs in its own process it also cancels it at once: the local edition's cancel stays instant. In hosted, the holder hears of it within one heartbeat.
- **Deleting a story** asks to cancel its active jobs, then deletes the rows, as today. The holder's next heartbeat finds the row gone and cancels at fal. Its final write finds no row, which already does nothing (`test_deleting_a_story_while_its_job_runs_keeps_the_queue_going`).
- **The browser says "Cancelling…"** while the request waits. `job_dict` gains `cancelling` (a running job with `cancel_requested_at`), `api.ts`'s `Job` mirrors it, and the Cancel buttons of the dock, the reel and the film view show "Cancelling…", disabled.

### 1.6 Stopping, and deploys

- **SIGTERM or SIGINT:** the worker stops claiming, cancels its jobs as a shutdown (fal's requests keep running), and keeps its heartbeat going while `whole()` stores what fal billed, for up to `STOP_GRACE`. It then writes each job back as `queued`, with no worker and no slot, and exits 0. The next worker claims them at its next poll, and they go first (§1.3).
- **A job still storing after `STOP_GRACE`** stays running with a heartbeat that stops, and is requeued after `stale_seconds`.
- **Phase G's Compose file** gives workers `stop_grace_period: 60s`, so Docker waits past `STOP_GRACE` before SIGKILL.
- **uvicorn handles `serve`'s signals, as today.** In hosted, `serve` holds no jobs to hand back.

### 1.7 Fenced writes

- **Every write a worker makes to its job's row carries `worker = :me`:** progress snapshots, the version a picture check saved (`_take_version`), and the end. `update_job(job_id, worker, **fields)` matches nothing when the job has moved on. So a worker that lost its job changes nothing when it comes back, whether it was paused, cut off or slow.
- **The end frees the slot in the same statement.** Done, failed or cancelled keeps the worker's name for the record. Queued, handed back, clears it.
- **What isn't fenced:** `step_runs` and `steps`, which a stale worker and the new holder may both write for the same step. `put_step` already settles two writers (STORAGE_PLAN §3), and both poll the same fal request.
- **The last gap:** a worker cut off after fal billed a step, but before `whole()` recorded it, can lose that step's record. The new holder then pays for that one step again. It takes a database outage during that step's last seconds, and the lease keeps the window small.

### 1.8 Fakes that outlive a process

- **`FakeWorld(root)` keeps its state under `<library>/fake/`,** shared by every process that uses that library:
  - the fake fal's requests (endpoint, arguments, polls, cancelled, output, units) as one JSON file each, and its media as files;
  - the fake S3's objects, and the headers each was stored with.
- **Request ids become unique across processes** (`req-<random>`, not a counter).
- **What stays in memory:** the test steering (`fail_submit`, `result_gate`, `close_gate`, `billable_units_on`, …), per process. A test steers the fakes of the process it runs in.
- **`providers.transport(cfg)` passes the root.** Tests get theirs under `tmp_path` through the library, and `reset_fake()` still gives each test a fresh world. Invariant 8 holds for two processes: fake hosted mode is `serve` and `worker` in two terminals, and the README says so.

### 1.9 The CPU encoder, and sizing

- **Hosted encodes with libx264.** `Settings` in hosted makes it the default. Setting NVENC there explicitly is a configuration error, as a local model is: "render.encoder is h264_nvenc, which needs an NVIDIA GPU the hosted edition doesn't have: use libx264". The step keys carry the encoder, so hosted clips never mix with local ones, and no local key changes (invariant 1).
- **The number goes into HOSTED_PLAN §1.7 and §1.11** once the OVH VPS is timed (§4, question 1), with the machine's vCPUs. On 8 threads here a 4-minute film costs about 2.7 minutes of CPU. The guess for 8 shared cloud vCPUs is 4 to 7 minutes.
- **`[worker] renders` follows from it.** With ffmpeg's share at a few minutes and fal's at more, 2 renders per 8-vCPU worker should rarely encode at once. If the VPS shows shared vCores that are slow or stolen from, the worker moves to dedicated cores: a RISE-3 in the hosting decision (§4, question 5).
- **Encoding each frame twice** (the clip, then the film) is where the time goes. Encoding the clips faster is a later change, once measured, and not this phase's.

### 1.10 The local edition

- `serve` runs the queue with one render task, so the GPU lease is untouched (invariant 2). It heartbeats like any worker, so both editions run one code path, and it requeues every running job at start.
- `[worker]` settings other than `per_user` don't apply locally. With one render task, `per_user` never binds either.
- Nothing about the local library moves except migration 0006's empty columns.

### 1.11 Tests

Fakes, not mocks, on both databases (`scripts/check postgres`), and real processes where the exit test is about processes:

- **The claim:**
  - `test_claim_takes_turns_between_users`: three owners' jobs claimed in turn;
  - `test_a_person_at_their_limit_is_skipped`;
  - `test_a_job_that_ran_before_goes_first`;
  - `test_two_claims_for_one_person_cannot_both_win`: threads, as `test_claim_gives_each_worker_its_own_job` does. On Postgres it fails without the constraint.
- **Heartbeats and requeueing:**
  - `test_heartbeat_stamps_only_its_own_jobs`;
  - `test_heartbeat_tells_held_cancel_lost_and_gone`;
  - `test_requeue_stale_leaves_a_live_workers_job_alone`;
  - `test_a_worker_that_lost_its_job_writes_nothing`: progress, version and end are all fenced;
  - `test_a_worker_cut_off_from_the_database_stops_its_jobs`.
- **Cancelling:**
  - `test_a_cancel_reaches_the_worker_that_holds_the_job`: two `Runner`s on one database, the API's and a worker's (exit 3);
  - `test_a_deleted_storys_job_is_cancelled_at_fal`;
  - `test_a_running_job_says_cancelling`.
- **Two workers, three users** (exit 1): `test_two_workers_and_three_users_take_fair_turns`. Two runners with fake engines and `LANTERNIST_FAKE_PACE`, and the order of starts checked.
- **Real processes** (exits 2 and 4). `lanternist worker` subprocesses on the test's database and library, with `heartbeat_seconds = 0.5` and `stale_seconds = 3`:
  - `test_a_killed_worker_is_picked_up_and_pays_fal_once`: SIGKILL once the video's `step_runs` row is submitted, a second worker finishes the film, and the fake fal's shared requests show one submit per video step;
  - `test_sigterm_hands_the_job_back`: the job is queued within `STOP_GRACE`, and another worker finishes it with nothing paid twice.
- **The commands:**
  - `test_hosted_serve_runs_no_jobs`;
  - `test_a_worker_on_an_old_schema_says_to_upgrade`;
  - `test_the_local_worker_command_says_where_jobs_run`;
  - `test_the_hosted_encoder_is_libx264`.
- **The fakes:** `test_fakes_share_their_state_across_worlds`: a fal request submitted through one `FakeWorld` is polled to its result through another on the same root, and an object put through one is read through the other.
- **The database:** migration 0006 from 0005 rows; `test_models_match_the_migrations`; a copy of the real library; the new methods in `db.SHARED` (`heartbeat`, `requeue_stale`), and `request_cancel` taking the owner.
- **The fixtures:** `hosted_client` migrates first, then runs a worker beside the app in a thread with its own event loop, as `lanternist worker` would, and stops it at teardown. The hosted tests that render keep passing unchanged.
- **Live and opt-in** (`tests/test_live.py`, with your permission, §4 question 4). A hosted film on `lanternist-dev` and Postgres, with two 480P video scenes:
  - its worker is killed mid-video, and another finishes it with one fal request per video step;
  - then a second render is cancelled mid-video, and its fal requests end `cancelled`.

  It costs about $1 on your fal and OpenRouter keys, and it closes M2's live check of a restart and a cancel mid-video (M2_PLAN, Phase F's exit).

## 2. Steps

One pull request, `feat/workers` (question 3), cut from `chore/phase-c-done`, with a commit per step. The issue's two branches, `feat/worker` and `feat/worker-turns`, become D1 and D2.

### D1: jobs leave the API (≈ 1.5 days)

- [x] This plan, and the status lines: HOSTED_PLAN (Phase D in progress, the hosting decision), CLAUDE.md's list of plans, and README's.
- [ ] Fakes that outlive a process (§1.8), with no change in behaviour within one process.
- [ ] Migration 0006 (`/add-migration`), and the queries: `claim_job` with the worker, `heartbeat`, `requeue_stale`, `request_cancel`, and a fenced `update_job` (`/add-query`).
- [ ] The `Runner`: a name, several render tasks, polling, the heartbeat task with its four answers, the lease, and fenced progress and ends.
- [ ] The commands: `lanternist worker`, `lanternist db upgrade`, `serve` without the queue in hosted, and the revision check.
- [ ] "Cancelling…" in the web app.
- [ ] `hosted_client` with its worker; the tests above for D1.

### D2: turns and deploys (≈ 1.5 days)

- [ ] The fair claim: slots, `[worker] per_user`, requeued first, then served longest ago.
- [ ] SIGTERM and SIGINT hand jobs back.
- [ ] The process tests: a killed worker, and SIGTERM.
- [ ] libx264 in hosted.
- [ ] The timing on the OVH VPS (question 1), written into HOSTED_PLAN §1.7 and §1.11, and `[worker] renders` set from it.
- [ ] Docs: README (hosted is `serve` plus `worker`, and `db upgrade`), `lanternist.example.toml` `[worker]`, CLAUDE.md's map (`jobs.py`), and `.claude/rules/database.md` on fenced writes and `request_cancel`.
- [ ] The live check (question 4), with your go-ahead at the time.

**Exit:** items 1–5 of the definition of done, with `scripts/check` and `scripts/check postgres` green and `/self-review` done. Then this plan's and HOSTED_PLAN's boxes and status lines, and a comment on #17.

## 3. Where the build departed from the design

Nothing yet.

Departures from HOSTED_PLAN and the issue, decided in this plan:
- `cancel_requested_at`, a time, for the issue's `cancel_requested` flag (§1.2).
- A `slot` column with a unique constraint settles the per-person limit (§1.2, §1.3).
- Fair turns mean served longest ago, and a job that ran before goes first (§1.3).
- A worker runs several renders (`[worker] renders`), and the issue's "two workers" are two processes (§1.1).
- Fenced writes and a lease at ¾ of `stale_seconds`, which HOSTED_PLAN doesn't cover (§1.4, §1.7).
- The heartbeat and staleness are `[worker]` settings, not constants (§1.4).
- `lanternist db upgrade` comes forward from Phase G (§1.1).
- The fakes keep their state under the library, shared by processes (§1.8).
- No `workers` table (§1.1).

## 4. Questions, answered on 26 Sep 2026

The first two come from the issue, and the fifth is decision #26.

1. **Where to time libx264: your OVH VPS.** You chose it, since you have one and can buy more resources if needed. Claude first looks at what else runs there and how many vCPUs it has. It then replays the exact ffmpeg commands of the 8-thread run above (the 71 MB package, with a static ffmpeg in a temp folder, deleted afterwards). A VPS with fewer than 8 vCPUs still gives the speed of one cloud vCPU, which is what the guess lacks. **Still yours:** the VPS's SSH address and user, and whether anything else runs on it, since the timing keeps its CPU busy for a few minutes.
2. **Renders at once for one person, until plans exist: 1** (`[worker] per_user`). It's the Free plan's number in HOSTED_PLAN §1.4, and one render already keeps fal's two starting slots busy.
3. **One pull request, `feat/workers`,** with a commit per step, as for Phases B and C. D2's exit test needs D1, and they deploy together.
4. **A live check at the end: yes** (§1.11), about $1 on your keys, asked for again before it runs.
5. **Hosting (#26): OVHcloud US, in Vint Hill.** Hetzner, as HOSTED_PLAN §1.11 planned it, no longer holds. Read on 26 Sep:
   - every CX, CAX and CPX plan says "This product is currently unavailable";
   - CX is sold only in Germany and Finland;
   - Hetzner's status page has shown "Limited availability of cloud instances" since 26 Jun;
   - after the 15 Jun price rise, the CCX13 has 2 dedicated vCPU for €42.99, and a US CPX41 costs $141.49 a month.

   The choice:
   - **API and a worker:** a VPS-4 (8 vCores, 24 GB, 200 GB, unlimited traffic), $27.50 a month or $23.37 on 12 months;
   - **staging:** a VPS-1 or VPS-2;
   - **Postgres:** Neon, as planned;
   - **the worker, if the timing asks for dedicated cores:** a RISE-3 (Ryzen 9 5900X, 12 cores, $110);
   - **the account:** a new us.ovhcloud.com account for Monsoft. OVH US LLC is a separate company, and a VPS bought on ovhcloud.com can't run in a US region.

   It's recorded on #26, which stays open for the name, the domains and the beta. Phase G's plan rewrites §1.11 from it.

## 5. Sources (read 26 Sep 2026)

- Postgres `SELECT … FOR UPDATE SKIP LOCKED`: https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE
- Unique constraints treat NULLs as distinct: https://www.postgresql.org/docs/current/ddl-constraints.html · https://www.sqlite.org/lang_createtable.html
- Compose's `stop_grace_period`: https://docs.docker.com/reference/compose-file/services/
- Hetzner: billing (hourly, rounded up, capped at the month) https://docs.hetzner.com/cloud/billing/faq/ · plans and "currently unavailable" https://www.hetzner.com/cloud/cost-optimized and https://www.hetzner.com/cloud/regular-performance · the 15 Jun prices https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/ · the status notice https://status.hetzner.com/
- OVHcloud US: the VPS range https://us.ovhcloud.com/vps/ · Public Cloud prices, and the 1 Oct change to IPv4 and storage billing https://us.ovhcloud.com/public-cloud/prices/ · the separate US account https://us.ovhcloud.com/bare-metal/faq/ · the São Paulo Local Zone, on the roadmap with no date https://github.com/ovh/public-cloud-roadmap/issues/904
- Ping times between cities (third party): https://wondernetwork.com/pings
