# Campaign Manager — System Audit & Refactor Plan

> **Status:** Design locked as a **parallel "v2" build** (D14). §0.1 is the decision log; §12 is the build
> plan; §12.1 the write-safety choke-point; §12.2 logging; §5.1 the folder structure. No code changed yet.
> Branch `feature/campaign-automations-refactor`.
> **Owner:** Deepansh (reassigned in full 2026-07-25 — independent, no shared ownership).
> **Scope:** the "Campaign Manager" automation subsystem (budget scheduler, bid optimizer, on-demand
> tools). Fact-checked against the live codebase and the shared DB (read-only), 2026-07-25.

Read §1–§5 to understand the system, §6 for the problems, §0.1 + §7–§12 for the agreed plan.

---

## 0. Two conventions this refactor is built on

1. **Scraping / browser-automation runs on the VM only, through the scheduler.** Anything that launches
   Chromium or drives Blinkit is a VM job (Indian IP). Render never launches a browser.
2. **Render is for basic API hosting only** — serve JSON from the DB, accept writes to the DB, and
   _enqueue_ jobs. No Playwright, no Blinkit calls, no long-running work in the request path.

Most issues in §6 are direct violations of these two rules.

---

## 0.1 Decisions locked (this round)

These are settled unless we deliberately reopen them.

| #   | Decision                                                                                                                                                                                                                                                  | Rationale                                                                                                                                                                                                                                                          |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D1  | **Ephemeral browsers, not always-on.**                                                                                                                                                                                                                    | Preserves the subprocess failure-isolation the jobs system is built on; always-on scales _worse_ (N resident browsers = N GB), ephemeral+lanes caps peak RAM regardless of tenant count. Fewer runs (D7) solves the cold-start cost.                               |
| D2  | **One executor: the VM. Render is API-only.**                                                                                                                                                                                                             | Convention §0. Removes the US-IP block risk, the Render RAM/timeout problems, and the latent double-write.                                                                                                                                                         |
| D3  | **On-demand actions become enqueue→poll VM jobs** (set-budget, live-position, live-budget).                                                                                                                                                               | Gets Playwright off Render. A few seconds of added latency is acceptable (reliability > instantaneity — confirmed).                                                                                                                                                |
| D4  | **DB is the only source of truth; delete the JSON round-trip.**                                                                                                                                                                                           | Kills the global-file multi-tenant corruption bug (B1) and the dirty-working-tree problem (F2).                                                                                                                                                                    |
| D5  | **Re-auth = the main `cli auth blinkit` only.** Delete the campaign manager's own `reconnect_blinkit` (function + web card).                                                                                                                              | The scraper and the campaign manager **share the same `(tenant,"blinkit")` session**, so the existing auth already serves both. No bespoke auth code in the CM — it only _consumes_ the session. Auto-login (inbox/magic-link) supersedes even the CLI step later. |
| D6  | **Logs split:** slim structured history in DB (+ retention) for the UI; verbose narration to Cloud Logging; **delete all JSON log/state files.**                                                                                                          | The UI needs queryable per-tenant history (DB); the noisy play-by-play belongs in the jobs log stream. Keeps the DB small under Supabase's 500 MB quota.                                                                                                           |
| D7  | **Event-driven scheduling via a reconciler**, not blind polling.                                                                                                                                                                                          | Compile rules → `job_schedules`; budget fires at rule boundaries + a low-frequency safety poll; bid runs only inside active windows. Cuts ~384 launches/day to a few dozen.                                                                                        |
| D8  | **Separate CM automation out of `ads_service.py`** into the new **`campaign_manager/`** package (v2 — D14); the API layer is a thin enqueue/read wrapper.                                                                                                                        | `ads_service` currently conflates read-only analytics SQL with live Blinkit automation.                                                                                                                                                                            |
| D9  | **Campaign keyword/product cache → a new `cm_campaign_catalog` table** (not v1's `campaign_data_cache`).                                                                                                                                                                                                  | The VM→DB→UI cache pattern is right; a `cm_*` table keeps v2 fully isolated, and it's a _regenerable_ cache so the switch is near-free (re-sync, no data migration) — also drops the weak name. Populated by `cm.sync_campaign_data`; v1's `campaign_data_cache` dropped at cutover.                                                                                                           |
| D10 | **Tables → new `cm_*` tables for v2** (this **superseded** the earlier "evolve in place"; see the note below + D14). Deprecate-don't-delete the dead ones.                                                                                                  | See §4.1 (rewritten for D14). Parallel build → new tables give config-data isolation from v1's live rows.                                                                                                                                                          |
| D11 | **Multi-tenant is mandatory; multi-MP is kept structurally possible but not built.**                                                                                                                                                                      | Fix the global-file bug first (the real multi-tenant blocker). Only Blinkit has an ad-automation implementation.                                                                                                                                                   |
| D12 | **Refactor the plumbing, keep the engine — no from-scratch rewrite.**                                                                                                                                                                                     | The reverse-engineered Blinkit payloads, bid math, rule matching, and live-position scrape are validated against real Blinkit and expensive to re-derive.                                                                                                          |
| D13 | **Scale via _doing less per unit time_** (tier by keyword state, dedup scrapes, stagger tenants), not via concurrency (OOM) or a bigger VM alone.                                                                                                         | See §8.                                                                                                                                                                                                                                                            |
| D14 | **Build as "Campaign Manager v2" — a parallel new build**, not an in-place refactor. New package + new tables (`cm_*`) + new routes + new CLI group (`cm`) + new UI page + new `cm.*` job types, running alongside v1 until cutover.                      | No sandbox/staging exists; parallel build gives code + config-data isolation so v1 keeps running untouched while v2 is built and validated. Reuses the engine (D12). See §12.                                                                                      |
| D15 | **A single gated write choke-point (`writes.py`) — every Blinkit mutation goes through it.** Dry-run is the default; live requires arming; guardrails (bounds, clamps, rate limit, no-op skip, audit line) enforced there.                                | There is no sandbox and only real accounts — so "never blindly call Blinkit" must be _structurally_ enforced, not left to discipline. See §12.1.                                                                                                                   |
| D16 | **Structured, dry-run-aware logging** through loguru (never `print()`), flowing through the existing jobs → Cloud Logging pipeline. Verbose event stream to logs; slim history to DB.                                                                     | Deepansh monitors logs live during testing; must be Ops-Agent-ready with no new plumbing. See §12.2.                                                                                                                                                               |
| D17 | **MP-pluggable structure now; abstract interface later.** All Blinkit-specific code goes behind `marketplaces/blinkit/`; orchestration stays MP-agnostic. Do **not** design the `base.py` adapter interface until MP #2 (Zepto/Instamart) actually lands. | Separating the folder is cheap and right; abstracting from one example produces a leaky, Blinkit-shaped interface. Two real MPs define a good seam; one guesses. The bid _model_ itself may differ per MP — isolating now keeps that a contained change. See §5.1. |
| D18 | **Lanes: 2 browser lanes for the CM** — `cm_bid` (isolated, latency-critical) + `cm_ops` (budget/sync/on-demand); reconcile is a no-browser job. Scale by **slots**, not lanes.                                                                           | Bid is the control loop and must never starve; budget/sync are latency-tolerant and share. Lanes = isolation, slots = throughput/RAM. See §8.1.                                                                                                                    |

> **D10 update (superseded by D14):** because v2 is a _parallel_ build, it uses **new `cm_*` tables**
> (config-data isolation from v1's live rows), _not_ evolve-in-place. The earlier "evolve in place" applied
> to an in-place refactor, which we are no longer doing. Old v1 tables stay untouched until cutover, then are
> dropped (much later). The dead `ad_automation_*` tables are still deprecate-don't-delete.

**Still open (small):** whether there's **one real campaign to designate as the write guinea-pig** (else
write-path testing is no-op re-asserts only). See §13. _(Resolved since: Q2 → split `cm_bid_runtime` table;
reconcile → runner-owned `cm.reconcile` job, enqueue-on-edit, schedules written at edit time, unified one-shot
scheduler — §7.3.)_

---

## 1. What the Campaign Manager is (product view)

Two distinct things live under `ads`; conflating them causes confusion:

|             | **Ads Analytics** (`/ads`)                 | **Campaign Manager** (`/campaign-manager`)               |
| ----------- | ------------------------------------------ | -------------------------------------------------------- |
| Purpose     | Report on paid activity (spend, RoAS, SoV) | _Act on_ Blinkit — change budgets & bids automatically   |
| Data source | Scraped tables (`blinkit_ad_campaign*`)    | Live Blinkit API via a logged-in browser                 |
| Direction   | Read-only                                  | Read **and write** to Blinkit                            |
| Frontend    | `features/ads/`                            | `features/campaign-manager/`                             |
| Risk        | Low (just SQL)                             | High (writes money-affecting settings to a live account) |

This document is about the **Campaign Manager** (second column). The analytics half is healthy and out of
scope except that both are currently served by the same `ads_service.py` / `routes/ads.py` (which D8 splits).

Three capabilities: **Budget Scheduler** (thermostat — set daily budget by time-of-day/day-of-week rules),
**Bid Optimizer** (cruise control — adjust keyword CPM to hold a target search position), and **on-demand
tools** (set-budget now, live-position check, live-budget, cached keywords/products).

---

## 2. The four moving parts (mental model)

1. **Rules** — what the user wants (DB: `budget_schedules`+`budget_schedule_rules`, `bid_optimizer_rules`).
2. **Session** — a logged-in Blinkit identity (encrypted in `platform_sessions`, restored into a browser).
3. **Executor** — the thing that, on a timer, loads the session, launches Chromium, reads the rules, and
   applies changes. **This is where the mess is.**
4. **Logs** — what happened (DB history tables + legacy JSON).

---

## 3. How it works today — the full flow

### 3.1 Auth & session

- **Storage.** A Playwright `storage_state` (cookies + `localStorage` + Firebase IndexedDB) is Fernet-
  encrypted, one row per `(tenant_id, "blinkit")` in **`platform_sessions`** (`scraper/utils/session.py`).
  The **scraper and the campaign manager share this same row** (D5). Nothing on disk.
- **Restore order is critical** (`client.py::setup_with_state`): context with `storage_state` → inject
  Firebase IndexedDB via `add_init_script` **before** page JS → navigate. (Firebase v9+ keeps the refresh
  token in IndexedDB.)
- **Auth token.** API calls send a `firebase_user_token` header, grabbed three ways (intercept, localStorage,
  live SDK) and refreshed at call time in `_fetch`.
- **Expiry.** Session dies → redirect off `/dashboard` → "reconnect" error. Today reconnection is a manual
  magic-link paste; **D5 replaces this with the standard `cli auth blinkit`.** Auto-login is not built.

### 3.2 The Blinkit API surface

Authenticated calls to `https://brands.blinkit.com` via **in-page `page.evaluate(fetch)`** (Cloudflare
blocks httpx — a `direct_api.py` httpx attempt was reverted):

| Method | Path                                   | For                                                        |
| ------ | -------------------------------------- | ---------------------------------------------------------- |
| POST   | `/adservice/v1/advertisers/campaigns`  | list campaigns; read real `advertiser_id`                  |
| GET    | `/adservice/v1/campaigns/{id}`         | detail (budget, keywords, pids, pacing) + `min_cpm_config` |
| POST   | `/adservice/v1/campaigns/reports/{id}` | keyword report (24h position, impressions, cpm)            |
| PUT    | `/adservice/v3/campaigns`              | **the write** — budget and/or keyword bids                 |

Consumer side (`live_position.py`): a _separate_ `blinkit.com` scrape — set store via `?lat=&lon=`, search
`/s/?q=`, intercept `/v1/layout/search`, read position + `is_ad`. This gives a **real-time** position vs
the lagged 24h report. The `PUT /adservice/v3/campaigns` payload is reverse-engineered and finicky (resends
the whole campaign; special-cases `BANNER_LISTING`, `empty_pids`, no-product) — our most fragile point.

### 3.3 Budget Scheduler

`cli ads budget-scheduler` → `scheduler.py::_run_core`: load schedules (now from **DB**, commit `233e054`) →
for each, find the rule matching _now_ (IST) or fall back to `default_budget` → `client.update_campaign`.

### 3.4 Bid Optimizer

`cli ads bid-optimizer` → `bid_optimizer.py::run`: load active rules (today via a **JSON file** synced from
the DB — the round-trip D4 kills) → per campaign: current CPM from detail, products for matching, **real-time
position** from the consumer scrape (fallback: 24h report → position 50) → step CPM by distance
(≥4→₹100, ≥3→₹50, ≥1→₹25, else ₹12.5), clamp `[min,max]`, **10-min HOLD** before re-raising → apply via
`update_keyword_bids` → persist runtime (`last_cpm`/`last_position`/`last_bid_updated_at`).

### 3.5 On-demand tools

All currently run Playwright **in the Render process**: set-budget, live-position, live-budget, reconnect.
Campaign keywords/products are served from **`campaign_data_cache`** (populated by the `ads.sync_campaign_data`
VM job) — the one good VM→DB→UI pattern (D9).

### 3.6 Where things execute today (the split)

Periodic budget/bid now run **only on the VM** (verified: one `budget_scheduler_log` run per 5-min slot,
trailing its VM job by ~1 min — the earlier double-write is resolved by the 07-25 DB-read fixes). But
on-demand actions still launch Chromium **on Render**, and `run_scheduler_all_tenants` /
`run_bid_optimizer_all_tenants` keep a callable Render path alive (latent double-write). D2/D3 remove these.

### 3.7 Scheduling today

`job_schedules` id 24 → `ads.budget_scheduler` `*/5 * * * *`; id 25 → `ads.bid_optimizer` `2-59/15 * * * *`
(all day); `ads.sync_campaign_data` has **no schedule** (stale). Both poll blindly 24/7 (~384 launches/day,
mostly no-ops) — D7 fixes this.

---

## 4. Data model

**Live v1 tables** (in use today; **v2 replaces them with `cm_*`** — §4.1): `budget_schedules`,
`budget_schedule_rules`, `bid_optimizer_rules`, `budget_scheduler_log`, `bid_optimizer_log`,
`campaign_data_cache` (→ `cm_campaign_catalog`).
**Kept as-is:** `platform_sessions` (shared with the scrapers).
**Analytics/scraped:** `blinkit_ad_campaign(s|_daily|_detail)`, `blinkit_sponsored_sov`,
`blinkit_brand_collections`, `blinkit_visibility_plans`.
**Scheduling:** `jobs`, `job_schedules` (+ `Lane` enum with `budget_scheduler`/`bid_optimizer`/`sync_campaign_data`).

### 4.1 Table decision (D14 — supersedes the earlier D10)

v2 is a **parallel build**, so it uses **new `cm_*` tables**, not the v1 ones — giving config-data isolation
while v1 keeps running (D14). The v1 tables stay untouched until cutover, then are dropped (much later,
shared-DB caution).

- **New v2 tables** (`app/models/campaign_manager_v2.py`, each with a `platform` column for MP-readiness):
  `cm_budget_schedules`, `cm_budget_rules`, `cm_bid_rules` (config), **`cm_bid_runtime`** (1:1 runtime split —
  Q2 resolved), `cm_run_log` (slim history), **`cm_campaign_catalog`** (cached campaign keywords + products;
  built with the `cm.sync_campaign_data` job, ~V4).
- **`campaign_data_cache` → replaced by `cm_campaign_catalog`** (D9). It's a regenerable cache, so the switch is
  near-free (re-sync, no data migration); it completes v2's `cm_*` isolation and drops the weak name. v1's table
  is dropped at cutover (V6.4).
- **`cm_run_log`** is append-only → a **retention policy** (e.g. 90 days); verbose narration goes to Cloud
  Logging (D6), not the DB.
- **Old v1 tables** (`budget_schedules`, `budget_schedule_rules`, `bid_optimizer_rules`, `budget_scheduler_log`,
  `bid_optimizer_log`) — left running for v1 until cutover, dropped at **V6**.
- **`ad_automation_rules` (3 rows) + `ad_automation_actions` (90 rows) are DEAD** — an abandoned
  _performance-triggered_ automation ("if RoAS < X over N days → act", migration `9cba1aca0fa7`), referenced
  nowhere. **Deprecate, leave physically in place** (shared DB — never drop casually), drop much later. (Their
  _idea_ is a plausible future feature.)
- **Shared-DB discipline:** any new table cuts over reads _and_ writes together — never dual-write old + new;
  additive migrations, one head, announce before applying, freeze once applied.

---

## 5. Files & folders touched (full inventory)

**`ad_campaigns/` (domain logic — mostly KEEP per D12):** `client.py` (BlinkitClient, all API calls,
`update_campaign`/`update_keyword_bids`, `get_campaign_*`; `update_campaign_budget_via_ui` = legacy delete),
`bid_optimizer.py` (bid loop; JSON I/O to delete), `scheduler.py` (budget rule matching), `live_position.py`
(consumer scrape). **Delete:** `direct_api.py` (reverted httpx), `main.py` (broken — imports non-existent
`ad_campaigns.bid_scheduler`), `schedules.py` + the four JSON files.

**API & services:** `app/services/ads_service.py` (split per D8), `app/routes/ads.py`,
`app/models/campaign_manager.py`, `app/models/blinkit_marketing.py`, `app/models/job.py` (PlatformSession),
`app/schemas/ads.py`, `scraper/utils/session.py`, `scraper/platforms/blinkit/auth.py::_capture_session`,
`scraper/utils/browser.py`.

**Jobs/CLI:** `cli/commands/ads.py` (v1 — deleted at cutover); the new commands live in the new `cm` group
(`cli/commands/campaign_manager.py` — §5.1). `jobs/types.py` (add `cm.*` types), `app/core/config.py` (`LANE_SLOTS`).

**Frontend `features/campaign-manager/`:** `CampaignManagerPage.jsx`, `api.js`, `hooks.js`, `components/*`
(AddScheduleForm, EditScheduleForm, ScheduleList, SchedulerHistory, SetBudget, AddBidOptimizerForm,
BidOptimizerRuleList, BidOptimizerHistory, LivePositionCheck [commented], CampaignSelector,
ReconnectBlinkit [delete per D5]).

**Migrations:** `9cba1aca0fa7` (dead ad_automation), `b7c3d8e2f1a9` (daily_budget), `d8e2f1a4c3b7`+`b69eb97`
(campaign_data_cache), `e3b1f7a9c2d5` (ad lane enum), `2bb4d44b4cf7` (converge). ⚠️ Confirm `alembic heads`=1
before the next migration.

### 5.1 v2 folder structure (target — D14)

v2 follows the repo convention: a subsystem gets its own top-level package (like `jobs/`, `ad_campaigns/`),
with models/routes/schemas/CLI/job-registry/frontend in their standard homes. It runs fully in parallel with
v1 (new `cm.*` job types, `cm_*` tables, `/campaign-manager-v2` route, `cm` CLI group) — no collisions.

```
backend/
  campaign_manager/                 # NEW package = v2 domain logic (functions, not classes)
    __init__.py
    README.md                       # what this is + v1→v2 boundary + "engine reused, not forked"
    config.py                       # dry-run default, guardrail bounds, rate limits
    logs.py                         # structured logging setup + event helpers (§12.2)
    repo.py                         # tenant-scoped DB reads/writes for rules + history (NO JSON)
    reconciler.py                   # rules → job_schedules (the producer) — D7  [MP-AGNOSTIC]
    writes.py                       # ⭐ CHOKE-POINT POLICY: dry-run + guardrails; delegates apply to the adapter [MP-AGNOSTIC]
    budget.py                       # orchestration: match rules → target → writes.apply_budget() [MP-AGNOSTIC]
    bid.py                          # orchestration: decide → writes.apply_bid() [MP-AGNOSTIC]
    marketplaces/                   # ⭐ the MP seam (D17) — all MP-specific code lives here
      __init__.py                   #   registry: slug -> adapter
      base.py                       #   adapter interface — WRITE LATER, when MP #2 lands (not now)
      blinkit/
        __init__.py
        client.py                   #   engine reused from ad_campaigns (API + reverse-engineered payloads)
        positions.py                #   blinkit.com live-position scrape (tiered source — §8)
        adapter.py                  #   read_budget / apply_budget / read_position / read_bid / apply_bid

  app/models/campaign_manager_v2.py # NEW cm_* SQLModel tables (+ `platform` column; live here so Alembic autogens)
  app/routes/campaign_manager.py    # NEW thin routes: read DB + enqueue jobs (no Playwright)
  app/schemas/campaign_manager.py   # NEW request/response contracts
  app/services/ads_service.py       # v1 until cutover; the read-only ANALYTICS half stays here afterward

  cli/commands/campaign_manager.py  # NEW `cm` group: budget-scheduler / bid-optimizer / reconcile /
                                    #   set-budget / sync-campaign-data — all support --dry-run
  jobs/types.py                     # ADD cm.* job types → lanes cm_bid / cm_ops (§8.1)

frontend/src/features/
  campaign-manager-v2/              # NEW page (route /campaign-manager-v2) + api.js + hooks.js + components/
```

Boundary: **MP-agnostic orchestration** (reconciler, scheduling, `writes.py` _policy_, guardrails, logging,
rules storage) at the package root; **all MP-specific code** (client, payloads, positions, the read/apply
_mechanism_) under `marketplaces/<slug>/`. `writes.py` enforces policy and delegates the actual apply to the
adapter. The engine is **reused, not forked**; at cutover it moves fully under `marketplaces/blinkit/` and the
rest of `ad_campaigns/` is deleted.

---

## 6. Issues — the full list

🔴 critical · 🟠 high · 🟡 medium · ⚪ cleanup. Fix column references the decision that resolves it.

### Architecture

- 🔴 **A1 — Split VM/Render execution + latent double-write.** On-demand actions launch Chromium on Render
  (US IP); `*_all_tenants` keep a periodic Render path callable. → **D2/D3.**
- 🟠 **A2 — Playwright in Render's request path** (RAM, timeouts, blocked pool). → **D2/D3.**
- 🟠 **A3 — No in-repo scheduler for the Render path; opaque trigger.** → **D7** (one producer: `job_schedules`).

### Correctness & multi-tenancy

- 🔴 **B1 — Bid optimizer round-trips DB→JSON→DB through a single _global_ file** → concurrent tenants
  clobber → wrong bids. Latent at 1 tenant. → **D4.**
- 🟠 **B2 — Runtime state on the config row** (drives the file dance). → **D4** (write back via scoped UPDATE)
  + **Q2 resolved:** split into `cm_bid_runtime` (§4.1).
- 🟡 **B3 — `ADVERTISER_ID = 234` hardcoded** (Dobra's account). → **Fix now:** derive live per session and
  **fail loud** if the fetch fails — never fall back to another tenant's id (a silent wrong-account write is a
  real-money bug). **Multi-tenant hardening:** store a per-tenant *expected* `advertiser_id` and have
  `writes.py` **assert the session's advertiser_id == the tenant's expected** before any write (a wrong-session
  = wrong-account guardrail). Table/column deferrable to tenant #2; killing the hardcoded fallback is not.
- 🟡 **B4 — Legacy hardcoded `TENANT_ID` in `scheduler.py::run()`.** → delete the entrypoint.

### Reliability & observability

- 🟠 **C1 — "Success" ≠ success** (no-op / per-campaign failure still exits 0 → heartbeat happy). → define
  real success semantics; wire CM failures into the deadman/alert path.
- 🟡 **C2 — Duplicate, unbounded logging** (`_append_log` O(n²) JSON + DB). → **D6.**
- 🟡 **C3 — `print()` not loguru** in `bid_optimizer.py`/`live_position.py`. → use `logger`.
- 🟡 **C4 — `_fetch` swallows non-JSON as `{}`** (Cloudflare block reads as empty-OK). → distinguish/raise.

### Blinkit-integration fragility

_(Labelled `BF*` to avoid colliding with the `D*` decision numbers.)_

- 🟠 **BF1 — Reverse-engineered `PUT /adservice/v3/campaigns` payload.** Unavoidable (no public API) but
  should be **isolated, documented, golden-payload-tested**, with full request/response logging on failure.
- ⚪ **BF2 — `update_campaign_budget_via_ui`** (270-line brittle UI automation, only ref'd by broken `main.py`).
  → delete.

### Efficiency

- 🟠 **E1 — Blind 24/7 polling** (~384 launches/day, mostly no-ops). → **D7** + the scale model (§8).

### Dead / legacy

- ⚪ **F1 — Dead modules:** `direct_api.py`, `main.py` (broken import), `schedules.py`+`schedules.json`. → delete.
- ⚪ **F2 — Git-tracked runtime JSON state** (dirty tree, `git pull` refuses, `checkout .` restores stale
  bids). → **D4/D6** (delete the files).

### UI/UX

- 🟡 **G1** — UI narrates the split-brain ("every 5 min" vs "on VM"). 🟡 **G2** — fire-and-hope 35 s
  `setTimeout` feedback. 🟡 **G3** — no real automation health / "stop everything" / applied-value confirmation.
  → **§11.**

---

## 7. Target architecture (the agreed design)

### 7.1 One executor: the VM; Render is API-only (D2/D3)

Every Blinkit-touching action is a **VM job** — periodic automations _and_ on-demand actions (set-budget,
live-position, live-budget). Render endpoints only **read** DB rows and **enqueue** jobs; no Playwright
imports survive in `app/`. On-demand UX = **enqueue → poll**: `POST …/set-budget` inserts a job and returns
a job id; the UI polls job status + the resulting log row.

### 7.2 DB is the only source of truth (D4)

`bid_optimizer.run(rules, …)` receives rules explicitly (tenant-scoped); runtime written back with a scoped
`UPDATE`; the four JSON files and `_append_log`/`_save_rules`/`load_schedules` are deleted. Logs live only in
DB (slim) + Cloud Logging (verbose) per D6.

### 7.3 Event-driven scheduling — the reconciler (D7, refined 2026-07-26)

Rules are the source of truth; a **reconciler** compiles them into `job_schedules` rows and keeps them in
sync — idempotent via deterministic names (`auto:cm:budget:<tenant>:<mp>:<hhmm>`,
`auto:cm:bid:<tenant>:<mp>:<window>`): create missing, update changed, delete no-longer-wanted. Jobs stay
dumb ("apply what the rules say for now"); only _when_ they run changes.

**The reconciler is a VM job (`cm.reconcile`), runner-owned.** Every UI change — create / update / pause /
delete, budget _or_ bid — has the API **enqueue** a `cm.reconcile` job; the runner rewrites that tenant's
schedules. The API never mutates schedules itself (stays enqueue+read only, per §0). ~seconds of latency is
fine (the next fire is minutes/hours away).

**Schedules are written at edit time, not on the run day.** A rule that starts next Monday gets its schedule
row created the moment you save — it just stays **dormant until it fires**. The timing lives in the row:
- **Recurring window** → a `job_schedules` cron row (`0 13 * * *`). Future-start → set `next_run_at` to the
  start datetime so it stays dormant until then.
- **One-time action** (a `once` rule, or an expiry cleanup) → a **one-shot** `job_schedules` row: explicit
  `next_run_at`, no cron, fires once, then auto-disables.

**One scheduler for everything (unified — small jobs-system enhancement).** Add a `repeat` flag to
`job_schedules`: `repeat=true` → advance `next_run_at` via cron after firing (recurring); `repeat=false`
(one-shot) → **disable the row after it fires once.** So one-off and recurring are the _same_ row type, one
producer, one place to see/manage/monitor scheduled work — no second path via raw `jobs`. This is a **general
scheduler capability** (useful beyond the CM) that lives in the jobs system; the CM just uses it. (Two small
jobs-side tweaks: the producer's fire-then-disable branch, and the deadman monitor treating a pending one-shot
as overdue only once its `next_run_at` passes.)

- **Budget:** recurring boundary schedules (one per distinct transition time — one browser handles all
  campaigns changing then) **+ a low-frequency safety poll** (hourly; 30 min until auto-login) for drift/missed
  fires. **Expiry** (a rule's end date) → a one-shot cleanup job **pre-scheduled for that date at edit time**
  (reset to default, remove the recurring schedule).
- **Bid:** `*/15` bounded to each rule's active window, tiered by state (see §8).
- **Stop = an action:** pausing/removing an automation enqueues a final "reset to default / clear bids" job —
  the last-applied value must not persist.

Because activation and expiry are both encoded in the rows **at edit time**, the periodic reconcile is **no
longer functionally required** — it downgrades to an optional **weekly drift check** (re-assert correctness if
anything drifted out of sync). MVP can skip it.

### 7.4 Auth (D5)

Keep the DB session model. **Delete the CM's own reconnect**; re-auth via the shared `cli auth blinkit`
(a VM/SSH step). Auto-login (inbox reader) is the future that removes even that manual step.

### 7.5 Separation (D8)

Analytics stays in `ads_service` (read-only SQL). All automation orchestration moves into the new
**`campaign_manager/`** package (v2 — D14); the API layer becomes thin enqueue/read handlers.

### 7.6 CLI (both paths — matches the scrapers)

```
python -m cli cm budget-scheduler   --tenant <id>                        # apply budgets now (direct/dev; dry by default)
python -m cli cm bid-optimizer      --tenant <id>                        # one optimizer pass
python -m cli cm sync-campaign-data --tenant <id>                        # refresh cm_campaign_catalog
python -m cli cm set-budget         --tenant <id> campaign=<cid> budget=<n>
python -m cli cm reconcile          --tenant <id>                        # rules → job_schedules
python -m cli jobs run cm.<type> -t <id> [k=v …]                         # production path (queue+lanes)
```

Direct commands = dev/manual/debug; the scheduler drives the same commands via `jobs run`. Consistent with
`cli scrape …` vs `jobs run scrape.…`.

---

## 8. Scale model (multi-tenant × multi-MP) — D13

The naïve fear ("bidding can't wait, concurrency = OOM, bigger VM won't save us") overstates the cost.
Three reframes:

1. **Cost is browser-_time_, not browser-_count_ per keyword.** One browser already handles _all_ of a
   tenant's keywords in one run (grouped by campaign, session reused). RAM is bounded per _run_, not per keyword.
2. **The cadence is forgiving.** The 10-min HOLD makes this a ~15-min control loop, not real-time.
3. **Work ∝ _actively-chasing_ keywords, not _total_.** Most keywords sit at target and need only cheap
   monitoring, not a fresh real-time scrape.

**Levers, in order of leverage:**

1. **Tier by state.** Actively-chasing → fresh live-position scrape (~15 min). At-target → cheap 24h **report
   API** or the latest **public-scrape DB snapshot**, checked hourly. (The competition scraper already searches
   keywords at locations — the bid optimizer may reuse that data for monitoring instead of its own scrape.)
2. **Dedup scrapes by `(keyword, location)`** across campaigns and tenants — one scrape serves all
   (same trick as the public scraper's `DISTINCT (lat,lon)`).
3. **Stagger tenants across the window** (A at :00, B at :02 …) — same total work, **peak concurrency stays
   1–2 browsers → RAM bounded → no OOM.** This is the direct answer to the OOM fear.
4. **Reuse one browser per run** (already) + read products from `cm_campaign_catalog` instead of a live fetch.

**Worked example — 10 tenants × 3 campaigns × 5 keywords = 150 targets:**

- Naïve (all fresh every 15 min): 150 × ~15 s = 2,250 s per 900 s window → ~3 concurrent browsers → RAM pressure.
- Tiered + staggered: ~20% actively chasing = ~30 × 15 s = **450 s < 900 s → one browser per lane**, staggered,
  ~1 GB peak. The other 120 monitored hourly / from the report API / DB snapshot — nearly free.

**Bigger VM?** Buys a few more concurrent slots (linear) but is _not_ the primary lever. Two harder walls sit
beyond RAM: **the IP** (all tenants on one VM IP → the same Cloudflare/ASN wall the public scraper hits →
**proxies**, ~same scaling point) and **Blinkit's account rate-limits**. So: algorithmic levers first, bigger
VM for a few slots, proxies for the IP wall, more boxes last.

**Multi-MP:** each marketplace is an independent scrape + API + session; it multiplies per-tenant work but MPs
run in **separate lanes/boxes**. Only Blinkit has an ad-automation implementation — build a second MP when it
has an ad API, not before. The session model already keys on `(tenant, platform)`.

**Honest ceiling:** with tiering + staggering + dedup on the current 8 GB box, ~**10–15 Blinkit tenants**
before needing more slots; then bigger VM, then proxies, then more boxes. It degrades gracefully (queues
lengthen, at-target monitoring slows) rather than OOMing.

### 8.1 Lanes (D18)

Model: lanes run **in parallel**, **sequential within**; a job's lane comes from its type; `LANE_SLOTS` sets
concurrency inside a lane. **Concurrent browsers = Σ slots across browser lanes = the RAM bill** (~1 GB each).
**Lanes = isolation; slots = throughput/RAM** — two different knobs.

- **`cm_bid`** — the bid optimizer (latency-critical control loop). Isolated so nothing starves it. 1 slot now.
- **`cm_ops`** — budget apply + `sync_campaign_data` + on-demand set-budget (all latency-tolerant). Share one
  lane → combined RAM capped at one browser. 1 slot.
- **`reconcile`** — **no browser, no dedicated lane**: a `cm.reconcile` VM job, enqueued by the API on rule
  edits (runner-owned — §7.3), plus an optional weekly drift-check in the existing `interactive` lane.

So **2 CM browser lanes** (down from the current 3 — consolidate budget+sync; reuse the existing `Lane` enum
values, no lane migration). RAM on the 8 GB box: scrapers `batch`(1)+`dashboard`(1) + `cm_bid`(1)+`cm_ops`(1)
= 4 browsers ≈ 4 GB + ~1 GB OS/runner ≈ **5 GB**, comfortable. Scale by raising **slots** (throughput), and
by **per-MP bid lanes** (`cm_bid_blinkit`, `cm_bid_zepto`) only when MPs multiply — not now.

### 8.2 Worked example — a busy Sunday, 3 tenants × 3 MPs

Peak demand is what you size for, because it **breaks the tiering assumption**: high demand → volatile
positions → far more keywords _actively chasing_ (say ~50% vs ~20% on a normal day). Assumptions: 3 tenants
× 3 MPs = **9 independent (tenant, MP) bid runs / 15-min cycle**; ~4 campaigns × 5 keywords = 20 targets/pair;
fresh live scrape ~15 s, cheap at-target check ~2 s, session restore ~5 s; 1 slot = 900 s of browser-time/cycle;
~1 GB/browser. _(Only Blinkit is built today — this is the future MP state.)_

|                   | Active/pair | Browser-time/pair        | × 9 pairs   | Slots needed               |
| ----------------- | ----------- | ------------------------ | ----------- | -------------------------- |
| Normal day (~20%) | 4           | 4×15 + 16×2 + 5 ≈ 97 s   | 873 s       | **1 slot** (fits 900 s)    |
| **Sunday (~50%)** | 10          | 10×15 + 10×2 + 5 ≈ 175 s | **1,575 s** | **2 slots** (need 1,800 s) |

So the same fleet needs **`cm_bid` at 2 slots** on Sunday — more compute means **more slots on the one bid
lane, not more lanes.** Budget stays cheap (9 pairs × ~25 s ≈ 225 s, fires hourly/at boundaries → 1 `cm_ops`
slot). **Sunday RAM:** 2 (bid) + 1 (ops) + 1 (OS) ≈ 4 GB; + a dashboard scrape ≈ 5 GB — **fits the 8 GB box.**
Operational rule this exposes: **don't run a heavy public/batch scrape (2–4 GB) during the Sunday ad peak** —
stagger it off-peak, or you flirt with OOM. Load ≈ `(tenants × MPs) × active-work/pair`; at ~175 s/pair you fit
~5 pairs/slot, so 9 pairs → 2 slots; ~15 pairs → a 16 GB box + proxies (the one-IP wall, same as the scraper).

---

## 9. Operational timeline (how a day runs)

Example: budget rule "1pm–8pm → ₹2000, else ₹500"; bid rule "keyword K, target position 5, window 9am–9pm".

**Day level**

| Time           | Fires                  | Effect                                                                               |
| -------------- | ---------------------- | ------------------------------------------------------------------------------------ |
| (at edit time) | `cm.reconcile` on save | rules → `job_schedules`: budget @13:00 & @20:00, hourly safety poll, bid `*/15 9-20` (dormant until they fire) |
| 09:00 → 20:45  | bid job (every 15 min) | position check + (maybe) bid update, within window                                   |
| 13:00          | budget boundary        | rule matches → set ₹2000                                                             |
| 14:00, 15:00 … | budget safety poll     | re-assert ₹2000 (idempotent; catches drift/missed fires)                             |
| 20:00          | budget boundary        | rule ends → back to ₹500                                                             |
| 21:00          | (bid window closes)    | no bid jobs until 9am                                                                |

**Inside one bid run** (seconds, not minutes)

| t+      | step                                                         |
| ------- | ------------------------------------------------------------ |
| 0 s     | runner launches Chromium, restores session                   |
| ~3 s    | Firebase token captured                                      |
| ~5–25 s | live-position scrape of blinkit.com for keyword K            |
| ~25 s   | position determined (e.g. pos 9 vs target 5)                 |
| ~27 s   | `PUT /adservice/v3/campaigns` raises the bid; DB log written |
| ~30 s   | browser torn down, job success                               |

The "wait 10 min then adjust again" (HOLD) is _between_ runs — run N sets the bid, run N+1/N+2 observe whether
position moved and adjust. Within a run it's seconds.

---

## 10. Rebuild vs refactor — decided: **refactor the plumbing, keep the engine** (D12)

Preserve `client.py`'s API methods, the bid math, `scheduler.py`'s rule matching, and `live_position.py` —
validated against real Blinkit, expensive to re-derive. Rebuild around them: one VM executor, DB-only,
reconciler scheduling, clean CLI, no Render Playwright, no JSON, no dead code. A contained ~1–2 week phased
refactor, not a multi-month rewrite, and far lower-risk.

---

## 11. UI/UX rework

Current UI is thin and leaks infra ("Auto-runs every 5 min"/"on VM"). Redo it **after** the backend contract
is settled. Target:

- **Automation status panel** per capability: On/Off, last run + result, next run, last error — from
  `job_schedules` + the log tables. No infra jargon.
- **Real action feedback** (enqueue→poll spinner + success/error toast, not a blind 35 s `setTimeout`).
- **Timeline schedule builder** — visualize the day (which window sets which budget, where default applies).
- **"Stop automation" that resets** (confirm: "budget returns to ₹X") — enqueues the reset job.
- **Bid transparency** — current vs target position, current vs min/max bid, recent actions inline per rule.
- **Connection health** — session freshness + a one-click path to re-auth.
- Consistent with `docs/ui-rules.md` / `docs/frontend-architecture.md`.

---

## 12. Build plan — Campaign Manager v2 (parallel build, D14)

v2 is built alongside the running v1. v1 keeps applying budgets/bids for the live tenant the whole time;
v2 stays **dry-run / test-tenant** until a deliberate, reversible cutover. **Iron rule: never let v1 and v2
both write to Blinkit for the same tenant.**

| Phase                   | What                                                                                                                                                                          | Blinkit risk      |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| **V0 — Scaffold**       | `campaign_manager/` package; `cm_*` tables (migration); `logs.py`; **`writes.py` choke-point with dry-run default + guardrails** (§12.1). Nothing runs live.                  | none              |
| **V1 — Budget v2**      | budget scheduler reads `cm_` rules → target → `writes.apply_budget()` (dry). Test: test tenant, then live tenant **dry-run** (real reads, no writes).                         | reads only        |
| **V2 — Bid v2**         | bid optimizer, DB-only (no JSON), tiered positions (§8), via the choke-point (dry).                                                                                           | reads only        |
| **V3 — Reconciler**     | `cm.reconcile` → `job_schedules` (deterministic names; budget boundaries + safety poll; bid windows; stop=reset). Testable with **zero Blinkit** (just writes schedule rows). | none              |
| **V4 — On-demand + UI** | `cm.*` job types for set-budget etc. (enqueue→poll); new API routes; new `/campaign-manager-v2` page.                                                                         | dry until armed   |
| **V5 — Cutover**        | migrate live tenant rules v1→v2 tables; enable v2 schedules; **disable v1 (id 24/25)**; switch UI route. Attended, off-peak. Reversible (re-enable v1).                       | first real writes |
| **V6 — Contract**       | delete v1 code + page; move the engine into `campaign_manager/`; drop v1 tables (much later); deprecate `ad_automation_*`. Auto-login later.                                  | —                 |

Deploying v2 to the VM (merge → `main`) can happen while it's still **dormant** (schedules disabled / dry) —
deployment ≠ activation. No DB write or schema change without showing the exact command + confirmation.

### 12.1 The gated write choke-point (D15) — "never blindly call Blinkit"

Since there is no sandbox and only real accounts, this is enforced _structurally_, not by discipline:

- **One function mutates Blinkit.** Every `PUT /adservice/v3/campaigns` (budget or bid) goes through
  `writes.apply_budget()` / `writes.apply_bid()`. Reads may be anywhere; **writes exist in exactly one place.**
- **Dry-run is the default; live must be armed.** The choke-point refuses to PUT unless explicitly given
  `--live`/`apply=True`. Fail-safe. The whole build runs dry by default.
- **Guardrails, enforced at the choke-point even in live mode:**
    - **Bounds** — reject a budget of 0 / absurd values / outside the rule's declared range. A bug computing
      `budget=0` is _rejected_, not sent.
    - **Bid clamps** — re-enforce `[min_bid, max_bid]` here (defense in depth).
    - **Rate/sanity limit** — refuse to hit the same campaign more than N times in a short window (what would
      have caught the every-minute-cron incident).
    - **No-op skip** — if computed value == current value, **don't call Blinkit at all.**
    - **Audit line** — log old→new _before_ the call (§12.2), and a DB history row after.
- **Attended first live runs** at cutover (V5), off-peak.
- **Write-path testing with no sandbox:** primarily **no-op re-asserts** (set current value to itself — the
  PUT executes, nothing changes), plus optionally **one designated low-stakes real campaign** as the guinea-pig
  (small change, immediately reverted, attended). _(Open item — is there such a campaign? §13.)_

### 12.2 Logging (D16)

Reuses the existing jobs → Cloud Logging pipeline (v2 runs as VM jobs; stdout → `logs/jobs/<date>/<lane>/
cm.<type>__<id>.log` → shipped by the current `foresight_<lane>` receivers). Locally, logs stream to the
terminal. No new plumbing; optionally add a `foresight_campaign_manager` receiver later.

- **loguru, never `print()`** (fixes C3), via `from app.utils.logger import logger`, with **structured fields**
  bound per event (`tenant`, `campaign_id`, `keyword`, `action`, `old`, `new`, `dry_run`, `reason`, `run_id`) —
  human-readable now, filterable in Cloud Logging (serialize) later.
- **Every line carries `dry_run`**, with a `[DRY-RUN]` prefix in dry mode — zero ambiguity about what was real.
- **Event vocabulary per run:** `run.start` → `session.ok|expired` → per item `decision` (state, rule matched,
  computed target, verdict apply/skip/hold/no-op + reason) → around each mutation `write.intent` →
  `write.guardrail` (pass/fail) → `write.result` (Blinkit response) → `run.summary` (N processed, M applied /
  would-apply, K skipped, errors).
- **Levels → severity:** INFO normal · **WARNING** skips/holds/guardrail-trips/no-ops · **ERROR** failures +
  rejected writes. `severity>=WARNING` surfaces everything alert-worthy.
- **Two-tier (D6):** verbose event stream → logs/Cloud Logging; **slim structured history** (timestamp,
  campaign, action, old→new, success) → `cm_run_log` DB table for the UI. `writes.py` emits both, so UI history
  and ops logs never diverge.

### 12.3 Safe testing & cutover (no sandbox reality)

- **Isolation v2 gives:** code (new files) + config/log data (`cm_*` tables, test tenant). **What it does NOT
  isolate:** the Blinkit account + session (one real account, shared) — so the choke-point + dry-run are the
  real safety, not v1/v2 separation.
- **Local:** only **direct commands** (`python -m cli cm budget-scheduler --tenant <test> --dry-run`).
  ⚠️ **Never `cli runner start` locally** — it would claim the VM's real jobs and scrape from your home IP.
- **VM:** keep the production runner on `main` untouched; use a **second checkout** of the branch for manual
  dry-run commands (real Mumbai IP + env) without touching the production runner.
- **Two kinds of test:** logic/plumbing/reconciler → test tenant, **no Blinkit needed**; Blinkit integration →
  live tenant session in **dry-run** (reads) + no-op re-asserts (writes).
- **Cutover = flip which `job_schedules` are enabled** — instantly reversible; v1 code never leaves until V6.

---

## 13. Open questions (small — the rest are resolved in §0.1)

1. **Write guinea-pig campaign** — one low-stakes real campaign for write-path tests, or no-op re-asserts only
   (needed by V5, not before).

**Resolved this round:** latency acceptable (D3); multi-tenant mandatory (D11); always-on rejected (D1);
reconnect consolidated (D5); logs split (D6); cache → new `cm_campaign_catalog` (D9); refactor-not-rewrite (D12); scale via
tiering/staggering (D13); MP-pluggable structure (D17); lanes (D18); advertiser_id per-tenant (B3 — kill the
hardcoded `234` now, add the session-matches-account guardrail with multi-tenant hardening).

**Q2 RESOLVED (2026-07-26): SPLIT bid runtime into its own table** (`cm_bid_runtime`, 1:1 with
`cm_bid_rules`, FK ON DELETE CASCADE, holds `last_cpm`/`last_position`/`last_bid_updated_at`, updated in place
— bounded, one row per rule). Greenfield → zero migration cost now; resolves the config/runtime-mixing smell (B2).

**Reconcile/scheduling RESOLVED (2026-07-26):** `cm.reconcile` is a **runner-owned VM job**; the API only
**enqueues** it on any rule change (create/update/pause/delete). Schedules are written **at edit time** (dormant
until they fire, timing in the row). **Unified scheduler:** a `repeat` flag on `job_schedules` — recurring
(cron, re-arm) vs one-shot (`repeat=false`, explicit `next_run_at`, fire-once-then-disable) — so one-time and
recurring share one system. Expiry = a pre-scheduled one-shot cleanup job. The periodic reconcile downgrades to
an optional weekly drift check. `repeat`/one-shot is a small, general **jobs-system** enhancement (§7.3).

> **CLAUDE.md is stale** — still calls the campaign manager "off-limits, coworker-owned". Update when this lands.

---

_Fact-check basis (2026-07-25):_ full read of `ad_campaigns/` (all modules), `app/services/ads_service.py`,
`app/routes/ads.py`, `app/schemas/ads.py`, `app/models/campaign_manager.py`, `cli/commands/ads.py`,
`jobs/types.py`, `scraper/utils/session.py`, and the `features/campaign-manager/` frontend; plus read-only
queries against the shared DB (job history, log cadence, table inventory + row counts, session freshness).
