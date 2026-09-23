# Lanternist Hosted: the SaaS edition

> **Status, 23 Sep 2026: Phase A done (`DB_PLAN.md`, merged as #13); Phase B in progress (`ACCOUNTS_PLAN.md`); the rest planned.** The product direction changed on 22 Sep: Lanternist is to be a hosted service. People buy credits and spend them on films, and a plan (tier) decides which models they may use. Running on your own GPU stays, as the way we develop the app. Each phase gets its own plan in `plans/` when it starts, and the work is tracked in the epic, issue #14. §5 lists the decisions only you can make: sign-in (6) and where the business is registered (2) were settled on 23 Sep.
>
> Facts about Stripe, Paddle, Polar, Clerk, WorkOS, R2, Neon, Hetzner, fal, OpenRouter, moderation models and the law were read from their own pages on 22 Sep 2026 (sources in §6). Anything marked **verify** wasn't confirmed. The legal points are research, not legal advice: §1.10 needs a lawyer before the public launch.

**Goal:** someone with a phone and a card signs up, gets enough free credits for a first short film, and makes story films on hosted models, with no GPU, keys or install. They see the price in credits before anything is spent, and pay only for what ran. Credits come from packs and monthly plans; the plan decides which models, resolutions and lengths they may pick. The same code still runs on one machine with local models for development (the local edition), and in fake mode with no keys at all.

Definition of done (the acceptance test at the end of Phase I):

1. **Sign up** with email or Google, on a phone. The account gets the sign-up grant once, after the email is verified.
2. **New story**, Spanish, kids 5–8, 3 minutes. The pickers offer the Free plan's models; the others show which plan unlocks them.
3. **Board and render a stills film.**
   - The estimate is shown in credits, and the credits are held before the job starts.
   - Each step then charges what it actually cost plus the markup, and the rest of the hold comes back at the end.
   - The account's history adds up to its balance.
4. **A scene blocked by moderation** costs nothing and says why, in words a parent understands.
5. **Buying.**
   - A credit pack bought with a test card arrives once, even when the webhook is delivered twice.
   - Subscribing to a plan grants its credits and unlocks its models.
   - Cancelling locks them again at the end of the period.
6. **Isolation.** Two users render at once on two workers. Neither can read the other's stories, jobs, pictures, films or spend: every route with the other's id answers 404.
7. **A deploy during a render.** The render carries on in the new worker and pays fal for nothing twice.
8. **Deleting the account** deletes its stories, files and Stripe customer. The ledger rows stay, without the person, for the accounts.
9. **Fake mode** runs all of it with no keys: fake sign-in, fake payments, fake storage, fake models (invariant 8).
10. **Every film** carries a signed content credential and a watermark, and says it was made with AI (§1.10).

---

## 0. Where we are

The MVP made films on the 5090. M2 made every stage able to run remotely: the writer on OpenRouter; narration, pictures, video and ambience on fal. So a film can already be made with no GPU. What M2 built is most of what a paid service needs underneath:

| Built | Becomes, in the hosted edition |
|---|---|
| The engine interface and the registry, with list prices, billing prices, launch prices that end on a date, and `commercial_use` | The catalogue users pick from, filtered by plan and licence (§1.4) |
| `estimate()` before every board and render, from the same items the stages run | The credit hold (§1.3) |
| The budget check before each remote stage (`Pipeline._check_budget`) | The "enough credits?" check, and topping up the hold |
| `step_runs`: every step's billed units and cost in micro-dollars, written before polling | What each step charges, one ledger row per step (§1.3) |
| Resume after a restart without paying twice; a user's cancel cancels at fal | Deploys in the middle of renders (§1.7) |
| `providers/fake.py`: fal and OpenRouter faked at the httpx transport | The same pattern for Stripe, sign-in and storage (§1.13) |
| The picture check (a vision model per picture, $0.0006 each) | Also asks whether the picture suits the audience (§1.9) |
| Progress on the job row, streamed by SSE | Works unchanged across processes, since workers write the row and the API reads it |

What's missing, in the order the phases take it:

- **Accounts.** There are no users: stories, jobs, settings and files belong to whoever reaches port 8420.
- **Postgres and one home for queries.** Done in Phase A: every query is in `db.py`, and the tests run on SQLite and Postgres (`DB_PLAN.md`).
- **Storage.** Files live in `~/Lanternist`, and the step cache is JSON files beside them.
- **Workers.** One runner, inside the API process, runs one job at a time.
- **Money.** A budget caps the user's own spend on their own keys; there are no credits, plans or payments.
- **Safety and law.** No moderation of what people type, no content credentials, and voice cloning from any upload.

**Before Phase E (credits),** finish what M2 left to check live. It's cheap (about $3–5 on your keys) and it's the ground credits stand on:
- stop the server during fal video and start it again, and cancel a render mid-video;
- Kling with MMAudio.

From the film-quality review, two items matter once people pay:
- **Film length.** The demo narrator speaks about 185 words a minute against the 150 the writer plans for, so "3 minutes" comes out 10% short.
- **The estimate.** It still leaves out the picture checks and their redraws.

---

## 1. Design

### 1.1 One codebase, two editions

A new top-level setting, `edition = "local" | "hosted"`, decides what differs. Everything else is shared: the storyboard, the writer, the pipeline, the engines, the estimate, the web app.

| | Local (today, and our development setup) | Hosted |
|---|---|---|
| Who | One person on this machine; no sign-in | Accounts, through WorkOS AuthKit (§1.2) |
| Database | SQLite in the library | Postgres (Neon) |
| Files | `~/Lanternist` | R2, one prefix per user (§1.6) |
| Jobs | The runner inside `lanternist serve` | `lanternist worker` processes (§1.7) |
| Models | Local engines and remote ones on your own keys | Remote models only, with `commercial_use = true`, on the platform's keys, filtered by plan |
| Money | A per-story budget in dollars | Credits, holds and plans (§1.3–1.5) |
| Keys | Environment, keychain, file; set on the Settings page | Environment only; the Settings page has no keys |
| Voices | Recordings you add; clone engines copy them | Preset voices only; no uploads (§1.9) |
| Migrations | At every start, as today | A deploy step, before the new containers start |

**The local edition is one implicit user.** `current_user` returns a user with id `local`, so every route and query takes a user in both editions, and there's one code path. The migration that adds owners backfills `local` into the rows already in a library.

**Open source.** The blueprint planned an AGPL self-hosted edition beside the hosted one. The local edition keeps that possible at little cost. Whether to publish it is decision 1 (§5), and nothing in Phases A–I depends on it. The desktop apps and the multi-OS work (blueprint M6) are out of scope (§4).

### 1.2 Accounts and tenancy

**Sign-in is WorkOS AuthKit** (decided 23 Sep 2026, #23), with email codes and Google, and no passwords. The design is in `ACCOUNTS_PLAN.md` §1.4.
- **Why AuthKit:**
  - Its hosted pages and emails come in es-419 and pt-BR, the languages of the people we expect.
  - Our own FastAPI sets the session cookie, HttpOnly, after the sign-in callback. EventSource sends it, so SSE needs no token refresh.
  - Free to a million users. The custom domain ($99/month) is optional: until paying users justify it, the sign-in pages and emails use WorkOS's domain.
  - Invitations and a waitlist for the closed beta, free.
  - With no passwords there are no hashes to be locked in, so moving provider later is cheap.
- **Where it lives.** One module, `auth.py`, behind a `current_user` dependency, and the client in `providers/workos.py`. Swapping providers later touches those and the sign-in page.
- **The rejected alternatives:**
  - Clerk: localization is experimental, its emails are in English without paid templates, its token is a 60 s script-readable cookie, and it costs about $1,025/month at 100k users.
  - Supabase Auth, unless data must stay in the EU or Brazil. Auth0.
  - Our own email codes with Authlib: we would own email delivery, its translations, rate limits and account linking.
  - Better Auth: a TypeScript library, so a Node service beside FastAPI, with tables outside `db.py`.
- **Details:**
  - The callback exchanges the code for the user, then stores a session of our own (a random token in the cookie, its hash in `sessions`), for 30 days.
  - SameSite=Lax, plus an `Origin` check on every write, is the CSRF defence.
  - The `users` row is created at the callback, the only way in. Signed `user.updated`, `user.deleted` and `session.revoked` webhooks keep it current.

**Every row a user owns carries `owner_id`,** and every `Database` method that reads or changes one takes the user first. That's why Phase A puts every query in `db.py`: the filter is written once per method, and nowhere else.
- **Rows that carry an owner:** `stories` (and through them, versions and jobs), `jobs`, `step_runs`, `settings` (now per user) and the ledger.
- **Rows shared by everyone:** `model_prices`, and `uploads`, which are content-addressed and don't reveal who uploaded.
- **Not found looks the same as not yours.** A route asked for another user's story, job or asset answers 404, exactly as for one that doesn't exist.
- **A test enumerates `app.routes`** and fails for any route with a `{story_id}`, `{job_id}` or `{asset}` that the cross-user test doesn't call (§1.13). A new route can't slip past it.
- **New invariant for CLAUDE.md:** "Every row a user owns is read through their id, in `db.py`."

**Admins** are users with `role = "admin"`. They get `/api/admin/*` and `lanternist admin …`, for:
- users and balances;
- today's spend against the cap;
- granting credits (the closed beta runs on this, before payments);
- suspending an account;
- the moderation log.

### 1.3 Credits: a ledger, holds and markup

**The unit.** The ledger stores retail value in integer micro-dollars, like every other amount in the app (invariant 5). A credit is only a way of showing it: `hosted.credit_usd = "0.01"`, so 1 credit = 10,000 micros.
- A step that costs a fraction of a credit (a $0.0006 picture check is 0.12 credits at 100% markup) is charged exactly. The balance is shown rounded down.
- Stripe's own "billing credits" don't fit. They apply only when an invoice is finalised, only to metered subscription items, and Stripe says they "can't be offered as stored value". So the ledger is ours.

**Two tables:**
- **`ledger`**, append-only. Kinds: `grant` (sign-up, admin), `purchase` (a pack), `plan_grant` (a period of a plan), `capture` (a step), `refund`, `adjust` (disputes, corrections).
  - The balance is the sum of the user's rows, never a stored number.
  - A row has an `external_id`, unique, holding the Stripe object it came from. A webhook delivered twice adds nothing.
  - A capture names its `step_run_id`, also unique, so a step is never charged twice.
- **`holds`**, one per job: the amount held and what's been captured against it, open until the job ends.
  - Available credit = balance − (held − captured) over open holds.

**The flow**, reusing what M2 built:

1. **Enqueue.** The estimate (already computed for every board and render) is priced at retail, per line, with each model's markup.
   - The hold is that total plus 20%.
   - The user's row is locked while it's placed (`SELECT … FOR UPDATE`), so two jobs started at once can't both spend the same credit.
   - If the user can't cover it, nothing is queued: the answer is "needs 140 more credits", with a Buy button.
2. **Before each remote stage** (where `_check_budget` runs today), the pipeline checks that captured + this batch's estimate fits in the hold.
   - If it doesn't, it tops the hold up from available credit.
   - If that's not enough either, the job stops with `CreditsShort`. That's a sibling of today's `BudgetExceeded`: nothing was spent on the stage, and "buy credits and carry on" resumes from the cache.
3. **Each step that finishes (`done`) with a cost** captures `cost_micros × (1 + markup)` in the same transaction that closes its `step_runs` row.
   - Writer calls and picture checks capture too.
   - Local steps don't exist in hosted.
4. **At the job's end,** done or not, the hold closes and whatever wasn't captured is free again.

**What isn't charged:**
- A failed or cancelled step.
- A step fal refused for its content (`content_policy_violation`, or a black picture flagged `has_nsfw_concepts`).
- A step served from the user's own cache. Their re-renders stay as cheap as they are today.
- When fal or OpenRouter billed us anyway (OpenRouter bills failed writer attempts), the cost stays in `step_runs` as ours. The admin view shows it.

**Markup is per model:** `markup` in the registry entry, falling back to `hosted.markup` (default `"1.0"`, i.e. +100%). Cheap models can carry more margin and premium video less, without touching code. Payment fees come out of it: a $10 pack costs about $0.75–1.15 in fees (§1.5).

**The story budget stays** as an optional cap in credits. A parent can say "never more than 300 credits on this one". The existing flow for raising a budget covers it.

**Credits don't expire at launch,** whether bought or granted by a plan: one balance, no buckets. Expiry can come later if the numbers show hoarding (decision 4).

### 1.4 Plans

**Plans live in one file,** `plans.toml` beside the registry: id, label, monthly credits, and limits. Stripe's price ids are per environment, in config. Registry entries gain `plan`, the lowest plan that may use them, and a quality option can carry its own (`quality.plans = { "1080P" = "pro" }`).
- **The API enforces it.** A story whose models the user's plan lacks is refused before it's queued: "Kling v3 Pro comes with Pro. See plans in Billing."
- **The pickers show it.** A locked model is shown with the plan that unlocks it, not hidden.

**The writer list is curated in hosted.** Locally, the writer picker lists every OpenRouter model with structured output. Hosted, it lists a short set in `registry/writers.toml`, each with its plan. The live list can't be vetted for quality, safety or data handling, model by model.

**What a 3-minute film costs us**, at list prices after H3's launch price ends on 30 Sep. The assumptions: about 27 shots, 2,700 characters of narration, and a cast sheet plus 4 portraits.

| Film | Models | fal + OpenRouter | At +100% |
|---|---|---|---|
| Stills, economy | GPT-5.6 Luna, Chatterbox, klein 9B | ≈ $1.15 | ≈ 230 credits |
| Hybrid (30% video), economy | the same + H3 Max Turbo 480P for 54 s | ≈ $2.50 | ≈ 500 |
| Full video, economy | H3 Max Turbo 480P | ≈ $5.65 | ≈ 1,130 |
| Full video, 768P | H3 Max Turbo 768P | ≈ $8.35 | ≈ 1,670 |
| Stills, premium | Opus 5, ElevenLabs v3, Nano Banana Pro | ≈ $5.30 | ≈ 1,060 |
| Full video, premium | the premium stills + Kling v3 Pro | ≈ $25.50 | ≈ 5,100 |

Pictures set the price of a stills film; the video model and its resolution set everything else. The writer is a rounding error, except Opus. Moderation and the picture check add about $0.05 a film.

**A plan structure to react to.** The names, prices and credit amounts are placeholders: decision 3.

| | Free | Plus | Pro |
|---|---|---|---|
| Credits | a sign-up grant, enough for one 2-minute stills film (≈ 150) | monthly, e.g. $12 → 1,200 | monthly, e.g. $30 → 3,300 |
| Pictures | klein 9B | + Seedream 5.0 Pro, Nano Banana 2 | + Nano Banana Pro, FLUX.2 [max] |
| Video | H3 Max Turbo 480P | + 768P, H3 Max, Wan, LTX-2.5 fast | + 1080P, Kling v3 Std/Pro, Veo 3.1 |
| Narration | Chatterbox, Qwen3-TTS presets | + ElevenLabs v3, MiniMax Speech | the same |
| Writer | GPT-5.6 Luna, DeepSeek V4.1 Flash | + Sonnet 5 | + Opus 5 |
| Length | up to 3 minutes | up to 6 | up to 10 |
| Renders at once | 1 | 1 | 2 |

Credit packs (say $10, $25, $50) are sold to every plan, Free included. Packs under $10 lose too much to fixed fees.

### 1.5 Payments

**Checkout Sessions created on our server,** full-page:
- `mode=payment` for packs and `mode=subscription` for plans.
- `client_reference_id` is the user; `metadata` holds the pack or plan.
- The Customer Portal handles card changes, plan switches and cancellation. It's translated into es-419 and pt-BR.

**The webhook route** verifies `Stripe-Signature` against the raw body and records each event once, in `webhook_events` (unique provider + event id). It answers 2xx at once and applies the event in a job. Stripe sends events out of order and sometimes twice, so every handler is idempotent on the object's id:

| Event | What it does |
|---|---|
| `checkout.session.completed` (paid), `checkout.session.async_payment_succeeded` | A `purchase` row for a pack. The success page calls the same function, safe to run twice. |
| `invoice.paid` | A `plan_grant` for the period, and `users.plan` set to the plan. |
| `customer.subscription.updated` | The plan changes (up at once, down at the period end), or it goes `past_due` or `unpaid`. |
| `customer.subscription.deleted` | Back to Free at the period end. The credits stay. |
| `charge.refunded`, `charge.dispute.created` | An `adjust` row taking back up to the refunded credits. Map a charge to its invoice through the Invoice Payments list: since API 2025-03-31, a charge no longer names its invoice. |

**Merchant of record.** Selling to consumers in the EU and Latin America means collecting and filing VAT/GST in many countries. A merchant of record does that for us. **Decided 23 Sep 2026 (#24): Stripe Managed Payments.** Lanternist is a product of Monsoft Solutions, a US company that already has a Stripe account, so Paddle is out; #31 tracks turning Managed Payments on for that account. The options as they were weighed:
- **Stripe Managed Payments** (generally available since 22 Apr 2026, AI services eligible since 2 Jun):
  - The same Checkout, webhooks and portal as plain Stripe, so the code above doesn't change. +3.5% on top of Stripe's fees.
  - Pix in Brazil.
  - Only for businesses based in the US, Canada, 31 European countries, Australia, Hong Kong, Japan or Singapore; none in Latin America.
  - **Verify** with Stripe that prepaid credit packs qualify.
- **Paddle**, if we aren't eligible:
  - 5% + 50¢ all-in, and its docs describe exactly our pattern ("sell prepaid credits as one-time products and track the balance in your application").
  - Payouts almost anywhere.
  - Its webhooks map one to one onto the table above: `transaction.completed`, `subscription.*`, `adjustment.created`.
  - The payments module is small either way, but it's chosen once.
- **Plain Stripe** is cheapest per payment (about $0.74 on a $10 foreign card), but then we register and file taxes ourselves.

### 1.6 Storage: R2, one prefix per user

**`Store` gets a second backend.** Today's is a folder; the hosted one is R2. The pipeline keeps calling `put`, `path`, `get_step` and `put_step`.
- **Layout.** Assets stay content-addressed, under the owner:
  - `u/<user>/assets/ab/<sha>.<ext>`
  - `u/<user>/derived/…`
  - `shared/…` for what belongs to no one: voice samples.
- **Why a prefix per user:**
  - Asking for another user's asset finds nothing.
  - Deleting an account is one prefix.
  - Lifecycle rules can act per prefix.
  - The cost is some duplicated bytes between users, which is negligible.
- **The worker keeps a local disk cache** of the objects it needs, because ffmpeg reads files. `path(asset)` downloads on a miss; `put` writes locally and uploads. Pictures get their 384 and 768 JPEGs made by the worker as they land. In hosted, the API never runs ffmpeg.
- **The step cache moves into Postgres in hosted:** a `steps` table keyed by (owner, key). The hosted store holds a database handle. Locally, step records stay JSON files, so a local library needs no migration of its cache. Either way, each user has a cache of their own: user B never gets user A's result for free, even for the same prompt.
- **Serving.** `/api/assets/{asset}` answers with a 302 to a presigned GET URL on R2's S3 endpoint.
  - R2 presigned URLs don't work on custom domains.
  - They support range requests, so films seek.
  - Egress is free.
  - Each URL's expiry is rounded to the hour, so it stays the same for an hour and the browser's cache still works. Existing `<img>` and `<video>` tags don't change.
  - A download adds `response-content-disposition` for the file name.
- **The client** is httpx with botocore used only to sign, not boto3's transport. That keeps storage behind `providers.transport()`, so fake mode serves a fake S3 (invariant 8). It's the same choice M2 made for fal uploads. The calls are few: PUT, GET, HEAD, DELETE, list and delete a prefix, presign.
- **What a story weighs, measured in the lab library:**
  - The finished film: 350–400 MB for 4 minutes at 1080p.
  - Its pictures: about 120 MB.
  - ffmpeg's intermediate clips: about 1 GB, most of it the 24 Mbit/s fitted shots.
- **Intermediate clips expire.** They cost nothing to make again, so ffmpeg's outputs go under a prefix with a 7-day lifecycle rule. A step whose file has gone is already a cache miss (`Store.get_step`), so it's remade at no charge.
- **Price.** $0.015/GB-month, free egress, and 10 GB free.
  - What stays is about 0.5 GB a story, so 1,000 users with 10 stories each is about 5 TB, roughly $75/month.
  - Moving old pictures and clips to Infrequent Access comes when the bill says so.

### 1.7 Workers and the queue

- **Two commands.**
  - `lanternist serve` in hosted runs the API only.
  - `lanternist worker` runs the queue's two lanes (renders, and the fast lane for samples) and claims jobs with `claim_job` (`DB_PLAN.md` §1.4, `FOR UPDATE SKIP LOCKED`).
- **Renders at once per user.** A claim skips users already running their plan's number of renders (1, or 2 on Pro). One person can't fill the workers.
- **Heartbeats.**
  - A worker stamps `jobs.heartbeat_at` on its running jobs every 10 s.
  - `requeue_stale()` puts back any running job whose heartbeat is older than 60 s. It replaces the start-up `requeue_running`, which would take a live worker's jobs.
  - The fal requests of a re-queued job are polled again, not paid again (M2's resume).
- **Cancel across processes.** The API sets `jobs.cancel_requested`. The worker sees it within one heartbeat and cancels as a user's cancel, which also cancels at fal.
- **Deploys.** SIGTERM makes a worker stop claiming and cancel its tasks as a shutdown, so they return to the queue. The next worker resumes them. Compose gives it `stop_grace_period: 60s`.
- **fal's concurrency is the real limit early on.**
  - New accounts run 2 requests at once. The limit rises by itself with paid invoices over 4 weeks, to 40; above 40, or for per-endpoint quotas, it's a sales conversation.
  - Queued requests don't count against it and simply wait at fal.
  - So nothing breaks, but a 30-picture board shares 2 slots with everyone at launch. Talk to fal before opening sign-up (Phase I).
- **Polling stays.** fal webhooks (ED25519-signed) would save polling calls, but polling is built, resumes, and works behind any network. Webhooks come when the request volume makes polling cost something.
- **ffmpeg runs on CPU:** `render.encoder = "libx264"` in hosted. Measure a 4-minute film's clips and mix on the chosen machine in Phase D, and size the worker from that.

### 1.8 Providers on the platform's keys

- **Keys come from the environment only in hosted.** The `PUT/DELETE /api/providers/{name}/key` routes don't exist there, and Settings shows no keys.
- **`keys.PLATFORM`** holds the hosted edition's own secrets, from the environment only: WorkOS now, Stripe and R2 later. `redact()` scrubs them with the model providers' keys (invariant 4).
- **OpenRouter:**
  - One runtime key per environment, created with a management key and given a monthly limit. It's a circuit breaker against runaway spend.
  - `user` = a hash of our user id, so a provider's abuse block lands on that user, not the whole account.
  - `data_collection: "deny"` as today.
  - The terms forbid reselling API access, not building a product on it. We sell films.
- **fal:**
  - `X-Fal-Store-IO: 0` on every request, so fal doesn't keep request and response bodies for 30 days.
  - Output lifetime drops from 24 h to 1 h: we copy outputs at once.
  - Voice reference payloads are deleted after use.
  - **Terms to settle with fal in writing before launch** (Phase I):
    - They forbid use "on a timesharing, service bureau, or similar arrangement", so ask that a film product sold on credits isn't one.
    - End users must be 18 or older, which our sign-up requires.
    - fal may use usage data to build its own models. The privacy policy must say so, unless fal's enterprise terms change that.
- **Registry in hosted:** only entries with `provider` in (`fal`, `openrouter`) and `commercial_use = true`. Local engines don't exist there. FLUX.2 [klein] on fal is commercial; its local weights aren't.

### 1.9 Safety

The blueprint put it plainly: open sign-up, any audience and cloning together are what most needs to be right before launch. At launch, cloning is out, and every other checkpoint is cheap:

| Checkpoint | How | Cost per story |
|---|---|---|
| The idea, before the writer | Llama Guard 4 on OpenRouter: the MLCommons categories, and it reads Spanish and Portuguese. Through our existing OpenRouter client, so no new provider. | ≈ $0.001 |
| The storyboard, before the board | The same model over the scenes, plus our own rules for the audience: a kids' story may have mild peril, nothing more | ≈ $0.001 |
| Every picture | fal's safety checker, on and never switched off. A black picture flagged `has_nsfw_concepts`, or a `content_policy_violation`, is a failed, uncharged step, named on the scene. Plus the picture check's question gains "does this suit a <audience> story?" | ≈ $0.02 (already paid by the check) |
| Clips | Frames sampled from each clip through the same check. Kling has no safety input, and not every video model filters its output. | ≈ $0.01 |

**Recorded.** Each verdict goes into `moderation_events`: the checkpoint, the verdict, the categories, the model and the job. That record serves appeals, the admin view, and the DSA's statement of reasons (§1.10).

**Refusals speak plainly.** "We can't make this scene: the picture showed more than a children's story allows. Edit its description and draw it again." They're never retried on their own; the user can edit or re-roll.

**Voices.** Hosted offers the presets only. `POST /api/voices` doesn't exist there. Cloning comes back only with a recorded consent read-aloud and a signed release (blueprint M4). The law is moving here:
- BIPA claims over voiceprints are in court (class actions filed in May 2026, ElevenLabs among those named);
- Tennessee's ELVIS Act reaches the tools themselves;
- the NO FAKES Act passed its Senate committee in June 2026.

**Abuse and spend:**
- The sign-up grant comes only after the email is verified: one per normalised email, a few per IP a day, with Turnstile and a throwaway-domain list guarding the grant rather than the sign-up form.
- Per-user rate limits on enqueue.
- `hosted.daily_spend_cap_usd`: before each remote batch, today's platform spend (a sum over `step_runs`) is checked. Over the cap, remote stages pause for everyone with a polite message, and admins get an alert. A stolen card can't turn into a fal bill.

**No photos of real people** at launch, children least of all.

### 1.10 Labelling, privacy and the law

**EU AI Act, Article 50.**
- **What it asks.** Since 2 Aug 2026, a provider of a generative system must mark its audio and video output as AI-made, machine-readably. An app built on other companies' models counts as a provider in its own right.
- **No grace period for us.** The Digital Omnibus's delay to 2 Dec 2026 covers only systems on the market before 2 Aug 2026.
- **The Code of Practice** (final, voluntary, 10 Jun 2026) asks for two layers: signed, timestamped metadata **and** an imperceptible watermark.
- **Our plan:**
  - **Metadata.** Every exported MP4 carries a C2PA manifest, signed with `c2pa-python` (0.37, pre-1.0; MP4 supported). The certificate comes through the C2PA conformance programme. SSL.com has offered one free Level 1 certificate for a year since May 2026. **Verify** any conformance fee.
  - **Watermark.** An imperceptible audio watermark on the narration. The blueprint already asked for one on every narration. Evaluate an open-source audio watermarker in Phase F.
  - **Visible label.** "Made with AI" in the player and in the film's end credits. Story films are fiction, so the lighter "doesn't hamper enjoyment" disclosure applies, but the marking duty has no artistic exception.

**Children.** Accounts are adults only (fal requires 18+ end users too), and children are the audience, not the users.
- COPPA covers data collected *from* children under 13, not data about them collected from adults.
- The FTC's signs of a child-directed service include animated characters. So any public player page gets no trackers or third-party cookies.
- GDPR's Article 8 stays out while accounts are adults-only.

**The DSA.** We host what users make, so the duties of a hosting service apply:
- a point of contact;
- an EU legal representative if the business isn't in the EU;
- terms that explain moderation;
- a notice form with receipt and decision (Art. 16);
- a statement of reasons for every restriction, saying whether it was automated (Art. 17).

Micro and small enterprises are exempt from the transparency reports. **Share links wait until after launch** (§4): whether an unlisted link is "dissemination to the public" is unsettled. Films are private, downloadable files at launch.

**Also before the public launch:**
- terms of service, a privacy policy and an acceptable use policy;
- DMCA agent registration ($6, renewed every 3 years);
- a 48-hour takedown path (the US TAKE IT DOWN Act);
- answering data requests within a month (GDPR Art. 12);
- account deletion that really deletes (definition of done 8).

A lawyer reviews this section before Phase I (#29). The business is in the US (decision 2), so the terms follow US law, and EU representatives are needed if we sell to EU consumers.

### 1.11 Deploy and operations

**Start small:**
- **Servers.** Docker Compose on one Hetzner server: Caddy (TLS), the API and one worker. A CX43 (8 shared vCPU, 16 GB) is €15.99/month after Hetzner's June price rise. A dedicated-CPU CCX13 for the worker (€42.99) comes when encodes need it. A second, smaller server (CX33, €8.49) is staging.
- **Postgres** on Neon's Launch plan, with scale-to-zero off: about $19/month, and 7 days of point-in-time restore we don't have to run. The worker connects directly, not through Neon's transaction pooler.
- **Also:** R2 (about $0 at first), WorkOS AuthKit (free; $99/month for our own domain on its pages and emails, once paying users justify it) and Sentry (free tier).
- **Total:** about $50–100 a month before the first customer.
- **The platforms, compared:**
  - Fly's shared CPUs throttle under long x264 encodes.
  - Railway caps HTTP requests, SSE included, at 15 minutes.
  - Render and Fly cost several times more for the same machine.

**Deploying:**
- CI builds one image per tag and pushes it to GitHub's registry.
- The deploy runs `lanternist db upgrade`, then `docker compose up -d`. In hosted, migrations run as that step, never at each process start: several processes migrating at once would race.
- The workers' grace period lets running jobs go back to the queue cleanly (§1.7).

**Watching it:**
- Sentry for the API, the workers and the web app.
- An uptime check.
- Alerts when:
  - a worker's heartbeat stops;
  - queue wait goes over 10 minutes;
  - jobs fail more than usual;
  - daily spend reaches 80% of the cap.
- A nightly job compares our `step_runs` spend with fal's usage API and OpenRouter's credits endpoint (both need admin or management keys). fal's usage API is aggregated by endpoint and time, not per request, so drift is caught per day, per endpoint.

**Backups.** Neon's point-in-time restore, plus a nightly `pg_dump` to R2. R2 holds the files; the stories themselves are in Postgres.

### 1.12 The web app

- **Sign-in.** AuthKit's hosted pages for signing in and up; our own sign-in page in front of them, and the account menu.
- **The header** shows the balance in credits.
- **The estimate box** speaks credits, and "Raise budget" becomes "Buy credits and carry on" when it's the balance that's short.
- **Model pickers** show locked models with the plan that unlocks them.
- **A Billing page:** the plan, the credit packs, the Customer Portal, and the history (ledger rows, one line per job, not per step).
- **What the hosted edition leaves out:** the key rows and the local-engine rows on the Settings page, the doctor's GPU rows, and voice uploads. `/api/options` says which edition it is, so the web app reads it rather than guessing.
- **The landing page** is a separate static site. The app itself stays a static React build served by FastAPI, as the blueprint decided.
- **Language.** The app's own words are English today. The stories are in any language, but the users we expect speak Spanish and Portuguese. Translating the interface is decision 7.

### 1.13 Tests

Invariant 8 extends to everything new. Fake mode runs the hosted edition with no keys:

- **Fake sign-in.** With fake engines on, `current_user` accepts a test header naming the user, so tests act as two people.
- **Fake Stripe** in `providers/fake.py`: it creates Checkout Sessions and posts signed webhook events, twice and out of order on request.
- **Fake S3** at the httpx transport, like the fake fal: it serves PUT, GET, HEAD, DELETE, list and presigned GETs.
- **Tenancy.** For every route with a `{story_id}`, `{job_id}` or `{asset}`, user B gets 404 on user A's id. The list of routes comes from `app.routes`, so a new route fails the test until it's covered.
- **The ledger:**
  - the balance is the sum of the rows;
  - a step captures once, however often its row is saved;
  - holds close at the job's end, done, failed or cancelled;
  - two jobs enqueued at once can't overdraw (on Postgres);
  - a moderated or failed step charges nothing;
  - a webhook delivered twice grants once.
- **Workers:** two workers, a killed worker's job picked up after its heartbeat stops, a cancel from the API reaching the other process, and a deploy during a fake fal video paying nothing twice.
- **Live and opt-in** (`pytest -m live`, with your permission, as today): one real Stripe test-mode checkout, one R2 round trip, one Llama Guard call.

### 1.14 Data

New and changed tables. Money is `_micros` `BigInteger`; spend history outlives the rows it belongs to (`SET NULL`); every constraint is named (`DB_PLAN.md` §1.3).

| Table | Change | Holds |
|---|---|---|
| `users` | **new** | `id`, `auth_subject` (WorkOS's user id, unique; `local` for the local user), `email`, `role` (`user`/`admin`), `created_at`, `deleted_at`. Phases E and H add `plan`, `plan_status`, `plan_renews_at` and `billing_customer_id` |
| `stories`, `jobs`, `step_runs` | add `owner_id` | `stories`, `jobs` → `users` `ON DELETE CASCADE`; `step_runs` → `SET NULL`, so spend outlives accounts |
| `jobs` | add `heartbeat_at`, `worker`, `cancel_requested` | Workers across processes (§1.7) |
| `settings` | add `owner_id`, part of the key | Settings per user |
| `sessions` | **new** | `id` (the hash of the cookie's token), `user_id`, `provider_session`, `created_at`, `expires_at` |
| `ledger` | **new** | `id`, `user_id` (`SET NULL`), `kind`, `amount_micros` (signed), `job_id`, `step_run_id` (unique when set), `external_id` (unique when set), `note`, `created_at` |
| `holds` | **new** | `job_id` (unique), `user_id`, `amount_micros`, `captured_micros`, `status` (`open`/`closed`), `created_at`, `closed_at` |
| `steps` | **new** (hosted) | `owner_id`, `key`, `record` (JSON), `created_at`; primary key (`owner_id`, `key`) |
| `webhook_events` | **new** | `provider`, `event_id` (unique together), `type`, `received_at`, `processed_at`, `error` |
| `moderation_events` | **new** | `id`, `owner_id`, `story_id`, `job_id`, `checkpoint`, `verdict`, `categories` (JSON), `model_id`, `created_at` |

The migration that adds `users` and the owners runs on local libraries too: it backfills `local`. It follows `/add-migration`, with a test on a copy of the real library, and the PR suggests a backup first.

### 1.15 New and changed files

```
src/lanternist/
  auth.py               # current_user: a WorkOS sign-in in hosted, the local user locally, a test header in fake mode
  ledger.py             # holds, captures, grants; available credit; CreditsShort
  plans.py  plans.toml  # plans, their limits, which models each unlocks
  billing.py            # Checkout Sessions, the webhook handlers (Stripe or Paddle), the portal link
  moderation.py         # the idea and storyboard checks, the audience question for pictures and clips
  provenance.py         # the C2PA manifest and the watermark on exported films
  store.py              # Store interface; the local folder and R2 (+ the steps table) behind it
  providers/s3.py       # httpx + botocore signing: put, get, head, delete, list, presign
  providers/workos.py   # the sign-in callback's calls to WorkOS
  providers/fake.py     # + fake WorkOS, fake Stripe, fake S3
  registry/writers.toml # the hosted writer list, with plans
  jobs.py               # claim, heartbeats, requeue_stale, cancel across processes, per-user limits
  pipeline.py           # _check_budget also holds and tops up credits; captures per step
  keys.py               # PLATFORM: + workos, stripe, r2
  config.py             # edition, [hosted], [database]
  cli.py                # worker, db upgrade, admin grant/suspend
  api/app.py            # user on every route; billing, webhooks, admin; edition-aware routes
  migrations/versions/  # in build order: 0004 accounts (users, sessions, owners), 0005 steps, 0006 the worker
                        # columns on jobs, 0007 ledger and holds, 0008 moderation_events, 0009 webhook_events
web/src/
  pages/Billing.tsx  components/SignIn.tsx  Balance.tsx
deploy/
  compose.yml  Caddyfile  Dockerfile
```

---

## 2. Phases

Each phase ends with something that runs end to end. Sizes assume one developer working with Claude Code, like M2's. **After Phase G there's a closed beta, on credits granted by hand**; payments follow, and the public launch comes last.

### Phase A: the database, ready for Postgres (≈2.5 days)

`DB_PLAN.md`: every query in `db.py`, Postgres beside SQLite, tests on both, and an atomic job claim.

**Exit:** its definition of done.

### Phase B: editions and accounts (≈3 days)

`ACCOUNTS_PLAN.md`, issue #15.

- [ ] `edition` and the `[hosted]` config section. `/api/options` says which edition it is.
- [ ] `users`, `owner_id` everywhere, settings per user. The migration backfills the local user and is tested on a copy of the real library.
- [ ] `auth.py`: WorkOS AuthKit sign-in and our own sessions, the local user, the fake-mode header. `current_user` on every route; every `Database` method scoped.
- [ ] Hosted leaves out the key routes, voice uploads and local engines. The registry is filtered to hosted-eligible models.
- [ ] Sign-in in the web app; Settings without keys in hosted.
- [ ] The cross-user test over `app.routes`.

**Exit:**
- [ ] Two users in fake hosted mode each write, board and render a story, and see only their own. Every cross-user request gets a 404.
- [ ] The local edition works exactly as before (the golden keys; `~/Lanternist` opens after its migration).

### Phase C: storage on R2 (≈3 days)

- [ ] The `Store` interface: the local folder, and R2 with its per-user prefixes, local disk cache and `steps` table.
- [ ] `providers/s3.py` (httpx + botocore signing) and the fake S3.
- [ ] Thumbnails made by the worker; presigned redirects with hour-stable URLs; downloads with a file name.
- [ ] Deleting a story deletes its database rows. Deleting an account deletes its prefix.

**Exit:**
- [ ] A full film in fake hosted mode with every file on the fake S3.
- [ ] One live R2 round trip (opt-in).
- [ ] The Board, the reel and the film play from presigned URLs.

### Phase D: workers (≈3 days)

- [ ] `lanternist worker`; `serve` without the runner in hosted.
- [ ] Heartbeats, `requeue_stale`, cancel across processes, renders at once per plan.
- [ ] SIGTERM hands running jobs back to the queue.
- [ ] libx264 in hosted: time a 4-minute film's clips and mix on a CX43, and write the number here.

**Exit:**
- [ ] Two workers, three users: fair turns.
- [ ] Killing a worker mid-video: another picks it up after a minute and pays nothing twice.
- [ ] A cancel from the web reaches the worker.

### Phase E: credits and plans (≈4 days)

Needs decisions 3 and 4, at least as placeholders.

- [ ] `ledger`, `holds`; `ledger.py`; the hold at enqueue with the user's row locked; top-ups before remote stages; `CreditsShort`; a capture per step in the transaction that closes its run; the release at the end.
- [ ] `markup` in the registry; retail pricing in the estimate.
- [ ] `plans.toml`, `plan` on registry entries and quality options, `registry/writers.toml`. The API refuses what the plan lacks; pickers show the plans.
- [ ] Balance, credits in the estimate box, "Buy credits and carry on" (Buy leads to Billing, empty until Phase H), and the history.
- [ ] `lanternist admin grant`, the sign-up grant, and the admin view of users, balances and today's spend.
- [ ] The estimate includes the picture checks and an allowance for their redraws. Otherwise holds come up short (§0).

**Exit:**
- [ ] A film in fake hosted mode: the hold, the captures and the release add up exactly to the change in balance.
- [ ] A moderated step charges nothing.
- [ ] Two renders started at once can't overdraw.
- [ ] A Free user can't pick Pro models, through the UI or the API.

### Phase F: safety (≈3 days)

- [ ] `moderation.py`: Llama Guard 4 over the idea and the storyboard, with the audience rules. Refusals in plain words.
- [ ] The picture check asks about the audience; clips are checked by sampled frames; `moderation_events`.
- [ ] fal's `X-Fal-Store-IO: 0`, 1-hour outputs, and payloads deleted after voice references.
- [ ] Rate limits, the daily spend cap and its pause, and grants only after a verified email, with Turnstile.
- [ ] `provenance.py`: the C2PA manifest on every exported MP4 (with a test certificate until the real one arrives), the audio watermark once the evaluation picks one, and the visible label in the player and the end credits.

**Exit:**
- [ ] A set of ideas meant to trip each category is refused, in all three languages.
- [ ] A set of ordinary bedtime ideas passes. The false-alarm rate goes into this plan, like the picture check's did.
- [ ] Every film verifies with `c2patool`.

### Phase G: deploy, and a closed beta (≈3 days)

- [ ] `deploy/`: Dockerfile, Compose, Caddy. Staging and production. CI builds and deploys on a tag; `lanternist db upgrade` runs first.
- [ ] Neon; R2 buckets and lifecycle rules (unfinished uploads, scratch); secrets.
- [ ] Sentry, the uptime check, the alerts in §1.11, the nightly spend comparison, and nightly `pg_dump`.
- [ ] Invite-only sign-up (AuthKit invitations, or its waitlist); credits granted by hand.

**Exit:**
- [ ] Ten invited people make films on staging and then production, with no help beyond an invite.
- [ ] Their films' actual costs are within ±15% of their estimates, as M2 promised and as holds need.

### Phase H: payments (≈3 days)

On Stripe Managed Payments (decision 2), once it's on for Monsoft's account (#31).

- [ ] `billing.py` on the chosen provider: packs, plans, the portal, webhooks through `webhook_events`, refunds and disputes.
- [ ] The Billing page. Fake Stripe (or Paddle) in `providers/fake.py`.

**Exit:**
- [ ] Items 5 and 8 of the definition of done in test mode.
- [ ] One live test-mode checkout (opt-in).

### Phase I: the public launch (≈3 days, plus the lawyer's time)

- [ ] The lawyer's review of §1.10. Terms, privacy policy and AUP. The DMCA agent. The DSA contact, notice form and statements of reasons. EU representatives if needed.
- [ ] fal's written answer on the service-bureau clause, and a raised concurrency limit.
- [ ] OpenRouter's capped runtime key; the real C2PA certificate.
- [ ] Account deletion (definition of done 8).
- [ ] The landing page; open sign-up.

**Exit:**
- [ ] Items 1–10 of the definition of done, on production.

**Total: about 28 working days**, plus the waits that aren't ours: the lawyer, fal, Stripe's eligibility review and the C2PA conformance programme. Start those during Phase B.

---

## 3. Risks

| Risk | Mitigation |
|---|---|
| Everything hosted depends on fal | Adapters are per capability, so a direct provider can slot in behind the same interface. Keep the registry's second-best model for each stage ready. |
| fal's 2 concurrent requests make launch-week films slow | Queued requests wait rather than fail. Talk to fal early; the limit rises by itself with spend, to 40. The estimate's time range already widens when items wait at fal. |
| fal's terms (service bureau), or its use of our usage data | Written confirmation before launch; enterprise terms if needed. The privacy policy says what fal may do. |
| A user sees another's story or film | One place for queries, `owner_id` in every method, 404 for not-yours, a test generated from the route table, per-user storage prefixes |
| Holds run short because the estimate leaves something out | Checks and redraws go into the estimate (Phase E). Top-ups before each stage. `CreditsShort` stops before spending, and the cache means carrying on wastes nothing. The Phase G exit measures the estimates. |
| We pay for what a user doesn't (failed steps, restarts, moderation) | M2's resume without paying twice, OpenRouter's reported cost of failures kept as ours, and the admin view of our unbilled spend |
| A stolen card or a script turns into a fal bill | Credits are prepaid, so nothing runs on credit. Grants only after a verified email, Turnstile, rate limits, the daily cap with its pause, and OpenRouter's capped key. |
| Children's content: a harmful picture reaches a child | Moderation at four checkpoints, fal's checkers always on, the audience question in the picture check, adults-only accounts, and no sharing at launch |
| EU AI Act marking, with no grace period | C2PA and a watermark before the public launch (Phase F), with a label on top. The lawyer checks it against the Code of Practice. |
| Voice-clone law (BIPA, ELVIS, NO FAKES) | No cloning in hosted at launch |
| Prices change under the plans (H3 doubles on 30 Sep) | Registry prices with `until` and `then`, the daily sync, markup per model, and the nightly comparison with what we were billed |
| A solo operator on call for a live service | One server, managed Postgres, alerts on the few things that matter, deploys that put jobs back in the queue. Status updates go on the landing page. |

---

## 4. Out of scope

- **Blueprint M6:** desktop apps, installers, and support for Windows, macOS, AMD and Apple Silicon. The local edition stays a Linux + NVIDIA development setup.
- **Voice cloning in hosted,** and per-character voices (blueprint M4).
- **Share links and a public gallery** (the DSA duties of an online platform). Photos of real people.
- **Teams and organisations,** gift credits, referral credits, coupons beyond what Stripe's portal offers, and an API for third parties.
- **Music,** aspect ratios (9:16 for social video), wind-down and pace controls. They're product features that fit between phases and matter to paying users; plan them separately.
- **fal webhooks** in place of polling, and Postgres LISTEN/NOTIFY in place of the SSE poll: later, when the volume asks for them.
- **A lighter copy of each film for phones.** A 4-minute film is 350–400 MB at today's bitrate, which is heavy on mobile data.
- **Moving local libraries into the hosted service.**

## 5. Decisions to confirm

1. **Open source.** Publish the local edition as the AGPL self-hosted app (the blueprint's plan), or keep the code closed and the local edition as our development setup only? *Recommended:* decide at launch; nothing before then depends on it.
2. **Where the business is registered.** *Decided 23 Sep 2026 (#24):* the US, as a product of Monsoft Solutions, with Stripe Managed Payments as merchant of record. It decided:
   - the merchant of record: Stripe Managed Payments if it's the US, Canada, the EU/EEA, the UK, Australia, Hong Kong, Japan or Singapore, else Paddle;
   - whether EU representatives are needed;
   - which law the terms follow.
3. **Plans and prices:** how many plans, what each costs and grants, what each unlocks, and the sign-up grant. §1.4 has a structure to react to.
4. **Credit value, markup and expiry.** *Recommended:*
   - 1 credit = $0.01;
   - +100% markup by default, set per model;
   - credits don't expire at launch.
5. **Hosting.** *Recommended:* one Hetzner server with Compose, Neon for Postgres, and R2 (§1.11).
6. **Sign-in.** *Decided 23 Sep 2026 (#23):* WorkOS AuthKit, behind `auth.py`, with email codes and Google and no passwords. The custom domain waits for paying users.
7. **The interface's language.** Translate the app into Spanish and Brazilian Portuguese before the public launch, or after? The Customer Portal and AuthKit's pages already speak both.
8. **The domain and the name.** The blueprint's advice stands: a trademark search, then register the domains on the same day.
9. **The beta.** How many people, whose (friends, parents' groups, a waiting list), and how many credits each.

---

## 6. Sources (read 22 Sep 2026)

- Stripe:
  - Checkout fulfilment: https://docs.stripe.com/checkout/fulfillment
  - Subscription webhooks: https://docs.stripe.com/billing/subscriptions/webhooks
  - Webhooks: https://docs.stripe.com/webhooks
  - Billing credits: https://docs.stripe.com/billing/subscriptions/usage-based/billing-credits
  - Managed Payments: https://docs.stripe.com/payments/managed-payments/eligibility
  - Pricing: https://stripe.com/pricing
- Paddle: https://www.paddle.com/pricing · https://developer.paddle.com/get-started/how-paddle-works/ai-companies/
- Polar: https://polar.sh/docs/merchant-of-record/fees
- Clerk:
  - Manual JWT verification: https://clerk.com/docs/guides/sessions/manual-jwt-verification
  - How Clerk works: https://clerk.com/docs/guides/how-clerk-works/overview
  - Pricing: https://clerk.com/pricing
  - Python SDK: https://github.com/clerk/clerk-sdk-python
- WorkOS (read 23 Sep 2026):
  - Pricing: https://workos.com/pricing
  - Custom domains: https://workos.com/docs/custom-domains
  - Authorize: https://workos.com/docs/reference/authkit/authentication/get-authorization-url
  - Authenticate with a code: https://workos.com/docs/reference/authkit/authentication/code
  - Sign-out: https://workos.com/docs/reference/authkit/logout
  - Webhooks: https://workos.com/docs/events/data-syncing/webhooks · events: https://workos.com/docs/events
- Cloudflare:
  - R2 pricing: https://developers.cloudflare.com/r2/pricing/
  - R2 presigned URLs: https://developers.cloudflare.com/r2/api/s3/presigned-urls/
  - Turnstile server-side validation: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
- Neon: https://neon.com/pricing · https://neon.com/docs/connect/connection-pooling
- Hetzner price change: https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- Fly CPU performance: https://fly.io/docs/machines/cpu-performance/
- Railway limits: https://docs.railway.com/networking/public-networking/specs-and-limits
- fal:
  - Concurrency limits: https://fal.ai/docs/documentation/model-apis/concurrency-limits
  - Webhooks: https://fal.ai/docs/model-apis/model-endpoints/webhooks
  - Common parameters: https://fal.ai/docs/documentation/model-apis/common-parameters
  - Usage API: https://fal.ai/docs/platform-apis/v1/models/usage
  - Terms: https://fal.ai/terms
  - Trust and safety: https://fal.ai/legal/trust-and-safety
- OpenRouter:
  - Management keys: https://openrouter.ai/docs/guides/overview/auth/management-api-keys
  - User tracking: https://openrouter.ai/docs/cookbook/administration/user-tracking
  - Terms: https://openrouter.ai/terms
  - Llama Guard 4: https://openrouter.ai/meta-llama/llama-guard-4-12b
- EU AI Act:
  - Article 50: https://artificialintelligenceact.eu/transparency-rules-article-50/
  - Digital Omnibus: https://eur-lex.europa.eu/eli/reg/2026/1744/oj/eng
  - Code of Practice: https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content
- C2PA: https://pypi.org/project/c2pa-python/ · https://opensource.contentauthenticity.org/docs/conformance/trust-lists/ · https://www.ssl.com/products/content-authenticity/content-credentials/c2pa/
- COPPA FAQ: https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions
- DSA: https://www.eu-digital-services-act.com/
- TAKE IT DOWN Act: https://www.ftc.gov/business-guidance/resources/complying-take-it-down-act
