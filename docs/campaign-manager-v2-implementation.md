# Campaign Manager v2 — Implementation Plan

> Companion to [campaign-manager-refactor.md](campaign-manager-refactor.md) (the _why/what_). This is the
> ordered _how_ — a work breakdown you execute and check off. Branch `feature/campaign-automations-refactor`.
>
> **Prime directives (from the design doc):**
>
> - v1 keeps running for the live tenant until an explicit, reversible **cutover (V5)**. Never let v1 and v2
>   both write to Blinkit for the same tenant.
> - **Every Blinkit mutation goes through `writes.py`**, which is **dry-run by default** and guardrailed.
> - **No Playwright in `app/`** — the API only reads the DB and enqueues jobs.
> - Any **DB migration or shared-DB write** is shown as an exact command and **confirmed before running**.

---

## How to read this

Tasks are grouped by phase (V0–V6). Each task has a checkbox, the file(s) it touches, and — where relevant —
a ⚠️ flag for anything needing confirmation (migrations, first live writes). Each phase ends with a **Gate**
(what must be true to move on) and a **Verify** (how you prove it, safely).

**Dependency map** (what can run in parallel):

```
V0 scaffold ──┬──► V1 budget (dry) ──┐
              ├──► V2 bid (dry) ──────┼──► V4 API + UI ──► V5 cutover ──► V6 contract
              └──► V3 reconciler ─────┘        ▲
                   (Blinkit-independent)        └── V1+V2+V3 must be proven in dry-run first
```

V1, V2, V3 are largely independent once V0 exists (V3 needs no Blinkit at all). V4 needs V1–V3. V5 needs V4.

**Effort feel:** V0 small, V1/V2 medium, V3 medium, V4 large (UI), V5 small-but-careful, V6 small. Iterative —
ship and test each phase on the VM before the next.

---

## Prerequisites (before V0)

**None of these block starting V0.**

- [x] **Alembic** (2026-07-26): heads = 1 **and** DB pointer both at `e3b1f7a9c2d5` — clean. (Stamped past a
      stale-pointer drift where the ad-lane-enum migration had been applied out-of-band.) `--autogenerate`
      works; V0.7's `cm_*` migration chains off `e3b1f7a9c2d5`.
- [ ] **Testing approach** (no test tenant needed — see below): logic tests (reconciler, rule-matching,
      `writes.py` guardrails) run as **pytest with fixtures + fabricated tenant UUIDs**, not the shared DB;
      DB-integration via **transaction-rollback** or test rows under Dobra's id in the (empty-until-cutover)
      `cm_*` tables; **real-Blinkit reads use the live tenant (Dobra) in dry-run** (V1.6 / V2.6).
- [ ] **Write guinea-pig campaign** from the client — one low-stakes real campaign for the V5 write-path
      tests (Deepansh requesting). Not needed until V5; until then write-tests fall back to no-op re-asserts.
- [ ] Second checkout of the branch on the VM for manual dry-run testing (leave the production runner on `main`).

---

## V0 — Scaffold (zero Blinkit risk)

Goal: the skeleton exists, a dry-run command runs end-to-end and does nothing.

> **Status — BUILT 2026-07-27** (code complete + verified: 6/6 guardrail tests pass, all imports clean, `cm`
> CLI group + `cm.*` job types wired). **Pending:** V0.7 migration **apply** (generated + hand-trimmed as
> `aef972735d57`, awaiting confirmation) and the gate run; not committed to git yet. **Deviations from the tasks
> below** (all in the backlog): **own lanes** `cm_bid`/`cm_ops` added instead of reusing v1's (supersedes V0.9);
> **B3** advertiser_id fix **deferred** (V0.5 → V1.3); guardrail tests are **standalone** assert-based (no pytest
> dependency added).

- [ ] **V0.1** Create `campaign_manager/` package with stub modules (`config.py`, `logs.py`, `repo.py`,
      `writes.py`, `budget.py`, `bid.py`, `reconciler.py`, `marketplaces/__init__.py`, `marketplaces/blinkit/`).
      Functions-not-classes, module-level.
- [ ] **V0.2** `config.py` — settings: `CM_DRY_RUN_DEFAULT=True`, guardrail bounds (min/max budget, max
      writes/window), rate-limit window. Read from env with safe defaults (no new required `.env` keys).
- [ ] **V0.3** `logs.py` — loguru-based structured helpers: `log_run_start/decision/write_intent/guardrail/
write_result/run_summary`, each binding `tenant/campaign_id/keyword/action/old/new/dry_run/reason/run_id`.
      `[DRY-RUN]` prefix + `dry_run` field on every line. (§12.2)
- [ ] **V0.4** `writes.py` — the choke-point _policy_: `apply_budget()`/`apply_bid()` with dry-run default,
      guardrails (bounds, clamp, rate-limit, **no-op skip**, audit log), and delegation to the MP adapter.
      In V0 the adapter apply can be a stub; **live path exists but is never armed.** _(Multi-tenant hardening,
      tenant #2: assert the session's `advertiser_id` == the tenant's expected before any write — B3.)_
- [ ] **V0.5** `marketplaces/blinkit/adapter.py` — implement `read_budget/apply_budget/read_position/
read_bid/apply_bid` by **reusing** `ad_campaigns.client` + `ad_campaigns.live_position` (import, don't copy).
      **Derive `advertiser_id` live per session and fail loud if the fetch fails — drop the hardcoded `234`
      fallback** (B3; falling back to another tenant's account id is a real-money bug).
- [ ] **V0.6** `app/models/campaign_manager_v2.py` — `cm_budget_schedules`, `cm_budget_rules`, `cm_bid_rules`
      (config only), `cm_bid_runtime` (1:1 with `cm_bid_rules`, FK ON DELETE CASCADE — holds `last_cpm`/
      `last_position`/`last_bid_updated_at`; Q2), `cm_run_log` (slim history). Each rule/schedule table has a
      `platform` column. Register so Alembic sees them.
- [ ] **V0.7** ⚠️ **Migration** for the `cm_*` tables — autogenerate, review, show the exact `alembic upgrade`
      command, **confirm before applying.** Re-check single head after.
- [ ] **V0.8** `cli/commands/campaign_manager.py` — new `cm` typer group with `budget-scheduler`,
      `bid-optimizer`, `reconcile`, `set-budget`, `sync-campaign-data`; **all default to `--dry-run`**, live
      needs `--live`. Wire into `cli/main.py`.
- [ ] **V0.9** `jobs/types.py` — add `cm.*` job types mapped to lanes `cm_bid` / `cm_ops` (reuse existing
      `Lane` enum values; consolidate budget+sync into `cm_ops`).
- [ ] **V0.10** Unit tests for `writes.py` guardrails (pure logic, no Blinkit): bounds rejection, clamp, no-op
      skip, rate-limit trip. High value, zero risk.

**Gate:** `python -m cli cm budget-scheduler --tenant <test> --dry-run` runs, logs `run.start`/`run.summary`,
touches no Blinkit, writes no rows (empty rules). Guardrail unit tests pass. `alembic heads` = 1.
**Verify:** run it locally (direct command, not the runner). Read the log stream.

---

## V1 — Budget scheduler v2 (reads only)

Goal: correct budget decisions end-to-end, dry-run, for the live tenant.

> **Status — DONE 2026-07-27.** Rule-matching ported to `budget.py` (`target_for_now` / `_matches_rule`, pure)
> + full `run()` wiring (load schedules → session → per campaign: target → read current → `writes.apply_budget`
> dry → `cm_run_log`). **15/15 unit tests pass** (9 budget-rule + 6 guardrail). **V1.5/V1.6 validated end-to-end:**
> seeded a temp schedule (campaign 574687 "Tech Test", `default_budget=999`), ran the dry-run → **read the real
> budget ₹201 from Blinkit** → logged `would set 201→999`, guardrail PASS, `would-apply (not sent)`, **zero
> writes**; temp data cleaned up. Fixed a `get_adapter` import bug (relied on the submodule being pre-imported —
> masked by test ordering, caught by the real run).

- [ ] **V1.1** `repo.py` — read `cm_budget_schedules` + rules (tenant + platform scoped); write `cm_run_log`.
- [ ] **V1.2** `budget.py` — port the rule-matching (reuse `ad_campaigns.scheduler` logic) → compute the target
      budget for _now_ (IST) or `default_budget` → call `writes.apply_budget()`.
- [ ] **V1.3** `blinkit/adapter.py` — `read_budget` (campaign detail → `campaign_budget`), `apply_budget`
      (`update_campaign`).
- [ ] **V1.4** `writes.apply_budget` — bounds + **no-op skip** (if target == current, skip the call); dry-run
      logs "would set ₹X → ₹Y".
- [ ] **V1.5** Seed a `cm_budget_schedule` for the **test tenant** (via CLI or reviewed SQL) and dry-run it.
- [ ] **V1.6** Dry-run for the **live tenant** — real reads (current budgets), zero writes. Compare decisions
      to expectations.

**Gate:** dry-run produces the correct target-budget decision per campaign + "would-apply" logs for the live
tenant, with **zero writes**. **Verify:** log stream + `cm_run_log` history rows (marked dry_run).

---

## V2 — Bid optimizer v2 (reads only)

Goal: correct bid decisions, DB-only (no JSON), tiered positions, dry-run.

- [x] **V2.1** ✅ **DONE** `repo.py` — `get_bid_rules` (rule + runtime) + **`write_bid_runtime`** (Postgres upsert
      on `rule_id`; only the provided fields update, so a HOLD/dry-run pass writes `last_position` without nulling
      `last_cpm`); `write_run_log` reused. No JSON anywhere.
- [~] **V2.2** ⚠️ **PARTIAL (always-live; tiering deferred by decision)** `blinkit/positions.py` — live scrape +
      ported product matching (`match_position`: pid → name-token → brand fallback; sponsored-only, else skip).
      **Tiered source (report-API / DB-snapshot for at-target keywords) + `(keyword,location)` dedup deferred** to a
      scale-optimization backlog item — MVP scrapes every keyword live.
- [x] **V2.3** ✅ **DONE** `bid.py` — ported loop: `_dynamic_step` (₹100/50/25/12.5), `compute_bid` (raise / lower /
      target / **10-min HOLD**), `_in_window`; new CPM → `writes.apply_bid`; runtime persisted (`last_position`
      always; `last_cpm`/`last_bid_updated_at` only on a real applied write).
- [x] **V2.4** ✅ **DONE** `blinkit/adapter.py` — `read_bids` (bulk), `read_products`, `resolve_position` (wraps
      `positions.py`), plus the pre-existing `read_position` / `read_bid` / `apply_bid`.
- [x] **V2.5** ✅ **DONE (pre-built in V0)** `writes.apply_bid` — clamp `[min,max]`, no-op skip, rate-limit.
- [ ] **V2.6** ⏳ **PENDING (needs real data)** Dry-run for the live tenant — real position reads, zero writes.
      Requires a `cm_bid_rule` pointing at a **real advertised keyword + store lat/lon** for Dobra (it does an
      actual consumer scrape). Awaiting a keyword+location from the user (mirrors V1.6 against Tech Test).

**Tests:** pure suite `tests/test_bid_logic.py` — **18/18** (step tiers, raise/lower/target/HOLD incl.
improved / post-window / never-changed, `_in_window`, and `match_position` pid/name/organic/not-found/empty).
**Gate:** bid decisions + would-apply logs correct in dry-run; runtime persists to **DB, not JSON** — pure side
proven; V2.6 live-read smoke pending real data.

---

## V3 — Reconciler + unified scheduling (zero Blinkit)

Goal: rules → `job_schedules` (recurring + one-shot), written at edit time, idempotent; fully testable
without Blinkit.

- [x] **V3.0** ✅ **DONE (code; migration pending confirm) — Jobs-system enhancement: one-shot schedules.** Added a
      `repeat` flag to `job_schedules` (default `True`; `cron` now nullable). The producer **fires-then-disables**
      when `repeat=False` (and keeps a duplicate-blocked one-shot armed to retry rather than lose its single run);
      a malformed one-shot with no `next_run_at` self-retires. The deadman monitor skips a pending one-shot until
      its `next_run_at` passes, then windows on a flat misfire-grace slack (never calls `_cron_period` on a null
      cron). CLI: `schedules add --at "YYYY-MM-DD HH:MM"` creates a one-shot (mutually exclusive with `--cron`);
      `list`/`show` render `once`/one-shot safely; `update --cron` converts a one-shot back to recurring;
      enable/disable preserves a one-shot's fire time. **Files:** `app/models/job.py`, `jobs/scheduler.py`,
      `jobs/monitor.py`, `cli/commands/schedules.py`, migration `b1d7e4a92f30`. Additive — existing recurring
      schedules unchanged. **Migration `b1d7e4a92f30` written, NOT yet applied (awaiting go-ahead).** Lives in the
      **jobs system**, not `campaign_manager/` — a general capability the CM consumes.
- [x] **V3.1** ✅ **DONE** `reconciler.py` — reads a tenant's budget schedules + bid rules → `desired_schedules(...)`
      (pure, unit-testable). Emits: one recurring `cm.budget_scheduler` cron per distinct **budget boundary**
      (rule start/end time, tenant-wide union); an hourly **safety poll**; **`once`** budget rules → apply+revert
      **one-shots**; **expiry** (recurring rule end_date) → a reset-to-default one-shot the morning after;
      **bid windows** → `*/15`-within-window `cm.bid_optimizer` crons (merged across active rules). Deterministic
      names `auto:cm:<kind>:<tenant>:<mp>:<rest>`. The dumb budget job reverts to default at an end boundary, so
      no separate revert schedule is needed.
- [x] **V3.2** ✅ **DONE** Idempotent `_apply`: matches managed rows by prefix **and platform** (`_is_managed`),
      create missing / update changed (`_differs` — never diffs a recurring row's drifting `next_run_at`) / delete
      no-longer-wanted. Re-run with no rule change → zero writes. `reconcile --dry-run` (default) previews the diff
      without writing `job_schedules`; `--live` writes it.
- [~] **V3.3** ⚠️ **PARTIAL** — **expiry** one-shots (reset-to-default after end_date) and time-window reverts
      (via the end-boundary fire) are done. **Deletion/pause `stop=reset`** — resetting a campaign's *live* Blinkit
      budget when its whole schedule is deleted — is **deferred to V4** (the API knows `default_budget` at delete
      time and enqueues the reset before reconcile forgets the row). Safe today because every scheduled job runs
      **dry-run** until cutover. Bid `stop=reset` (clear bids) deferred with the live bid path.
- [x] **V3.4** ✅ **DONE (job side)** `cm.reconcile` is a VM job (lane `interactive`, [jobs/types.py](../backend/jobs/types.py)),
      dry-run by default → **enqueue it with `live=true`** to actually write schedules. The **API enqueue-after-CRUD**
      is V4 (rules CRUD lives there). The _optional_ weekly drift-check schedule is skipped for MVP (activation +
      expiry are encoded at edit time, so periodic reconcile isn't functionally required — §7.3).
- [x] **V3.5** ✅ **DONE (2026-07-29)** Tests, no Blinkit. **Pure suite** `tests/test_reconciler.py` — **13/13**
      (boundaries + dedup, `once` on/off, past-skip, expiry, bid window + merge, `_is_managed` scoping, and
      idempotency incl. `next_run_at` drift not churning). **DB integration** (scratchpad `test_reconciler_db.py`,
      self-cleaning) — seeded a real tenant, reconcile-live → **9 correct `auto:cm:*` rows**; re-run → **0/0/0**;
      edit 20:00→22:00 → **1 created + 1 deleted**; cleanup → **0 residue**. All green.

**Files (V3.1–V3.4):** [reconciler.py](../backend/campaign_manager/reconciler.py) (the compile), `logs.py`
(`reconcile_change`). No Blinkit, no browser — pure DB against `job_schedules`.

**Gate:** reconcile yields correct, idempotent `job_schedules` (recurring + one-shot) for representative rule
sets, incl. edits/pauses/removals/expiry; one-shot rows fire once then disable. **Verify:** unit/integration
tests against the test tenant; inspect `job_schedules`.

---

## V4 — On-demand actions + API + UI

Goal: enqueue→poll actions; new API surface; new UI page. Still dry by default.

- [x] **V4.1** ✅ **DONE** Real `cm.set_budget` orchestration (`campaign_manager/set_budget.py`) — single-campaign
      guardrailed budget set (session → arm_live → read → choke-point), reused by the UI action AND budget Reset.
      CLI stub replaced. Job type already registered (lane `cm_ops`).
- [x] **V4.2** ✅ **DONE (backend)** `app/routes/campaign_manager.py` — **19 route entries** under
      `/clients/{client_id}/campaign-manager`: budget schedules/rules CRUD, bid rules CRUD, **D19 buttons**
      (budget `/reset`; bid `/pause` `/resume` `/stop`), on-demand `/set-budget` + `/run/{budget-scheduler,bid-optimizer}`
      (enqueue→poll), `/jobs/{id}` poll, `/history`, `/advertiser` GET/PUT. Every mutation reconciles-after
      (`enqueue cm.reconcile live=true`, dup-guarded). Ownership-checked. **No Playwright** — reads/writes DB +
      enqueues only. Registered in `app/router.py`.
- [x] **V4.3** ✅ **DONE** `app/schemas/campaign_manager.py` — Pydantic v2 contracts (budget/bid In/Out, SetBudgetIn,
      AdvertiserIn/Out, EnqueuedOut, CmJobOut, RunLogOut).
- [x] **D19 state field** ✅ **DONE** `state` (active/paused/stopped) on cm_budget_schedules + cm_bid_rules
      (**migration `e5c9b2d7a418`, awaiting apply**); reconciler + budget.run + bid.run all key off `state`
      (active→emit/run; paused→bid frozen/no cron; stopped→nothing). Tests updated, all green.
- [ ] **Status enrichment (deferred)** — list endpoints return `state` but not last-run/next-run; UI derives
      last-run from `/history`. Add next-run (from job_schedules) + last-error to a status endpoint when the UI needs it.
- [x] **V4.4** ✅ **DONE** Frontend `features/campaign-manager-v2/` (route `/campaign-manager-v2`): `api.js` (all
      endpoints), `hooks.js` (queries + mutations w/ cache-invalidation + **`useJob` enqueue→poll**), `CampaignManagerV2Page`
      + components — `BudgetSchedulesCard` (schedules + rules + Reset/delete), `BidRulesCard` (+ D19 Pause/Resume/Stop),
      `TimingFields` (recurring/once + days + overnight, shared, `timingPayload` remaps end→stop), `QuickActionsCard`
      (set-budget + run engines, **`JobStatus` real spinner→success/error, not a blind setTimeout**), `HistoryCard`
      (cm_run_log, dry-run tagged), `AdvertiserCard` (set/show B3 account). State badges throughout. Backend gained
      `city`/`location_id` on `BidRuleIn` + service resolves via `repo.resolve_store` (for the form's city convenience).
      **Build ✓ (vite, 563 modules), oxlint ✓.** Deferred status enrichment (next-run/last-error on cards) still open.
- [x] **V4.5** ✅ **DONE** Nav + route added alongside v1 ("Campaign Manager v2" → `/campaign-manager-v2`); v1 kept.
- [x] **V4.6** ✅ **DONE (2026-07-30)** **End-user UI redesign** — the V4.4 card set was reshaped from an
      engineer's console into a task-first page (client feedback: "make it from the end user's perspective").
      - **Layout:** a left **launcher** (two tiles → in-place `AutomateBudgetForm` / `AutomateBidForm` composers)
        + `SetBudgetNowCard`; a right **`ScheduledPane`** listing every budget + bid automation with inline
        controls; `HistoryCard` full-width below. `AdvertiserCard` + the "Run engine" buttons were **removed**
        from the UI (advertiser is CLI-only setup; runs are scheduler-driven). Superseded components deleted:
        `BudgetSchedulesCard`, `BidRulesCard`, `AddBudgetScheduleForm`, `AddBidRuleForm`, `QuickActionsCard`,
        `AdvertiserCard`.
      - **`CampaignPicker`** — pick campaigns by **name** (searchable, name + #id), backed by the ads
        `/campaigns` endpoint; bid form suggests the campaign's existing keywords. History shows campaign name + id.
      - **Budget composer** shows timing inline (no toggle) — campaign + everyday budget + one scheduled window
        (budget + `TimingFields`) in a single request (backend's inline `rule`). `TimingFields` rebuilt: segmented
        recurring/once, aligned From/Until with a smart overnight/all-day hint, day pills, `start → end` range.
      - **`ScheduledPane` fixes:** mutations are now **optimistic** (delete/pause/resume/stop/reset apply
        instantly, roll back on error, invalidate on settle — fixes "list only updates on full refresh");
        uniform footer actions; **two-step delete confirm** (guards the mid-run delete edge); sticky + scrollable.
      - **Build ✓ (vite), oxlint ✓.**
- [x] **V4.7** ✅ **DONE (2026-07-30)** **Local integration testing (dry) proven** for budget + bid via the UI
      loop, using a new **`cli runner start --only-cm`** mode (serves only `cm_ops`/`cm_bid`/`interactive` lanes
      and fires only `cm.*` schedules — safe against the shared DB while the VM is off; see jobs-runbook). Full
      loop verified: UI edit → `cm.reconcile` → `job_schedules` → producer → engine (dry) → `cm_run_log`/History;
      the reconciler correctly retires expired schedules on runner restart. Budget also proven **live** via
      direct CLI (`cm set-budget --live`, ₹205 → Dobra via advertiser 19802). ⚠️ **Migration incident fixed:**
      `cm_bid`/`cm_ops` were missing from the PG `lane` enum (aef972735d57 was *stamped* during a multi-author
      merge, so its `ALTER TYPE` never ran on the shared DB) → corrective idempotent migration **`f2a7c4e1d9b3`**
      (mirrors e3b1f7a9c2d5 for the ad lanes).
- [x] **V4.8** ✅ **DONE (2026-07-30)** **v1 disabled + v2 made self-contained** (early cutover-prep, not the
      live-arming V5). Deepansh now owns the whole system, so v1 (`ad_campaigns/`) is being retired.
      - **v1 disabled so nothing auto-runs it:** VM `job_schedules` **24** (`ads.budget_scheduler`) + **25**
        (`ads.bid_optimizer`) set `enabled=false` (reversible) → the producer never fires them. The **6
        Playwright-invoking routes** in `app/routes/ads.py` (`/budget-schedules/run`, `/bid-optimizer/run`,
        `/live-position`, `/campaigns/{id}/live-budget`, `/campaigns/{id}/set-budget`, `/reconnect-blinkit`) were
        **removed** (+ their now-dead imports) → **the API has no endpoint that spawns Chromium** (fixes the
        "Render runs Playwright" risk). Kept all ads **DB reads** (analytics dashboard + the v2 `CampaignPicker`).
      - **v2 self-contained:** `ad_campaigns/client.py` + `live_position.py` **vendored** into
        `campaign_manager/marketplaces/blinkit/` (their deps are `scraper.utils` + playwright only — no
        `ad_campaigns`); `adapter.py` + `positions.py` repointed to the local copies. **`grep ad_campaigns
        campaign_manager/` = clean**, `app.main` imports OK. `ad_campaigns/` stays on disk as inert stale code.
      - **`sync_campaign_data` is NOT used by v2** — the engines read campaign keywords/products/CPMs **live**
        (`adapter.read_bids`/`read_products` → `client.get_campaign_detail`). `CampaignDataCache` (written only by
        the v1 `ads.sync_campaign_data` job) is read only by the dashboard's cached keyword/product routes, which
        the bid form's keyword *suggestions* piggyback on (degrades gracefully if stale). `cm.sync_campaign_data`
        is an **unimplemented stub** — revisit only if v2 ever wants its own cached campaign catalogue.

**Gate:** the v2 page can CRUD rules, trigger dry-run actions, and show status/history; every action reads DB +
enqueues jobs; **no Playwright import in `app/`.** **Verify:** click through on the test tenant; watch jobs +
logs; confirm `grep -r playwright app/` is clean.

---

## V5 — Cutover (first real writes — attended)

Goal: switch the live tenant to v2, reversibly.

- [ ] **V5.1** Pre-cutover checklist: V1–V4 proven in dry-run for the live tenant; guardrail tests green;
      **no-op re-assert write test passes** (a real PUT that sets current→current — proves the write path,
      changes nothing); optional guinea-pig-campaign test if one was designated.
- [ ] **V5.2** ⚠️ **Migrate live tenant rules v1→v2 tables** (small data — reviewed script, exact command,
      confirmed). Verify parity (same campaigns/budgets/bid targets).
- [ ] **V5.3** `cli cm reconcile` for the live tenant → creates v2 schedules (leave **disabled**).
- [ ] **V5.4** ⚠️ **The switch (attended, off-peak):** arm `--live` for this tenant; **enable** v2 schedules;
      **disable** v1 schedules (`job_schedules` id 24 + 25). One tenant only.
- [ ] **V5.5** Watch the first several cycles: logs, `cm_run_log`, and the **actual Blinkit state** (did the
      budget/bid land as intended?). **Rollback** = disable v2 schedules, re-enable v1 — v1 code never left.

**Gate:** v2 applies real budgets/bids correctly for the live tenant across several cycles; v1 disabled; stable.
**Verify:** cross-check a couple of real changes against the Blinkit dashboard.

---

## V6 — Contract (remove v1)

Goal: only v2 remains.

- [ ] **V6.1** Delete v1 code: `ads_service` automation functions + `_playwright_executor`, the automation
      routes, `ad_campaigns/` orchestration (bid_optimizer/scheduler JSON paths), `main.py`, `direct_api.py`,
      `schedules.py`, `update_campaign_budget_via_ui`, `reconnect_blinkit`, the four JSON files.
- [ ] **V6.2** Move the engine (`client.py`, `live_position.py`) into `campaign_manager/marketplaces/blinkit/`;
      update imports.
- [ ] **V6.3** Delete the v1 frontend page; point nav at v2 (optionally rename route to `/campaign-manager`).
- [ ] **V6.4** ⚠️ **Drop v1 tables** (much later, once certain, confirmed): `budget_schedules`,
      `budget_schedule_rules`, `budget_scheduler_log`, `bid_optimizer_rules`, `bid_optimizer_log`,
      `campaign_data_cache` (superseded by `cm_campaign_catalog`); and the dead
      `ad_automation_rules`/`ad_automation_actions`. (Shared DB — never casually.)
- [ ] **V6.5** Slim `cm_run_log` retention (e.g. 90-day prune job); verbose stays in Cloud Logging.
- [ ] **V6.6** Update `CLAUDE.md` (remove "campaign manager off-limits / coworker-owned"), refresh docs.

**Gate:** only v2 exists; `grep -r ad_campaigns app/` and `grep -r playwright app/` are clean; docs current.

---

## Cross-cutting (do alongside, not a phase)

- [ ] **Golden-payload test for the Blinkit `PUT`** (BF1) — a fixture of the exact working payload + a smoke test,
      so a Blinkit-frontend change that breaks the payload is caught early. Log full request/response on failure.
- [ ] **Alert policy** — `log_id("foresight_...") AND severity>=WARNING/ERROR` → email (closes the long-open
      loop where the heartbeat shouted into a void). Ties into D16 levels.
- [ ] **`cm.sync_campaign_data` schedule** — daily, so `cm_campaign_catalog` stays fresh.
- [ ] **Auto-login** (later) — inbox reader for the magic link; loosens the budget safety-poll interval. Post-V6.

---

## Deferred & cleanup backlog

> A running list of things we've **consciously put off** — cleanups, deletions, hardening — to do once the
> relevant phase lands or the system is proven. **Convention: whenever we defer something mid-build, add it
> here** (with where it came from + when it unblocks), so nothing gets lost. Tick items as they're done.

**The big v1-removal cleanup is phase V6** (delete v1 code, move the engine, drop v1 tables + `ad_automation_*`,
retention, update `CLAUDE.md`). See V6 — not re-listed here. Below are the *loose* deferrals that don't sit in
a numbered task.

### Hardening — do when it becomes relevant (first live writes / multi-tenant)

- [ ] **B3 — kill the hardcoded `ADVERTISER_ID = 234`** in `ad_campaigns/client.py` (derive live per session +
      **fail loud**, no cross-account fallback). *Deferred from V0.5* — it's the shared v1 engine and isn't
      exercised in dry-run; do it as a deliberate, tested change in **V1.3** (first live-write work). ⚠️ must be
      done before any live write.
- [x] **B3 guardrail — no-hardcoded live writes** ✅ **DONE (2026-07-29, option B)** — `adapter.resolve_advertiser`
      derives the advertiser from Blinkit with **no hardcoded fallback** (raises if absent). `writes.arm_live` gates
      every live run (in `budget.run`/`bid.run` after session-load): it ALWAYS derives-or-refuses and logs
      `live.armed` (advertiser + "CONFIRM this is the intended account" when unverified); if the optional
      `CM_EXPECTED_ADVERTISER_ID` env is set it ALSO asserts a match. Dry-run unaffected. `cm advertiser -t <id>`
      prints the derived id (read-only preflight). The coworker's `client.py` `234` fallback is untouched
      (off-limits) but can no longer be silently used.
- [x] **B3 (production) — per-tenant advertiser in the DB** ✅ **DONE (2026-07-29)** — `cm_platform_accounts`
      `(tenant_id, platform, advertiser_id)` (migration `d8a3f16b5e94`), set via `cm set-advertiser`. A live run
      fetches it (`repo.get_advertiser`), refuses if unset, and **injects it onto the client** (`adapter.set_advertiser`
      → `client.cm_advertiser_id`) so the write **sends the stored id**. ⚠️ **Root cause found via the live test:
      the hardcoded `234` was the STALE pre-split Dobra account; the real one is `19802` (captured from a dashboard
      PUT). Blinkit doesn't expose the advertiser in any read API, so it must be stored.** The coworker's
      `update_campaign`/`update_keyword_bids` gained an optional `advertiser_id` override (backward-compatible; their
      default path untouched) so our writes carry the right account without a monkeypatch. Env var removed. Test
      `test_budget_write_sends_stored_advertiser` proves the write carries the stored id.
- [ ] **Coworker's stale `ADVERTISER_ID=234`** — flag to the coworker: their live writes to Dobra also send 234
      (the dead account) since the split. Our path is fixed (explicit override); theirs needs the constant updated or
      derivation fixed. *Coordinate — not ours to silently change.*
- [ ] **Per-tenant guardrail bounds** (min/max budget, rate limits) — clients have different budget scales;
      global defaults in `config.py` for now. *When tenant #2 with a different scale lands.*
- [ ] **Arming UX** — `live` is currently a per-job param (`live=true` → `--live`). Decide the real arming
      mechanism for the UI/scheduler (per-schedule param vs. per-tenant flag) at **V4/V5**.

### Control model — Pause/Resume/Stop/Reset (D19, locked 2026-07-28 — see design §7.3.1)

Budget = **Reset** (→default, per campaign); Bidding = **Pause / Resume / Stop** (per keyword rule); bid Stop
**freezes** the bid (no value write), budget Reset **writes default**; the asymmetry is safe because the budget
cap backstops a frozen bid. No bid baseline restore (`baseline_cpm` dropped). Concrete build tasks:

- [ ] **`state` field** (`active`/`paused`/`stopped`) on `cm_bid_rules` (all three) + `cm_budget_schedules`
      (active/stopped) — model + migration. Reconciler reads it: active→control+guards, paused→guard only,
      stopped→nothing. **V4 (with the buttons); needs a migration ⚠️.**
- [ ] **`cm.reset` job** — writes `default_budget` + marks a budget schedule `stopped` (`catchup=true` — a missed
      reset is a permanent overspend gap). Bid Stop reuses no value write (state + schedule cleanup only). **V4.**
- [ ] **Button endpoints** (API, V4) = `state` write + `cm.reconcile` enqueue (+ `cm.reset` for budget Reset).
- [ ] **Terminal-guard-survives-pause** — a paused bid keeps its `stop_date` one-shot so it still auto-stops at
      end-time (the "boundaries win" invariant). Wire when `state`/pause lands.
- [ ] **Future-start dormancy precision** — a recurring boundary cron currently arms from `now`; before a rule's
      `start_date` the dumb budget job simply applies default (safe, but opens a browser). Set `next_run_at` to the
      start datetime to keep it truly dormant. *Optimization, not correctness.*
- [ ] **Stale-schedule cleanup after expiry** — expiry fires a reset one-shot but leaves the (now-inert) boundary
      crons, which keep applying default. A weekly drift-reconcile (or the expiry job triggering a re-reconcile)
      would remove them. *Tidiness, not safety.*
- [ ] **Bid window minute-precision** — `bid_windows` is hour-granular (`*/15 9-19`); sub-hour start/stop edges are
      rounded. Fine for MVP; tighten if a client sets, e.g., 09:30–20:45.

### Bid optimizer (from V2)

- [ ] **Tiered position sourcing** (the §8 scale lever, deferred by decision 2026-07-29) — MVP scrapes every
      keyword live every run. Add: at-target keywords → cheap source (24h report API or latest public-scrape DB
      snapshot), checked hourly; actively-chasing → fresh live scrape; **dedup by `(keyword, location)`** across
      campaigns/tenants. *Build when tenant count strains the box — it degrades gracefully until then.*
- [ ] **`recent_writes` wiring for the bid rate-limit** — `bid.run` passes `recent_writes=0` (same as budget);
      wire `repo.recent_write_count(kind="bid")` when live writes arm (V5), so the runaway-loop guardrail bites.
- [ ] **Windows-local live scrape** — v1 offloaded the consumer scrape to a thread executor (Playwright event-loop
      workaround). `positions.resolve` awaits `get_live_positions` directly; fine on the Linux VM, but the V2.6
      dry-run on a Windows laptop may need that workaround. *Confirm during V2.6.*

### Tables

- [ ] **Build `cm_campaign_catalog`** (model + migration) when we build `cm.sync_campaign_data` (~V4) — cached
      campaign keywords + products, replacing v1's `campaign_data_cache`. It's a regenerable cache (re-sync, no
      data migration). The bid optimizer (V2) may read products from it instead of a live fetch (optional). Drop
      `campaign_data_cache` at cutover (V6.4).

### Lanes / infra

- [ ] **Deprecate the v1 lanes** `budget_scheduler` / `bid_optimizer` / `sync_campaign_data` once v1 is off
      (part of V6). Note: Postgres can't cleanly drop enum values — leave them inert, or plan a type swap if we
      ever want a truly clean `lane` enum. Same applies to `cm_bid`/`cm_ops` if ever removed.
- [ ] **`reconcile` its own lane** — it sits in the shared `interactive` lane; if a long Explorer job ever
      starves it, give reconcile a dedicated no-browser lane. *Only if starvation is observed.*
- [ ] **`foresight_campaign_manager` Cloud Logging receiver** — optional dedicated log stream for cm.* (rides
      the per-lane receivers for now). *When we want cm logs isolated in the console.*

### Test / docs polish

- [ ] **pytest** — the repo has no test framework; V0.10 guardrail tests are standalone assert-based
      (pytest-compatible). Decide whether to adopt pytest properly (cleaner V3/reconciler tests). *Team call.*
- [ ] **`README.md` for `campaign_manager/`** — the layout currently lives in the package `__init__.py`
      docstring; split out if the package grows.
- [ ] **Golden-payload test for the Blinkit `PUT`** (BF1) — listed in Cross-cutting; do it *during* the build
      (V1/V2), not deferred — noted here only for visibility.

---

## Safety recap (the non-negotiables)

1. Dry-run is the default; `--live` must be explicit; the whole build runs dry until V5.
2. All Blinkit mutations go through `writes.py` — nothing else may PUT. (Enforce in review.)
3. Local = direct commands only. **Never `cli runner start` locally** (it claims the VM's real jobs).
4. Migrations / shared-DB writes: exact command shown, confirmed, single head kept.
5. Cutover is one tenant, attended, off-peak, and reversible by flipping which schedules are enabled.

---

## Blocking decisions (resolve when the phase needs them)

| Needed by | Decision                                                                                                                                  |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| ~~V0.6~~  | ~~Q2 — bid runtime location~~ ✅ **Resolved: split `cm_bid_runtime` table.**                                                              |
| ~~V3.4~~  | ~~reconcile trigger~~ ✅ **Resolved: runner-owned `cm.reconcile` job, enqueue-on-edit, edit-time schedules, unified one-shot scheduler.** |
| V5.1      | **write guinea-pig** — one low-stakes real campaign for write-path tests, or no-op re-asserts only.                                       |
