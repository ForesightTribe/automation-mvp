# Campaign Manager

> The single source of truth for the Campaign Manager: what it is, how it decides, what it
> writes to the marketplace, and **exactly what happens in every edge case we know about**.
> Replaces the earlier `campaign-manager-refactor.md`, `campaign-manager-v2-implementation.md`
> and `campaign-activation.md`.

**Jump to:** [Edge-case reference](#9-edge-case-reference) · [Known gaps](#12-known-gaps--parked)
· [Config](#10-configuration) · [Operating it](#11-operating-it)

---

## 1. What it is

Two different things live under "ads", and conflating them causes confusion:

|             | **Ads Analytics** (`/ads`)                 | **Campaign Manager** (`/campaign-manager`)        |
| ----------- | ------------------------------------------ | ------------------------------------------------- |
| Purpose     | Report on paid activity (spend, RoAS, SoV) | **Act on** the marketplace — change budgets & bids |
| Data source | Scraped tables                             | Live marketplace API via a logged-in session       |
| Direction   | Read-only                                  | Read **and write**                                 |
| Risk        | Low (just SQL)                             | High — writes money-affecting settings to a live account |

This doc is the second column. Three capabilities:

- **Budget scheduler** — a thermostat. Set the daily budget by time-of-day / day-of-week rules,
  and optionally start/stop the campaign at window edges.
- **Bid optimizer** — cruise control. Move a keyword's CPM to hold a target search position, then
  find the cheapest bid that still holds it.
- **On-demand actions** — set a budget now, start/stop a campaign now, read live state.

Blinkit is the only marketplace implemented. Everything marketplace-specific lives behind
`marketplaces/blinkit/`; the orchestration above it is marketplace-agnostic.

---

## 2. Mental model

```
   rules (DB)  ──edit──▶  cm.reconcile  ──▶  job_schedules
        │                                          │
        │                                     cron fires
        ▼                                          ▼
   the engines  ◀────────────────────────  runner (VM)
   budget.py / bid.py
        │
        │  every mutation, no exceptions
        ▼
   writes.py  ── guardrails ──▶  marketplaces/blinkit/adapter.py  ──▶  Blinkit
        │
        └──▶ cm_run_log (slim history, for the UI)  +  Cloud Logging (narration)
```

Five moving parts:

1. **Rules** — what the user wants. DB only, no files.
2. **The reconciler** — compiles rules into `job_schedules` rows. Never touches the marketplace.
3. **The engines** — `budget.py` and `bid.py`. Load a session, read live state, decide, write.
4. **The choke point** — `writes.py`. The *only* code that mutates the marketplace.
5. **Logs** — slim structured rows in `cm_run_log` for the UI; verbose narration to Cloud Logging.

### Principles

- **The VM is the only executor.** The API only reads the DB and enqueues jobs — no Playwright in
  `app/`, so Render can never spawn a browser or write to Blinkit.
- **The DB is the only source of truth.** No JSON state files.
- **Dry-run by default.** A live write requires explicit arming, per tenant.
- **Ephemeral browsers.** A job is a subprocess that launches Chromium, does its work, and exits.
  Failure isolation, and peak RAM capped by lane slots rather than tenant count.

---

## 3. Architecture

### Package layout

```
campaign_manager/
├── config.py         guardrail bounds, dry-run default, drift knobs (env-overridable)
├── logs.py           structured, dry-run-aware logging helpers
├── repo.py           all DB access — rules, runtime, run log (tenant + platform scoped)
├── writes.py         THE CHOKE POINT — guardrails + the only path to a mutation
├── budget.py         budget scheduler engine (+ campaign start/stop)
├── bid.py            bid optimizer engine (+ the end-of-window reset run)
├── reconciler.py     rules → job_schedules (pure planning + idempotent apply)
├── set_budget.py     on-demand single-campaign budget write
├── set_activation.py on-demand single-campaign start/stop
└── marketplaces/
    └── blinkit/
        ├── adapter.py        the marketplace mechanism (read_*/apply_*), status mapping
        ├── client.py         raw Blinkit API client
        ├── live_position.py  consumer-search API client (where our ad actually ranks)
        ├── positions.py      product matching → sponsored position
        └── restart.py        the RESTART payload builder
```

### Lanes

Lanes run in parallel and are sequential within themselves. A job's lane comes from its type.
Concurrent browsers = the RAM bill (~1 GB each).

| Lane          | Jobs                                              | Why |
|---------------|---------------------------------------------------|-----|
| `cm_bid`      | `cm.bid_optimizer`                                | The control loop. Isolated so nothing can starve it |
| `cm_ops`      | `cm.budget_scheduler`, `cm.set_budget`, `cm.set_activation`, `cm.sync_campaign_data` | Latency-tolerant, share one browser's worth of RAM |
| `interactive` | `cm.reconcile`                                    | No browser at all — it only writes our own rows |

**`cm_bid` and `cm_ops` run at the same time.** That parallelism is the source of several ordering
subtleties below — most importantly that both engines issue *whole-campaign* PUTs.

### Job types

| Job type                | Lane          | Params            | What it does |
|-------------------------|---------------|-------------------|--------------|
| `cm.budget_scheduler`   | `cm_ops`      | `live`            | Apply the budget (and start/stop) that matches *now* |
| `cm.bid_optimizer`      | `cm_bid`      | `live`, `reset`   | One optimizer pass; `reset` = end-of-window de-escalation |
| `cm.reconcile`          | `interactive` | `live`            | Recompile rules → `job_schedules` |
| `cm.set_budget`         | `cm_ops`      | `campaign`, `budget`, `live` | On-demand budget write |
| `cm.set_activation`     | `cm_ops`      | `campaign`, `action`, `live` | On-demand start/stop |
| `cm.sync_campaign_data` | `cm_ops`      | —                 | Cache campaign keywords/products |

---

## 4. Data model

All tables are `(tenant_id, platform)` scoped.

| Table                   | Holds |
|-------------------------|-------|
| `cm_budget_schedules`   | One per campaign: `default_budget`, `stop_after_window`, `state` |
| `cm_budget_rules`       | Windows on a schedule: budget + timing (recurring or once) |
| `cm_bid_rules`          | Keyword bid config: `target_position`, `min_bid`, `max_bid`, window, measurement store |
| `cm_bid_runtime`        | System state, 1:1 with a bid rule (below) |
| `cm_platform_accounts`  | `advertiser_id` + **`live_armed`** (the per-tenant arming switch) |
| `cm_run_log`            | Slim append-only history for the UI |

**One schedule per (tenant, platform, campaign)** is a DB constraint — a campaign has one everyday
budget, and two automations for it could only contradict each other. Extra windows go on the
existing schedule as rules.

### `cm_bid_runtime` — the system's memory

| Column | Meaning |
|---|---|
| `last_cpm` | The bid as we last set it |
| `last_position` | The position observed last tick — used for two-tick confirmations |
| `last_bid_updated_at` | Drives the reflection HOLD |
| `last_holding_cpm` | The last bid observed **holding** target. The precise snap-back price |
| `drift_paused_until` | When shaving may resume after an overshoot |
| `effective_target` | The relaxed target, when the real one is unreachable at `max_bid` |
| `raise_step` | The last raise size. Escalates while the position refuses to move, resets when it does |
| `effective_at_max_bid` | The ceiling `effective_target` was concluded at — makes edits self-healing |
| `updated_at` | Stamped whenever a tick persists runtime. **This is how "first tick of this window" is detected**, which is why no extra column was needed |

`cm_run_log` is append-only and needs a retention policy eventually. Verbose narration goes to
Cloud Logging, not the DB.

---

## 5. Scheduling — the reconciler

Rules do not poll. On any rule change the API enqueues `cm.reconcile`, which compiles the current
rules into `job_schedules` rows with deterministic names, idempotently (create missing / update
changed / delete no-longer-wanted). Only rows matching `auto:cm:<kind>:<tenant>:<platform>:…` for
the current platform are ever touched — manual schedules and other marketplaces are never deleted.

What it produces:

| Schedule | Cron | Purpose |
|---|---|---|
| Budget boundaries | one per distinct rule start/end time | Apply the budget that matches now |
| Safety poll | hourly | Catch drift and fires missed while the runner was down. **Recurring rules only** — a once-only automation is self-contained |
| `once` fires | one-shots, deduped by time | Apply at the window start, revert at the end |
| Expiry | one-shot at 00:05 after `end_date` | Reset to default promptly |
| Bid optimizer | `*/15` within the merged active hours | The control loop |
| Bid reset | daily at each window's stop, **fired 1 min early** | De-escalate closed keywords to `min_bid` |
| Cleanup | daily 04:00 | Self-reconcile to prune expired schedules |

**Why the bid reset fires a minute early.** `cm_bid` and `cm_ops` are parallel lanes, so a reset
scheduled on the same minute as a budget window's stop races the budget engine — and once that
engine stops the campaign, a bid write may be refused. One minute of lead makes the ordering
deterministic with no cross-lane coordination. The engine compensates with a **2-minute
look-ahead** (`RESET_LOOKAHEAD_MINUTES`) so the early fire still sees the window as closed; the
look-ahead must stay larger than the lead.

**A `once` bid rule gets its own date-bound cron** (`*/15 h <day> <month> *`) so it can never recur.

---

## 6. The budget engine

Each run, for every schedule: work out what should be true *now*, read the campaign, write if it
differs.

`plan_for_now` returns `(budget, state, reason)` where `state` has three answers:

- **`running`** — a rule is active. Starting is unconditional: a campaign with a budget window is
  meant to run during it, so finding it stopped and leaving it stopped would silently do nothing.
- **`paused`** — a window just ended *and* the schedule opted in via `stop_after_window`.
- **`None`** — the campaign's run state is none of our business right now. With the toggle off this
  is the only non-running answer, so an existing schedule never has its status touched at all.

The first matching rule wins, ordered by rule id — oldest wins, which is stable and explainable
("the one you made first takes precedence"). With no rule matching, `default_budget` applies, so an
end-time boundary naturally reverts.

`_window_just_ended` probes a **range**, not a single instant: a point probe silently missed any
window shorter than the misfire grace, and a late fire broke it the same way.

---

## 7. The bid engine

The control loop, every 15 minutes inside an active window. Per rule: read the campaign detail
(status + all keyword bids in one call), scrape the live consumer search at the rule's fixed store,
find our sponsored position, decide, write.

### 7.1 The shape of a window

```
 open            climb                 hold + drift              close
  │                │                       │                       │
  ▼                ▼                       ▼                       ▼
min_bid ──▶ raise, raise, raise ──▶ target held, shave 7%/tick ──▶ min_bid
            (₹100/₹50/₹25 steps)      snap back if it overshoots
```

Every window **starts and ends at the floor.** The pair is deliberate: the end-of-window reset is
best-effort (the campaign may be dark, or the write refused), and without the window-open floor a
reset that failed last night is never recovered — `current_cpm` reads yesterday's `last_cpm` and
steps *up* from it, so the bid ratchets across days until it pins at `max_bid`.

### 7.2 Climbing — the escalating raise

Position worse than target → raise. The step is **not** scaled by distance from target; it
escalates on whether the last raise actually worked.

```
base   = max(CM_BID_RAISE_MIN_STEP, CM_BID_RAISE_PCT% of the current bid)
position didn't improve → step × CM_BID_RAISE_ESCALATE
position improved       → back to base
window opened           → back to base
```

**Why not distance-scaled.** Sponsored slots sit about 4 apart (1/5/9/13/17), so slot
distance is nearly always either ≥4 or 1–2 — the old four-tier table resolved to ₹100 or
₹25 in practice and its ₹50 tier fired **once in 88 recorded steps**. Slot distance is also
a poor proxy for *rupee* distance: the bid→position curve is a staircase with treads
hundreds of rupees wide, so "one slot away" can cost ₹50 or ₹600. Distance simply isn't the
signal. Whether the last raise moved the position is.

Typical climb from a ₹100 floor at the defaults (₹50 / 8% / ×1.5):

| Tick | Bid | Step |
|---|---|---|
| 1 | 100 | +50 |
| 2 | 150 | +75 |
| 3 | 225 | +112 |
| 4 | 337 | +168 |
| 5 | 506 | +252 |
| 6 | 758 | +378 |

₹1,135 in six ticks, against ₹700 for a flat ₹100 step — and it reaches ₹10,000 in about
12 ticks, which is what lets a rule with **no `max_bid`** actually get there inside a window.

**One tick can never more than double the bid** (the step is capped at the current bid),
and `CM_BID_RAISE_ESCALATE=1.0` disables escalation entirely, leaving a flat
`max(floor, pct%)` step.

**Escalating is only safe because drift-down exists.** A fast climb overshoots the true
threshold; drift walks it back and settles just above it. Climb fast to find the position,
descend slowly to find the price. That is also why the multiplier is 1.5 rather than 2 —
doubling arrives a tick sooner but overshoots about twice as far, and drift then spends an
extra hour undoing it.

Only a **genuine raise** carries the escalation forward. A drift recovery snap-back is a
precise return to a known-good price, not a climb, and holding ticks aren't climbing at all
— letting either escalate would make the next real raise start from an inflated step.

**Reflection HOLD** — if the position hasn't improved and it's been under 10 minutes since the last
change, wait. Marketplace changes take time to show up; stacking raises overbids. At the
15-minute cadence this rarely fires; it exists for back-to-back runs, such as an edit
triggering an immediate re-apply.

### 7.2b Where the position comes from

One **API request per (keyword, store)** — the engine does not load search pages.

A single warm-up per run (homepage + one throwaway search) establishes a cleared session
and captures the headers Blinkit attaches to its own `/v1/layout/search` request. After
that every keyword is an in-page `fetch()` costing well under a second, and **the store is
selected by the `lat`/`lon` headers**, so spanning several stores costs no more than one.

Two properties the bid loop depends on:

- **Results are cached per `(keyword, store)` for the run.** Several campaigns routinely
  target the same keyword at the same store; the search results are identical, so only the
  product match differs. A *failed* fetch is cached as the failure too — re-scraping a
  keyword that just timed out only feeds the throttling that caused it.
- **"Couldn't look" is distinct from "our ad isn't there."** A failed request raises (→
  `error` row); an empty or organic-only result returns normally (→ `skip`). Collapsing
  them would let a transport fault read as "we're not ranking" and be acted on.

The transport — in-page fetch on a cleared session, Cloudflare-challenge detection, retry
with backoff — is **shared with the public scraper** (`in_page_fetch`), not copied, so a
Blinkit change is fixed once.

> **Why it works this way.** Until 2026-08-22 this launched a Playwright driver and a
> Chromium **per keyword**, then did two full `page.goto`s waiting on `networkidle`. That
> cost 10–60s per keyword and made Blinkit see a dozen cold clients hitting the same search
> from one IP within minutes. Eight of twelve keywords were lost to `Page.goto` timeouts and
> run time climbed 87s → 524s across four runs, heading for the 15-minute job timeout —
> past which the next fire is silently dropped by the overlap guard. There is also
> deliberately **no DOM fallback**: it could not read `ads_campaign_id`, so everything it
> returned was flagged organic, which `match_position` can only read as "skip". It never
> once produced a usable bid decision.

### 7.3 Holding — "at target **or better**"

Being better than target is a **success, not an error to correct.** Sponsored slots sit on a sparse
lattice — ~89% of observed positions were 1/5/9/13/17 — so a target of 3 is frequently unreachable,
and demanding exact equality would mean never settling.

### 7.4 Drift-down — the cheapest price that holds

Once holding, shave `CM_BID_DRIFT_PCT`% off the bid each tick. When a shave goes one step too far
and the position is lost, snap back to `last_holding_cpm` and stop shaving for
`CM_BID_DRIFT_PAUSE_MINUTES`.

Why it matters: the climb stops at the *first* bid that worked, which can be far above the real
threshold. Observed in practice — a keyword climbed ₹350 → ₹900 with the position stuck at 15 the
whole way, then showed position 15 again at ₹300. ₹600 bought nothing.

Four rules make it safe:

- **Two consecutive holds before shaving.** A single reading was unreliable in ~28% of repeatedly
  measured bid levels. It also gives a fresh raise one tick to prove itself before we undo it.
- **Overshoot vs market move** (`is_recovery`). Off target at a bid *below* one known to hold = our
  own drift went too far → snap back **precisely** to it. Off target at or above it = a competitor
  moved → normal raise. A step-raise from ₹299 would jump to ₹399 and overshoot the known-good ₹322
  by ₹77, then spend an hour drifting back down.
- **The pause is a ONE-WAY valve.** It gates the decrease only. Raises are never blocked, so being
  outbid during peak hours is answered on the very next tick.
- **`last_holding_cpm` is refreshed on every holding tick**, not just the first, so the snap-back
  tracks the market instead of returning to a price that worked an hour ago.

`CM_BID_DRIFT_PCT=0` is the default and a **true revert** — at 0 the decision logic is behaviourally
identical to pre-drift (freeze at target, step down only when strictly better).

### 7.5 Unreachable target

Pinned at `max_bid` with the target still missed, the old behaviour recomputed `max_bid`, had the
no-op guardrail reject it, and wrote a junk `skip` row — every 15 minutes, all day, paying the
ceiling for a position the ceiling did not buy.

Now the position actually achieved becomes the **working target**, and drift finds the cheapest bid
that holds *it*.

- **Two confirmations before relaxing.** One bad scrape must not relax a target for a whole window.
- **Relaxes to the current position, not the better of the two.** Relaxing too far self-corrects
  (drift just optimises the cheaper position); relaxing not far enough puts us straight back to
  pinning at max and doing nothing.
- **`effective_at_max_bid` makes edits self-healing.** The relaxed target is void the moment the
  rule's `max_bid` differs from the ceiling it was concluded at. **Raising the ceiling is the
  dangerous direction** — a stale relaxed target would have the optimizer keep drifting *down* right
  after being handed more room to climb.
- **Cleared at window open**, so every day re-climbs and retries the real target from scratch.

There is deliberately **no acceptability floor**: even a relaxed target of position 15 is held
rather than abandoned, because it is strictly better than the alternative — same position, a
fraction of the price. "Below what rank is this worth paying for?" is a business question, parked.

### 7.6 `max_bid` is optional

A rule does not have to name a ceiling — sometimes the target position is wanted whatever
it costs, and forcing a number up front either caps the rule too low or invites a made-up
value.

`None` does **not** mean unbounded. `resolve_ceiling` turns a rule's `max_bid` into a
concrete ceiling once, at the top of the loop:

```
ceiling = min(rule.max_bid, CM_BID_MAX_ABSOLUTE)  if rule.max_bid
          else CM_BID_MAX_ABSOLUTE
```

so every consumer — the decision logic, the clamps, the unreachable-target relaxation —
still receives a plain int and never has to know the field is optional. A rule that *does*
set a ceiling is capped at the lower of the two, which also catches a typo'd `max_bid`.

`CM_BID_MAX_ABSOLUTE` is a **runaway guard, not a tuning knob** — set well above any
realistic CPM (₹10,000 vs the ₹900 high-water mark) so it never binds in normal operation.
Real spend is bounded by the daily budget long before it: at a ₹10,000 CPM a ₹2,000 budget
is gone in 200 impressions and the campaign goes ON_HOLD.

✅ The old "a flat ₹100/tick tops out near ₹2,900 per window" limitation is **gone** — the
escalating raise (§7.2) reaches ₹10,000 in about 12 ticks, so an unbounded rule can now
actually reach a high target inside a window.

### 7.7 Bounds are invariants

`min_bid` / `max_bid` are enforced **every tick** against the live bid, not merely clamped onto a
value the optimizer chose to change. They used to be applied only to a computed change, so when the
decision was "no change" — the common case once a target is held — lowering `max_bid` below the live
bid did nothing at all until the next window opened, leaving the campaign a full day over its
ceiling. An out-of-bounds live bid is now written back into range before the position scrape.

### 7.8 The end-of-window reset

`cm.bid_optimizer --reset` writes each just-closed keyword back to `min_bid`. No position scrape, so
it's cheap. It skips keywords still covered by another in-window rule.

It has **no status gate**: `held` (ON_HOLD) is a *running* campaign whose budget ran out and the
marketplace accepts an update on it, and a genuinely stopped campaign gets the write attempted so
the refusal lands as a **visible failed History row** rather than an invisible skip.

An **unreadable** bid does not mean "already at the floor" — it means write it anyway. A genuine
already-at-floor is skipped (a bid write is a whole-campaign PUT; no point risking a clobber for no
change) but is **logged** either way.

---

## 8. Writes — the choke point and the marketplace contract

### 8.1 `writes.py`

Nothing else may call an adapter's `apply_*`. Every mutation goes through `apply_budget()`,
`apply_bid()` or `apply_status()`, which:

1. log the intent,
2. run guardrails — bounds, clamp, no-op skip, rate limit, status-transition table,
3. log the guardrail verdict,
4. and only then delegate to the adapter.

The guardrail checks are **pure functions**, unit-tested without the marketplace.

| Guardrail | Rule |
|---|---|
| Budget bounds | Reject outside `[CM_MIN_BUDGET, CM_MAX_BUDGET]`. A bug computing `budget=0` must be refused, never sent |
| Bid clamp | Clamp into `[min_bid, max_bid]` — defence in depth |
| No-op skip | Computed value equals current → skip the write |
| Rate limit | Max `CM_MAX_WRITES_PER_WINDOW` successful writes per **keyword** per `CM_RATE_WINDOW_MINUTES` |
| Status transitions | A table, not a scalar bound — see below |
| Live arming | A live run requires a stored `advertiser_id`, injected onto the client so the write carries the right account |

### 8.2 A bid write is a whole-campaign PUT

This is the single most important thing to know before touching this code.
`update_keyword_bids` fetches the entire campaign and PUTs it back — budget, start and end dates,
pids, brand ids, **every** keyword — with one CPM swapped in.

Consequences:

- **A "no change" write is not free.** Every write is a chance to clobber something, which is why
  the no-op guardrail exists and why already-at-floor is a skip rather than a harmless rewrite.
- **Lost updates are possible.** The budget engine does the same read-whole → write-whole cycle from
  a parallel lane. If it sets ₹2000 while our PUT is in flight from a read taken seconds earlier,
  our PUT echoes the old budget back.
- The payload also does `total_budget = detail.get("campaign_budget", 0)` — a thin detail read would
  write a budget of zero.

### 8.3 Status vocabulary

| Marketplace | Canonical | Notes |
|---|---|---|
| `ACTIVE`    | `running` | |
| `STOPPED`   | `paused`  | User-stopped — resumable |
| `ON_HOLD`   | `held`    | **Delivery paused because the daily budget ran out.** Still LIVE, not stopped: accepts an update (which is what revives it) and can be stopped. Never *restarted* |
| `COMPLETED` | `ended`   | Terminal |
| `DRAFT`     | `draft`   | Never launched |
| `SCHEDULED` | `running` | **Transient** — reported for a minute or two after a RESTART before settling to `ACTIVE` |

We only ever *write* `running` / `paused`. The rest exist so the guardrail can recognise and refuse
them.

**Status comes from campaign _detail_, never the campaigns list.** `get_campaigns()` asks for every
campaign type and the API rejects the whole request when any one of them is disabled for the
advertiser — which the client turns into an **empty list, silently**. A bulk status read built on it
returns nothing and looks like "no campaigns to manage".

### 8.4 Start and stop are not symmetric

- **Pause** is a bodiless `DELETE /adservice/v1/campaigns/{id}`. Cheap and safe.
  ⚠️ **`DELETE` does not delete — it stops.** The campaign survives and can be restarted. The
  adapter carries a loud comment because any future reader will assume it's a catastrophic bug.
- **Resume** is `PUT /adservice/v3/campaigns` with `campaign_request_type: "RESTART"` — a **full
  campaign re-submission** that rewrites budget, keywords, bids, pids and dates, and resets the
  start date to today. It therefore requires a budget and inherits the budget-bounds guardrail, and
  logs `status.overwrites` — the diff of everything it will replace — so a silently reverted bid is
  visible rather than discovered weeks later.

**The restart re-submits the bids it read.** This is why the window-open floor re-checks until the
marketplace reads back `min_bid`: the budget engine restarts the campaign on the same boundary
minute from a parallel lane, and its RESTART can land on top of our write.

`allowed_transitions` in the detail (`['RESTART']` when stopped, `['UPDATE']` when active) is
authoritative for the resume direction only — the stop is a different endpoint that never appears
there, so gating on it would block every stop.

### 8.5 Sessions

The campaign manager **consumes** the same `(tenant, "blinkit")` session as the scrapers and owns no
auth code of its own. Sessions live encrypted in the DB, not on disk. Engines call `ensure()`, so an
expired session self-heals. See [platform-auth.md](platform-auth.md).

---

## 9. Edge-case reference

Everything below is the actual behaviour of the current code.

### 9.1 Window opens

| Scenario | What happens |
|---|---|
| Normal open | Writes `min_bid`. Doesn't trust it — re-checks each tick until the marketplace reads it back |
| Bid already at `min_bid` | Confirms, marks the window open, optimises from `min_bid` |
| Last night's reset failed, bid still high | Writes `min_bid`. **This is what stops the multi-day ratchet** |
| Budget engine's RESTART overwrites our write | Next tick sees the old bid and writes again. Self-correcting, costs one tick |
| Campaign not running yet at open | Skips, does **not** mark the window open, retries next tick |
| Yesterday's drift / pause / relaxed target | All cleared — every day retries the real target from scratch |
| Overnight window (18:00–02:00), tick at 01:00 | Still the *same* window. Midnight doesn't re-floor a bid mid-flight |
| Dry run | Simulates the write, then marks open anyway — otherwise a dry tenant re-opens forever and never exercises the optimizer |

### 9.2 Climbing

| Scenario | What happens |
|---|---|
| Position worse than target | Raise by the distance-scaled step |
| Raised, no improvement, <10 min since | HOLD — wait for the marketplace to reflect it |
| Position unreadable / product not found | Skip. No write, **no runtime stamp** → next tick retries |
| Organic-only (ad not serving) | Skip |
| Position scrape throws | Error row, counted; the run continues to the next keyword |
| Reached `max_bid`, target still missed | See [9.4](#94-target-unreachable) |

### 9.3 At target

| Scenario | Drift **off** (default) | Drift **on** |
|---|---|---|
| Exactly at target | Freeze — pays the climb price all day | Shave `DRIFT_PCT`%/tick |
| Better than target (pos 1, target 3) | Steps *down* toward target | Counts as holding, shave |
| Held once only | — | Wait for a second confirmation |
| Shave went too far, position lost | — | Snap back **precisely** to `last_holding_cpm`, pause |
| Outbid during the pause | Raise normally | **Raise normally** — the pause only blocks decreases |
| Already at `min_bid` | No change | No change |

### 9.4 Target unreachable

| Scenario | What happens |
|---|---|
| Pinned at `max_bid`, target missed **twice** | Adopt the achieved position as the working target (`relax` row); drift then optimises for it |
| Missed once only | No relax — one bad scrape can't relax a target for a whole window |
| Still room below the ceiling | No relax — the climb hasn't finished trying |
| Relaxed to a poor position (e.g. 15) | **Still held.** No acceptability floor — deliberately parked |
| New window next day | Relaxation cleared, real target retried |
| Target becomes reachable mid-window | **Not noticed until tomorrow.** Parked — see [12](#12-known-gaps--parked) |

### 9.5 Rule edited

| Scenario | What happens |
|---|---|
| `max_bid` lowered below the live bid | Forced into range on the next tick (`bounds` row) |
| `min_bid` raised above the live bid | Forced up on the next tick |
| `max_bid` **raised** while relaxed | Relaxed target voided → climbs for the real target. Without this it would drift *down* after being given more room |
| `max_bid` lowered while relaxed | Voided, re-derived against the new ceiling |
| `target_position` edited | Relaxed target cleared explicitly (no self-healing tell for this one) |
| Any in-window edit | Reconcile + an immediate engine run, so the change lands now rather than at the next tick |
| Editing a spent `once` rule | Rejected (400) unless the edit moves its date forward |
| Campaign on a rule | Not editable — it is the rule's identity |

### 9.6 Window closes

| Scenario | What happens |
|---|---|
| Campaign running | Writes `min_bid` |
| Campaign **ON_HOLD** (budget exhausted) | **Writes it** — ON_HOLD is a running campaign |
| Campaign stopped, write refused | Attempted anyway; logs a **visible failed** row. Window-open recovers it |
| Bid already at `min_bid` | Skips the write, but **logs** the skip |
| Bid unreadable | Writes anyway — "unknown" is not "already at the floor" |
| Keyword still covered by another in-window rule | Left alone |
| One keyword's write throws | Caught — the other keywords still get de-escalated |
| Reset fire missed (runner down >5 min) | Dropped until tomorrow. Window-open covers it |

### 9.7 Budget engine

| Scenario | What happens |
|---|---|
| A rule matches now | Apply its budget; start the campaign unconditionally if stopped |
| No rule matches | Apply `default_budget` |
| Window just ended, `stop_after_window` on | Stop the campaign |
| Window just ended, toggle off | Revert to default, **never** touch run state |
| Two overlapping windows | The **oldest rule** wins — stable and explainable |
| Campaign is ON_HOLD | Budget is writable — raising it is what revives delivery |
| Campaign is `ended` / `draft` | Refused by the transition table (a draft is startable only by an explicit human action) |
| Recurring rule's `end_date` passes | A one-shot at 00:05 the next morning resets to default |
| Fire missed while the runner was down | The hourly safety poll catches it (recurring rules only) |

### 9.8 Safety and failure

| Scenario | What happens |
|---|---|
| Tenant not armed (`live_armed=false`) | Everything computes and logs; **nothing is written** |
| No `advertiser_id` stored | Live run refused outright — it can't be derived, so it must be configured |
| Session expired | Run aborts cleanly, error logged |
| Campaign detail read fails | Status treated as *unknown*, not stopped — a read blip must not silently pause optimization |
| >`MAX_WRITES_PER_WINDOW` writes on a keyword | Rate limit blocks further writes |
| Computed budget is 0 or absurd | Rejected by the bounds guardrail, never sent |
| `CM_BID_DRIFT_PCT=0` | True revert to pre-drift behaviour |

---

## 10. Configuration

`campaign_manager/config.py`. Every value has a safe default; **no required `.env` keys.** All are
read at import, so **the runner must be restarted** for a change to take effect.

| Env | Default | Meaning |
|---|---|---|
| `CM_DRY_RUN_DEFAULT` | `True` | Every action is dry-run unless explicitly armed |
| `CM_MIN_BUDGET` / `CM_MAX_BUDGET` | `1` / `100000` | Budget bounds guardrail |
| `CM_MAX_WRITES_PER_WINDOW` | `12` | Rate limit, per keyword |
| `CM_RATE_WINDOW_MINUTES` | `60` | Rate-limit window |
| `CM_BID_DRIFT_PCT` | **`7`** (armed) | **The drift kill switch.** Set to `0` for a true revert to pre-drift behaviour |
| `CM_BID_DRIFT_MIN_STEP` | `5` | Floor for one shave, so small bids still move |
| `CM_BID_DRIFT_PAUSE_MINUTES` | `90` | How long before shaving resumes after an overshoot |
| `CM_BID_RAISE_MIN_STEP` | `50` | Absolute floor for one raise |
| `CM_BID_RAISE_PCT` | `8` | Base raise as a % of the current bid |
| `CM_BID_RAISE_ESCALATE` | `1.5` | Multiplier per tick the position doesn’t move. `1.0` = flat step |
| `CM_BID_MAX_ABSOLUTE` | `10000` | Runaway guard. The ceiling for a rule with no `max_bid`, and a cap on one that has |

Fixed constants: reflection `HOLD_MINUTES=10` · optimizer cadence 15 min · reset lead 1 min ·
reset look-ahead 2 min · safety poll hourly · cleanup 04:00.

**Arming is per tenant**, not per env: `live_armed` on `cm_platform_accounts`. When armed, the
reconciler stamps `live=true` on that tenant's engine schedules so scheduled runs write for real.
Reversible — disarm, reconcile, back to dry.

---

## 11. Operating it

### CLI

```bash
python -m cli cm budget-scheduler --tenant <uuid> [--live]
python -m cli cm bid-optimizer    --tenant <uuid> [--live] [--reset]
python -m cli cm reconcile        --tenant <uuid> [--live]
python -m cli cm set-budget       --tenant <uuid> --campaign <id> --budget <n> [--live]
python -m cli cm show             --tenant <uuid> --campaign <id>     # READ ONLY
python -m cli cm set-advertiser   --tenant <uuid> --id <n>
python -m cli cm arm|disarm       --tenant <uuid>
python -m cli cm rules add-bid|add-budget|list|remove-bid|remove-budget
```

Everything defaults to dry-run. `--live` is always explicit.

### Rolling out a change

1. Apply any migration (shown and confirmed first — shared DB).
2. Merge to `main` and pull on the VM. **The VM runs `main`; nothing on a feature branch exists there.**
3. Create one bid rule on a **low-stakes campaign**, with drift off.
4. Watch a day of `cm_run_log` + Cloud Logging: does the window-open floor land, does the end reset
   fire, does anything get refused?
5. Only then arm drift (`CM_BID_DRIFT_PCT=7` + runner restart) on that one keyword, and measure.

### What to watch first

- **An `open` write that never confirms.** The most likely real-world failure: the marketplace
  returns a `min_cpm_config` per campaign type (the client falls back to 500), so a `min_bid` below
  that floor may be silently clamped or rejected.
- **`bounds` rows** appearing without an edit — would mean something else is moving the bid.
- **`relax` rows** — how often targets turn out to be unreachable, and at what position.
- **Failed `reset` rows** — how often the campaign is already dark at window close.

---

## 12. Known gaps & parked

### Deliberately parked

| Gap | Consequence |
|---|---|
| Target becoming reachable **mid-window** | Not noticed until the next day. Re-testing means climbing back to the ceiling, which burns most of a window and usually finds nothing |
| No acceptability floor on a relaxed target | A poor position is held cheaply rather than abandoned. "Below what rank is this worth paying for?" is a business call |
| Drift parameters (7%, 90 min) | Educated guesses, unmeasured. Tune from real History rows |
| Tiered position sourcing | Every distinct (keyword, store) is fetched live every run. Now one cheap API request each rather than a browser launch, so the pressure is much lower |
| Per-tenant guardrail bounds | Global defaults for now; revisit when a second tenant with a different budget scale lands |

### Known, not yet fixed

| Gap | Consequence |
|---|---|
| **Marketplace CPM floor unverified** | If `min_bid` is below it, floor writes may be rejected. Shows as an `open` write that never confirms |
| Reset schedule is `catchup=False` | A firing missed while the runner is down waits until tomorrow. Window-open covers it, so lower priority |
| Reset and optimizer share the overlap-guard key `(job_type, tenant_id)` | A reset can be swallowed by an in-flight optimizer run. Harmless at ~30 s runs; bites around 20–30 keywords. Fix: a distinct job type, or include params in the guard |
| Bid window scheduling is hour-granular | A 09:30 start rounds to the 09:00 hour; `_in_window` filters the early ticks, so it's cosmetic |
| Stale boundary crons after expiry | Expiry fires a reset one-shot but leaves the now-inert boundary crons; the daily cleanup prunes them |
| `cm_run_log` has no retention policy | Grows unbounded against a 500 MB quota |
| `cm_campaign_catalog` not built | `cm.sync_campaign_data` is a stub; the optimizer fetches products live |

### ⚠️ Never validated against the live marketplace

Every check so far is unit tests and a fake-adapter simulation. The window-open floor, the
end-of-window reset, drift, relaxation and bounds enforcement have **not** run against a real
campaign yet.

---

## 13. Testing

Standalone assert-based, no pytest dependency, no DB and no marketplace:

```bash
python -m campaign_manager.tests.test_bid_logic       # the bid decision
python -m campaign_manager.tests.test_guardrails      # writes.py
python -m campaign_manager.tests.test_reconciler      # rules → job_schedules
python -m campaign_manager.tests.test_budget_rules    # rule matching
python -m campaign_manager.tests.test_budget_apply    # budget + activation decisions
python -m campaign_manager.tests.test_transitions     # status transition table
python -m campaign_manager.tests.test_advertiser      # account guardrail
python -m campaign_manager.tests.test_restart_payload # the RESTART body
```

The decision logic is **pure** and tested without a browser. The orchestration — where the real bugs
have been — is covered by a fake-adapter end-to-end simulation of `bid.run` that exercises ON_HOLD,
refused writes, unreadable bids, the RESTART clobber, bounds edits, relaxation and overnight
windows, run green with drift both armed and off.
