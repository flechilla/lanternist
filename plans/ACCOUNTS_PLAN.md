# Lanternist: editions and accounts

> **Status, 23 Sep 2026: built on `feat/accounts`, as one pull request, and checked against WorkOS staging.** This is Phase B of `HOSTED_PLAN.md` (issue #15). The sign-in provider is WorkOS AuthKit (#23), on its free plan: the custom domain ($99/month) waits until paying users justify it. The questions in §4 are answered.
>
> **Measured before writing:**
> - `Database` has 42 public methods. 24 read or change a row a user will own; the rest run the queue, keep prices and uploads, or open the database.
> - The API has 31 routes, and 14 of them take a `{story_id}`, `{job_id}` or `{asset}`.
> - `~/Lanternist` is at revision 0003, with 4 stories, 12 jobs, 62 step runs and no saved settings. A copy was taken before this work: `backups/lanternist-before-0004-2026-09-23.db`.

**Goal:** every row a user owns carries its owner, and every query reads it through the owner's id. The local edition becomes one implicit user and works exactly as before. The hosted edition signs people in with an email code or Google, and shows each person only their own stories, jobs, files and settings.

Definition of done:

1. **Two users in fake hosted mode** each write, board and render a story, and see only their own. A request for the other's story, job or file answers 404, for every route that takes one.
2. **A test lists `app.routes`** and fails for a route with an id that the cross-user test doesn't call. A second test fails for a `Database` method that neither takes the owner first nor is listed as shared, with its reason.
3. **The local edition works as before.** The step-key tests hold, and a copy of `~/Lanternist` opens after migration 0004 with all its rows owned by `local`.
4. **Signing in** with WorkOS AuthKit sets an HttpOnly session cookie. The progress stream works through it, signing out ends the session, and a write from another origin is refused.
5. **Fake mode covers sign-in:** a fake WorkOS answers the real client, so the sign-in flow runs with no keys (invariant 8).

---

## 0. Where we are

- **No owners.** Stories, jobs, step runs and settings belong to whoever reaches port 8420, which binds to localhost.
- **One store.** `Pipeline` makes `Store(cfg.library)`: every picture, film and cached step sits under `~/Lanternist`, and a render also copies its film to `~/Lanternist/films`.
- **Resuming a step.** `open_run(step_key, provider)` looks up a restart's unfinished fal request by step key alone. Two users with the same step would share one request.
- **Keys.** `keys.PROVIDERS` is the model providers: OpenRouter and fal. The Settings page sets their keys, and `redact()` scrubs them.
- **Settings.** `settings` is one row per key, and `prefs.EDITABLE` lists 11 keys, 4 of which tune providers (fal concurrency and media hours, OpenRouter's data rule and pinned writers).

## 1. Design

### 1.1 Two editions

- **Config.** `edition = "local" | "hosted"` at the top of `lanternist.toml`, default `local`.
  - `[hosted] url` is the address people use, such as `https://app.lanternist.com`. The sign-in callback is `<url>/api/auth/callback`, writes must come from that origin, and the cookie is `Secure` when it's https.
  - `[workos] api_url` and `client_id`. The client id isn't a secret. The API key and the webhook secret come from the environment only (§1.4).
  - `lanternist.example.toml` documents all of it.
- **Hosted refuses local defaults at start-up.** A validator on `Settings` checks that `defaults.tts`, `image`, `video` and `ambience` aren't `local/…`, that `defaults.writer` is `openrouter/…`, and that `checker` is empty or `openrouter/…`. For a wrong value it says which and what to set: "defaults.tts is local/qwen3-tts-1.7b, a model on this machine, which the hosted edition doesn't run: pick a remote one". At start-up, `config.settings()` also checks that each model default is one the hosted registry offers, with the right capability. It lists the ones that fit. The validator can't make this check: it runs over each user's saved values on every request, and those were checked when saved.
- **`/api/options` says which edition is running** (`"edition": "hosted"`), so the web app reads it rather than guessing.
- **What hosted leaves out:**
  - Routes it doesn't register: `/api/providers` (with the key routes), `/api/doctor` and `POST /api/voices`. The first two show the platform's keys and machine, and uploads wait for consent (HOSTED_PLAN §1.9). The admin view in Phase E brings a hosted health view.
  - Models. `registry.load(…, hosted=True)` keeps only entries that are remote and have `commercial_use = true`. The only models without it today are local ones. The writer catalogue skips Ollama.
  - The web app hides the System check, the key cards on Settings, and adding a recording on Voices.
- **Settings per user, platform settings in config.** `prefs.PLATFORM_SETTINGS` names the four provider-tuning keys. In hosted they come from `lanternist.toml` only: they're neither listed nor saved per user, so no one can take more fal slots or turn data collection on. The local user still edits all 11.

### 1.2 Owners

**Tables** (migration 0004, `accounts`):

| Table | Change |
|---|---|
| `users` | **new**: `id` (32; `local` for the local user), `auth_subject` (WorkOS user id, `local`, or `fake:<name>`; `uq_users_auth_subject`), `email` (nullable), `role` (`user`), `created_at`, `deleted_at` |
| `sessions` | **new**: `id` (sha256 of the cookie's token, 64 hex), `user_id` (`fk_sessions_user_id`, CASCADE, indexed), `provider_session` (WorkOS's `sid`, nullable, indexed), `created_at`, `expires_at` |
| `stories`, `jobs` | add `owner_id`, not null, → `users` CASCADE, indexed |
| `step_runs` | add `owner_id`, nullable, → `users` SET NULL, indexed: spend outlives accounts |
| `settings` | add `owner_id`, → `users` CASCADE; the primary key becomes (`owner_id`, `key`) |

- **Backfill.** The migration inserts the `local` user and sets `owner_id = 'local'` on every existing row. It adds each column nullable, fills it, then makes it not null, in batch mode for SQLite.
- **The downgrade** drops the columns, `sessions` and `users`. A hosted database with several users can't go back without losing who owns what, and the downgrade says so in a comment. For a local library the round trip is lossless.
- **Columns for plans and billing** (`plan`, `plan_status`, `billing_customer_id`, …) come with the Phase E and H migrations that use them.
- **HOSTED_PLAN §1.15's numbering moves by none.** 0004 is accounts, including `sessions`. Then 0005 is `steps`, 0006 the worker columns on `jobs`, 0007 `ledger` and `holds`, 0008 `moderation_events` and 0009 `webhook_events`.

**Queries.** Every `Database` method that reads or changes an owned row takes `owner: str` first and filters on it. A row that exists but isn't yours comes back exactly like a row that doesn't exist: `None` or `KeyError`, and so a 404.
- The owned lookups go through two private helpers, `_story(s, owner, id)` and `_job(s, owner, id)`.
- `library`, `jobs`, `spend_by_story` and `saved_settings` filter in SQL, so their query counts don't change.
- `open_run(owner, step_key, provider)`: a restart resumes only its own user's request.

**What doesn't take an owner**, listed in `db.SHARED` with the reason for each:
- The worker's methods, on the job it has claimed: `claim_job`, `requeue_running`, `update_job`, `spend_by_step`, `start_run`, `update_run` and `get_run`. A step run is written with its `owner_id`.
- What everyone shares: prices, uploads (content-addressed; a URL is found only by having the file), `step_seconds` and `writer_tokens_per_minute` (averages for estimates, showing no one's rows).
- The database itself: `migrate`, `revision`, `close` and `alembic_config`.
- Sign-in, which is how the owner is found: `sign_in`, `session_user`, `start_session`, `end_session`, `user_updated`, `user_deleted` and `revoke_session`.

`test_every_database_method_takes_the_owner_or_is_shared` checks each public method's first parameter against that list.

**The runner acts as the job's owner.** It reads `job.owner_id` and passes it on to settings, the storyboard, new versions and the pipeline. `Runner.enqueue(owner, …)` takes it from the route.

### 1.3 Files per user

- **`Settings.library_for(owner: str | None) -> Path`** is the one place that knows the layout:

  | Edition | Owner | Folder |
  |---|---|---|
  | local | anyone | `~/Lanternist`, as today |
  | hosted | a user | `<library>/u/<owner>` |
  | hosted | None | `<library>/shared` |

  Phase C keeps this layout on R2 (`u/<user>/…`, `shared/…`).
- **Each user has their own cache.** A second user asking for the same picture pays for it once, in their own folder. Nobody gets another's work for free, and nobody can see that another person made it.
- **The pipeline takes the owner** and builds its store from `library_for(owner)`. A render copies its film to the store's `films/`, which locally is still `~/Lanternist/films`.
- **Voice samples are shared.** A sample job runs with no owner, since a preset voice sounds the same for everyone. So its store is `shared`, and the voice catalogue reads it from there.
- **`/api/assets/{asset}`** looks in the user's own store first, then `shared`. Another user's picture answers 404, as a missing one does. Thumbnails follow the same rule.
- `models.toml` overrides stay at the library root: they're the platform's, not a user's.

### 1.4 Sign-in: WorkOS AuthKit

**The flow.** Sign-in uses the authorization-code flow against AuthKit's hosted pages, which offer email codes and Google, with no passwords.
1. **`GET /api/auth/sign-in`** (`?screen=sign-up` for new accounts) makes a random `state` and puts it in an HttpOnly cookie for 10 minutes. It then answers 302 to `https://api.workos.com/user_management/authorize` with `provider=authkit`, the client id, the redirect URI and the state.
2. **`GET /api/auth/callback?code&state`** checks the state against the cookie, then posts the code to `/user_management/authenticate` with the API key.
   - WorkOS answers with the user (`id`, `email`, …) and an access token. The token's `sid` claim names WorkOS's session. We read it without verifying the signature: the token came straight from WorkOS, over TLS, in answer to our own authenticated request.
   - `db.sign_in(subject, email)` creates the user, or updates their email.
   - `db.start_session(…)` stores the sha256 of a new random token. The token goes into the `lanternist_session` cookie: HttpOnly, SameSite=Lax, Path=/, `Secure` on https, and 30 days (`SESSION_DAYS`).
   - Then a 302 to `/`.
3. **Every request** reads the cookie, and `current_user` finds the session and its user in one query. The session must not be expired and the user not deleted. Otherwise the answer is 401, "sign in first".
4. **`POST /api/auth/sign-out`** deletes the session and clears the cookie. It answers with WorkOS's logout URL for the `sid`, which the web app follows. Otherwise AuthKit would sign the same person straight back in.

**Why our own session row** rather than the sealed-cookie pattern AuthKit's SDKs use:
- Each request reads the user row anyway, for their role now and their plan later. Finding the session in the same query costs nothing more.
- With a sealed cookie, the 5-minute access token would need refreshing from WorkOS on the request path.
- Signing out, deleting a user and WorkOS revoking a session all take effect at once, by deleting rows.
- No JWT library and no key set to fetch.
- Swapping the provider later changes the callback, not the sessions.

**CSRF.** SameSite=Lax keeps the cookie off cross-site writes. In hosted, a middleware also refuses a POST, PUT, PATCH or DELETE under `/api` whose `Origin` isn't `[hosted] url`. The webhook is exempt: it has no cookie and is verified by its signature.

**SSE** sends the cookie like any same-origin request, and the stream is checked once, when it connects. Nothing needs refreshing.

**Webhooks.** `POST /api/webhooks/workos` verifies `WorkOS-Signature`: `t=<timestamp>, v1=<HMAC-SHA256 of "t.body">` with the webhook secret, within 5 minutes. `t` is in milliseconds, as the staging run confirmed.
- `user.updated` updates the email.
- `user.deleted` sets `deleted_at` and deletes the user's sessions. Deleting their stories and files is Phase I's account deletion.
- `session.revoked` deletes the session with that `sid`.
- No `user.created`: the callback is the only way in, and it creates the user.
- The handlers are idempotent. Recording each event once in `webhook_events` comes in Phase H, for payments.
- Webhooks need a public address. The suite tests them against signed fake events. The staging run reached them through an ngrok tunnel, and production gets its endpoint in Phase G.

**The email** is written at every sign-in, and by `user.updated` in between.

**The client** is `providers/workos.py`: plain httpx through `providers.transport()`, like fal and OpenRouter. There's no WorkOS SDK, so the fake exercises the real client (invariant 8). It makes two calls: authenticate with a code, and build the logout URL.

**Keys.** `keys.PLATFORM = {"workos": "WORKOS_API_KEY", "workos_webhook": "WORKOS_WEBHOOK_SECRET"}`.
- These are secrets of the hosted edition, read from the environment only.
- No Settings card or CLI command sets them.
- `redact()` scrubs them along with `PROVIDERS` (invariant 4).
- `PROVIDERS` stays the model providers a user may hold keys for.

**The local edition** has no sign-in. `current_user` returns the `local` user and the auth routes aren't registered.

**Fake mode:**
- **The test header.** `current_user` takes `X-Lanternist-User: <name>` in hosted fake mode only. It signs that name in as `fake:<name>`, which lets tests act as two people.
- **Signing in by hand.** Fake mode's sign-in goes to `/api/auth/fake`, a one-field form ("sign in as…"). The form posts to the real callback with the code `fake:<email>`. The fake WorkOS in `providers/fake.py` answers `/user_management/authenticate` for that code with a user and a token carrying a `sid`.

### 1.5 The web app

- **Sign-in.** In hosted, `App` asks `/api/me` first. A 401 shows a sign-in page with two buttons: "Sign in" (email code or Google) and "Create an account". Both go to `/api/auth/sign-in`.
- **After that,** `call()` sends any 401 back to sign-in: a session that expired mid-visit.
- **The account menu** in the header shows the email and "Sign out".
- **What hosted hides** (§1.1): the System check, the key cards on Settings, and "Add a recording" on Voices. The Settings page lists what `/api/settings` sends, which in hosted is only the per-user rows.
- **`api.ts`** gets `me()`, `signOut()` and `Options.edition`.

### 1.6 Tests

- **Fixtures.** `hosted_client`: the app in fake hosted mode, with fal defaults, `[hosted] url` and the Origin header set. A helper sends requests as a named user.
- **The cross-user test.** `test_another_users_ids_answer_404` builds user A's story and runs a write, a board and a render. Then it calls every route in `app.routes` that takes `{story_id}`, `{job_id}` or `{asset}`, as user B, from a table of how to call each, and expects 404.
  - The test fails if the table and the routes disagree.
  - The SSE route and job cancel are in the table too.
- **Two users.** `test_two_users_see_only_their_own`: the Library, the jobs list, settings, and a picture by its hash.
- **Caches.** `test_each_user_pays_for_their_own_cache`: the same story boarded by two users runs every step twice. `test_a_restart_resumes_only_its_own_users_request` covers `open_run`.
- **The database.** `test_every_database_method_takes_the_owner_or_is_shared`, and the owned methods on both databases.
- **Migration 0004:**
  - `test_migration_0004_gives_every_row_to_the_local_user` (from 0003 rows, `sqlite_only`, as the other migration tests are);
  - `test_migration_on_a_copy_of_the_real_library` also checks the owners;
  - `test_models_match_the_migrations` on both databases;
  - a Postgres round trip, upgrade then downgrade, with rows.
- **Editions:**
  - hosted refuses local defaults;
  - `/api/options` names the edition;
  - the left-out routes answer 404 in hosted;
  - the registry and the writer catalogue in hosted;
  - Settings in hosted lists and saves only per-user keys.
- **Sign-in:**
  - the callback sets an HttpOnly, SameSite=Lax cookie, and `/api/me` answers;
  - a wrong or missing state is refused;
  - an expired session answers 401;
  - sign-out deletes the session and returns WorkOS's logout URL;
  - a write from another origin gets 403;
  - SSE works on the cookie;
  - a webhook with a bad or old signature gets 400, and `user.deleted` and `session.revoked` end sessions;
  - `redact()` scrubs the WorkOS key.
- **The local edition:** the existing suite unchanged, and the step-key tests untouched.

## 2. Steps

One pull request, `feat/accounts`, in four commits.

### Commit 1: plans and status (≈ 1 hour)

- [x] `DB_PLAN.md`'s status: done, merged as #13. `HOSTED_PLAN.md`'s status: Phase A done, Phase B in progress (this plan).
- [x] `CLAUDE.md`'s plans list and README's plans line.
- [x] HOSTED_PLAN for the 23 Sep decisions:
  - WorkOS AuthKit in §1.1, §1.2, §1.8, §1.11, §1.12, §1.14, §1.15, the phases, §5 decision 6 and §6, with the custom domain optional until paying users;
  - the US and Monsoft Solutions in §1.5 and §5 decision 2;
  - Turnstile on the grant rather than the form, in §1.9;
  - the migration numbering in §1.15.

### Commit 2: editions (≈ 0.5 day)

- [x] `edition`, `[hosted]`, `[workos]` in `config.py` and `lanternist.example.toml`. The hosted defaults validator.
- [x] `/api/options` edition. Hosted leaves out the provider, doctor and voice-upload routes.
- [x] The registry and writer catalogue filtered in hosted. `prefs.PLATFORM_SETTINGS`.
- [x] Web: the System check, key cards and recording upload hidden in hosted.

### Commit 3: owners (≈ 1.5 days)

- [x] Migration 0004 (`/add-migration`), and `users` and `sessions` in `db.py`.
- [x] `owner` on every owned `Database` method (`/add-query`), `db.SHARED`, and the method test.
- [x] `auth.current_user` for the local user and the fake header. Every route that touches owned rows takes it.
- [x] The runner and pipeline carry the owner. `library_for`, the per-user store, shared samples and the asset route.
- [x] The cross-user and two-user tests. The migration tests on SQLite and Postgres.
- [x] CLAUDE.md invariant 10: "Every row a user owns is read through their id, in `db.py`." The database and API rules say so too.

### Commit 4: sign-in (≈ 1 day)

- [x] `providers/workos.py` and the fake WorkOS. `keys.PLATFORM`, scrubbed by `redact()`.
- [x] `auth.py`: the sign-in, callback, sign-out, `/api/me`, the session cookie, the Origin check and the webhook.
- [x] The fake sign-in form.
- [x] Web: the sign-in page, the account menu, and 401 sending people back to sign-in.
- [x] A manual run against WorkOS staging (23 Sep, §4): sign up and sign in with Google, sign out back to the app, sign in again. Five real webhooks (`user.updated` and `session.revoked`) were accepted through ngrok. Email codes wait for Magic Auth to be switched on in the dashboard, which no API or CLI command can do. AuthKit runs both methods, so the callback doesn't change.

**Exit** (the definition of done above):
- [x] Items 1–5, with the suite passing on SQLite and Postgres: 273 tests on SQLite, and 270 on Postgres with the 3 `sqlite_only` ones skipped. Item 4 in fake mode; against WorkOS itself with the manual run above.
- [x] A copy of `~/Lanternist` opens after 0004, owned by `local` (`test_migration_on_a_copy_of_the_real_library`). The library itself hasn't been migrated: the first start on this branch does it.

## 3. Where the build departed from the design

- **The progress stream of another user's job says `gone`**, with a 200, as it does for a job that was deleted, rather than a 404. It's still the same answer as for a job that doesn't exist, and the web app already closes the stream on it. The cross-user test expects exactly that.
- **A voice sample's job belongs to whoever asked**, so they can follow it, and its step runs are theirs too. Only its files go to the shared store.
- **A hosted render doesn't copy its film to `films/`**, and its result has no `path`: a path on the server means nothing to the person, who downloads the film from the page.
- **`providers/fal.py` passes mypy now**, and has left the exempt list in `pyproject.toml`, since this work touched it (CLAUDE.md). A fal client made without a database refuses to log a request, with a sentence, rather than failing on `None`.
- **Settings errors read as sentences.** A validator's own words come back as written, rather than as pydantic's `: Value error, …`.
- **A sign-in that fails goes back to the sign-in page**, with a code in its address: `/sign-in?error=expired|cancelled|refused|unavailable`, `auth.Failure`. A JSON error in the browser would say nothing to the person. The page has its own sentence for each code, so a link can't put words of its own on the front door. The details, such as WorkOS's message, go to the server log.
- **`/api/me` answers in both editions**, as the local user locally. The web app asks it only in hosted.
- **The web app hides its nav until someone signs in**, and the Library no longer says films are made "on this machine", which isn't so in hosted.
- **The webhook needs `WORKOS_WEBHOOK_SECRET`** in `keys.PLATFORM`, beside `WORKOS_API_KEY`. Without it, every webhook gets a 503 saying to set it, and the server logs the same sentence. WorkOS retries a 5xx, so nothing is lost once it's set. A signed event is read through a Pydantic model.
- **Hosted clones no one's recording, found by the self-review.** Taking away the upload route wasn't enough. The recordings already in `paths.voices` (on this machine, your own) were still listed, played and cloned for every account. So in hosted:
  - the voice catalogue lists no recordings;
  - `/api/voices/{name}/audio` is on the `local` router;
  - a fal narrator refuses a voice that isn't one of its presets;
  - a narrator with no presets isn't offered at all.

  That leaves **Chatterbox out of the hosted edition**, though HOSTED_PLAN §1.4 puts it in the Free plan. It only clones, so it needs voices the platform has consent to clone. That's a question for Phase E's plans. The hosted tests narrate with Qwen3-TTS's presets.
- **A hosted user's files are sent as `Cache-Control: private`**, so no cache between the server and the browser can hand one person's picture to another who has its address.
- **`owner` has no default** in `Pipeline`, the step context, a fal request or the writer's calls. A server path that forgets it fails mypy, instead of quietly billing, storing and resuming as the local user. The CLI and the tests pass `LOCAL`.
- **Fake mode has stand-ins for both of AuthKit's pages**, sign-in and sign-out, at the same paths under `/api/auth/fake`. So the real addresses `WorkOS` builds are the ones fake mode follows.
- **`Pipeline.find(asset)`** looks in the owner's files, then the shared ones, for the asset route.
- **The `wait` test fixture asks the test's own app.** It used to ask for `client`, and a hosted test that used it restarted the app as the local edition in the middle. It also takes the headers of the user whose job it is.

## 4. Questions, answered on 23 Sep 2026

- **Which settings are per user?** The seven model and budget defaults. The four provider-tuning keys are platform settings, in config, in hosted.
- **A backup of `~/Lanternist`:** a copy by hand, taken before this work (above). No automatic backup in the code.
- **Pull requests:** one for all of Phase B.
- **Files per user:** in this phase (§1.3), rather than waiting for R2 in Phase C.
- **`users.email`:** written at every sign-in, and by `user.updated`. Not asked; it follows from AuthKit, where the callback is the only way in.
- **WorkOS staging, as set up for commit 4's manual run** (23 Sep). The account is under Monsoft Solutions. `WORKOS_API_KEY` and `WORKOS_WEBHOOK_SECRET` are in the repo's `.env`, which is gitignored; never paste them into a chat or an issue. The API key can set:
  - the redirect URI `http://localhost:8420/api/auth/callback` (`POST /user_management/redirect_uris`);
  - the webhook endpoint `https://wise-mastiff-sharing.ngrok-free.app/api/webhooks/workos`, for the three events above (`POST /webhook_endpoints`, whose answer holds the secret).

  The sign-out redirect and the app homepage URL need the dashboard, or the `workos` CLI after `workos auth login`: `workos authkit logout-uris set` and `workos config homepage-url set`. Both are `http://localhost:8420`. The redirect must equal the `return_to` we send, which is `[hosted] url`. Without them, WorkOS ends every sign-out on its own `app-homepage-url-not-found` page.
- **Still for the user:** switch on Magic Auth (email codes) in the dashboard, and switch off Email + Password, since the sign-in page promises no password. No API or CLI command reaches these settings.
