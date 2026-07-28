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

- [ ] **V2.1** `repo.py` — read `cm_bid_rules` + `cm_bid_runtime`; write runtime (`last_cpm/last_position/
last_bid_updated_at`) to `cm_bid_runtime` via scoped `UPDATE`; create the runtime row when a rule is
      added, cascade-delete with the rule; write `cm_run_log`. (No JSON anywhere.)
- [ ] **V2.2** `blinkit/positions.py` — tiered source: actively-chasing → live scrape; at-target → report API
      / latest public-scrape snapshot. Dedup by `(keyword, location)`.
- [ ] **V2.3** `bid.py` — port the bid loop (distance step, **10-min HOLD**, min/max clamp) → compute new CPM →
      `writes.apply_bid()`.
- [ ] **V2.4** `blinkit/adapter.py` — `read_position`, `read_bid`, `apply_bid` (`update_keyword_bids`).
- [ ] **V2.5** `writes.apply_bid` — clamp `[min,max]`, no-op skip, rate-limit.
- [ ] **V2.6** Dry-run for the live tenant — real position reads, zero writes.

**Gate:** bid decisions + would-apply logs correct in dry-run; runtime state persists to **DB, not JSON**.
**Verify:** log stream shows `decision` (pos vs target, verdict) + `write.intent` per keyword; `cm_bid_runtime`
rows update.

---

## V3 — Reconciler + unified scheduling (zero Blinkit)

Goal: rules → `job_schedules` (recurring + one-shot), written at edit time, idempotent; fully testable
without Blinkit.

- [ ] **V3.0** ⚠️ **Jobs-system enhancement (prerequisite): one-shot schedules.** Add a `repeat` flag to
      `job_schedules`; the producer **fires-then-disables** when `repeat=false` (instead of re-arming via cron);
      the deadman monitor treats a pending one-shot as overdue only after its `next_run_at`. Additive (existing
      recurring schedules unchanged). **Migration** ⚠️ (confirm). Lives in the **jobs system**, not
      `campaign_manager/` — a general capability the CM consumes.
- [ ] **V3.1** `reconciler.py` — read a tenant's rules → compute desired `job_schedules`: recurring windows as
      cron rows (future-start → `next_run_at` set to the start so it's dormant until then); `once` rules +
      expiry cleanups as **one-shot** rows. Deterministic names (`auto:cm:budget:<tenant>:<mp>:<hhmm>`,
      `auto:cm:bid:<tenant>:<mp>:<window>`).
- [ ] **V3.2** Idempotent apply: create missing / update changed / delete no-longer-wanted (match by name prefix).
- [ ] **V3.3** "**Stop = reset**": on rule pause/removal, enqueue a final reset job (budget→default / clear bid);
      **expiry** → pre-schedule a one-shot cleanup for the rule's end date at edit time.
- [ ] **V3.4** Triggers: **`cm.reconcile` is a VM job**; the API **enqueues** it after any rule CRUD (V4) — the
      API never mutates schedules itself. Plus an _optional_ weekly drift-check schedule.
- [ ] **V3.5** Tests — no Blinkit: seed rule sets (recurring, future-start, `once`, with end-date) for the test
      tenant, run reconcile, assert exact `job_schedules` rows **incl. one-shots**; re-run → no change
      (idempotent); a rapid double-edit doesn't lose a reconcile.

**Gate:** reconcile yields correct, idempotent `job_schedules` (recurring + one-shot) for representative rule
sets, incl. edits/pauses/removals/expiry; one-shot rows fire once then disable. **Verify:** unit/integration
tests against the test tenant; inspect `job_schedules`.

---

## V4 — On-demand actions + API + UI

Goal: enqueue→poll actions; new API surface; new UI page. Still dry by default.

- [ ] **V4.1** `jobs/types.py` — `cm.set_budget` (+ any other on-demand) as enqueue→poll jobs (lane `cm_ops`).
- [ ] **V4.2** `app/routes/campaign_manager.py` — rules CRUD (read/write DB), enqueue endpoints (set-budget,
      run-now), a **job-status/poll** endpoint, history reads. **No Playwright.** Calls `reconcile` after CRUD.
- [ ] **V4.3** `app/schemas/campaign_manager.py` — request/response contracts.
- [ ] **V4.4** Frontend `features/campaign-manager-v2/` (route `/campaign-manager-v2`): page, `api.js`,
      `hooks.js`, components — schedule builder (day timeline), bid-rule list, **automation status panels**
      (on/off, last run, next run, last error), history, set-budget with **enqueue→poll** feedback (spinner +
      real success/error, not a blind `setTimeout`).
- [ ] **V4.5** Nav: add the v2 page alongside v1 (don't remove v1 yet).

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
- [ ] **B3 guardrail — session-matches-account assertion** in `writes.py` (per-tenant *expected* advertiser_id
      → refuse a write if the loaded session's account doesn't match). *Multi-tenant hardening — tenant #2.*
- [ ] **Per-tenant guardrail bounds** (min/max budget, rate limits) — clients have different budget scales;
      global defaults in `config.py` for now. *When tenant #2 with a different scale lands.*
- [ ] **Arming UX** — `live` is currently a per-job param (`live=true` → `--live`). Decide the real arming
      mechanism for the UI/scheduler (per-schedule param vs. per-tenant flag) at **V4/V5**.

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
