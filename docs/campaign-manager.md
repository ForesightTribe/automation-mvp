# Campaign Manager

> The single source of truth for the Campaign Manager: what it is, how it decides, what it
> writes to the marketplace, and **exactly what happens in every edge case we know about**.
> The **only** Campaign Manager doc. It describes the system as it is now — the v1 audit, the
> v2 build plan and the activation design it grew out of were folded in and deleted 2026-08-29;
> `git log -- docs/campaign-manager-*.md` has them if the history is ever needed.

**Jump to:** [When an automation ends](#5b-when-an-automation-ends) · [Edge-case reference](#9-edge-case-reference) · [Known gaps](#12-known-gaps--parked)
· [Config](#10-configuration) · [Operating it](#11-operating-it)

---

## 1. What it is

Two different things live under "ads", and conflating them causes confusion:

|             | **Ads Analytics** (`/ads`)                 | **Campaign Manager** (`/campaign-manager`)               |
| ----------- | ------------------------------------------ | -------------------------------------------------------- |
| Purpose     | Report on paid activity (spend, RoAS, SoV) | **Act on** the marketplace — change budgets & bids       |
| Data source | Scraped tables                             | Live marketplace API via a logged-in session             |
| Direction   | Read-only                                  | Read **and write**                                       |
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
4. **The choke point** — `writes.py`. The _only_ code that mutates the marketplace.
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
├── config.py         guardrail bounds, dry-run default, drift + settle knobs (env-overridable)
├── logs.py           structured, dry-run-aware logging helpers
├── repo.py           all DB access — rules, runtime, run log, lifecycle markers (tenant + platform scoped)
├── window.py         WHEN a rule applies — windows, expiry, the calendar axis (pure; the only copy)
├── lifecycle.py      what an automation's END means — settle-once, the sweep, lifecycle History (pure)
├── writes.py         THE CHOKE POINT — guardrails + the only path to a mutation
├── budget.py         budget scheduler engine (+ campaign start/stop, + settling ended schedules)
├── bid.py            bid optimizer engine (+ the end-of-window reset run, + settling ended rules)
├── reconciler.py     rules → job_schedules (pure planning + idempotent apply) + the lifecycle sweep
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

| Lane          | Jobs                                                                             | Why                                                 |
| ------------- | -------------------------------------------------------------------------------- | --------------------------------------------------- |
| `cm_bid`      | `cm.bid_optimizer`                                                               | The control loop. Isolated so nothing can starve it |
| `cm_ops`      | `cm.budget_scheduler`, `cm.set_budget`, `cm.set_activation`, `cm.sync_campaigns` | Latency-tolerant, share one browser's worth of RAM  |
| `interactive` | `cm.reconcile`                                                                   | No browser at all — it only writes our own rows     |

**`cm_bid` and `cm_ops` run at the same time.** That parallelism is the source of several ordering
subtleties below — most importantly that both engines issue _whole-campaign_ PUTs.

### Job types

| Job type              | Lane          | Params                       | What it does                                                           |
| --------------------- | ------------- | ---------------------------- | ---------------------------------------------------------------------- |
| `cm.budget_scheduler` | `cm_ops`      | `live`                       | Apply the budget (and start/stop) that matches _now_                   |
| `cm.bid_optimizer`    | `cm_bid`      | `live`, `reset`              | One optimizer pass; `reset` = the end-of-window reset + settle pass    |
| `cm.reconcile`        | `interactive` | `live`                       | Recompile rules → `job_schedules`; sweep lifecycle markers             |
| `cm.set_budget`       | `cm_ops`      | `campaign`, `budget`, `live` | On-demand budget write                                                 |
| `cm.set_activation`   | `cm_ops`      | `campaign`, `action`, `live` | On-demand start/stop                                                   |
| `cm.sync_campaigns`   | `cm_ops`      | `days`                       | Re-read the account's campaigns + statuses into the catalogue (a READ) |

---

## 4. Data model

All tables are `(tenant_id, platform)` scoped.

| Table                  | Holds                                                                                  |
| ---------------------- | -------------------------------------------------------------------------------------- |
| `cm_budget_schedules`  | One per campaign: `default_budget`, `stop_after_window`, `state`                       |
| `cm_budget_rules`      | Windows on a schedule: budget + timing (recurring or once)                             |
| `cm_bid_rules`         | Keyword bid config: `target_position`, `min_bid`, `max_bid`, window, measurement store |
| `cm_bid_runtime`       | System state, 1:1 with a bid rule (below)                                              |
| `cm_platform_accounts` | `advertiser_id` + **`live_armed`** (the per-tenant arming switch)                      |
| `cm_run_log`           | Slim append-only history for the UI                                                    |
| `cm_city_stores`       | The frozen **measurement store set** per city — ranks 1–3 (1 = anchor), a global set (`tenant_id` NULL) a client can replace whole; see [7.6c](#76c-where-a-rule-measures--the-city-registry) |
| `cm_store_stock`       | Stock cache: our products at each measurement store, with availability, from one brand search per store (~hourly) |
| `cm_bid_store_reads`   | Append-only: what each store showed on each bid tick (verdict, position, bid in force, which store bound the decision); 30-day retention |

**One schedule per (tenant, platform, campaign)** is a DB constraint — a campaign has one everyday
budget, and two automations for it could only contradict each other. Extra windows go on the
existing schedule as rules.

**Lifecycle columns** on `cm_bid_rules` and `cm_budget_schedules` — `ended_at`, `settled_at`,
`settle_attempts` (migration `c1e5a9d3f7b2`) — record when an automation ended and whether its final
teardown landed. Only `settled_at` / `settle_attempts` ever change what an engine does; see
[5b](#5b-when-an-automation-ends).

### `cm_bid_runtime` — the system's memory

| Column                 | Meaning                                                                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `last_cpm`             | The bid as we last set it                                                                                                                  |
| `last_position`        | The position observed last tick — used for two-tick confirmations                                                                          |
| `last_bid_updated_at`  | Drives the reflection HOLD                                                                                                                 |
| `last_holding_cpm`     | The last bid observed **holding** target. The precise snap-back price                                                                      |
| `drift_paused_until`   | When shaving may resume after an overshoot                                                                                                 |
| `effective_target`     | The relaxed target, when the real one is unreachable at `max_bid`                                                                          |
| `raise_step`           | The last raise size. Escalates while the position refuses to move, resets when it does                                                     |
| `effective_at_max_bid` | The ceiling `effective_target` was concluded at — makes edits self-healing                                                                 |
| `updated_at`           | Stamped whenever a tick persists runtime. **This is how "first tick of this window" is detected**, which is why no extra column was needed |

`cm_run_log` is append-only and needs a retention policy eventually. Verbose narration goes to
Cloud Logging, not the DB.

### Tables it READS but does not own

The campaign manager owns the `cm_*` tables above. It also reads things filled by the daily
marketplace scrapes and by `cli sync` — deliberately not copied into a `cm_*` table, because a second
copy would drift from the one the scraper maintains. Each marketplace has its own catalogue pair,
picked by ONE mapping (`repo._catalog(platform)`), never an `if platform ==` at a call site.

| Table                                                       | Holds                                                                                                                               | Filled by                      |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| `blinkit_ad_campaigns`                                      | Blinkit's campaign catalogue, plus its city targeting (`region_type`, `cities`), budget, `pacing_type` and spend-to-date            | daily marketing scrape         |
| `blinkit_ad_campaign_keywords`                              | Blinkit's published bid range per (campaign, keyword, match type) — `min_bid`, `max_bid`, `suggested_*`, `keyword_searches`         | daily marketing scrape         |
| `zepto_ad_campaigns`                                        | Zepto's campaign catalogue (**product ads only** — Zepto's list returns nothing else): type + bidding mode, budget, dates, city targeting (`city_targeting` ALL/MANUAL + `cities`), products | daily `scrape zepto --ads`; list fields also by `cm sync-campaigns -m zepto` |
| `zepto_ad_campaign_keywords`                                | Zepto's keywords per (campaign, keyword, match type): live bid, published `min_bid`, `is_negative`                                  | daily `scrape zepto --ads`     |
| `zepto_ad_campaign_daily`                                   | Zepto's daily metrics — read by the CM only for the TYPE of campaigns the catalogue lacks (Display), so they are refused, not "unseen" | daily `scrape zepto --ads`     |
| `cities` · `city_aliases` · `marketplace_locations.city_id` | The canonical city registry — what turns a campaign's city targeting into a real store to measure at                                | `cli cities seed` + `cli sync` |

⚠️ These are for the **UI**. The engine re-reads the bid floor live at write time (§7.6) — the
scraped copy can be up to a day old, and it is the number that decides what gets written to a real
account.

---

## 5. Scheduling — the reconciler

Rules do not poll. On any rule change the API enqueues `cm.reconcile`, which compiles the current
rules into `job_schedules` rows with deterministic names, idempotently (create missing / update
changed / delete no-longer-wanted). Only rows matching `auto:cm:<kind>:<tenant>:<platform>:…` for
the current platform are ever touched — manual schedules and other marketplaces are never deleted.

What it produces:

| Schedule          | Cron                                               | Purpose                                                                                                                     |
| ----------------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Budget boundaries | one per distinct rule start/end time               | Apply the budget that matches now. A rule whose last window has closed contributes none                                     |
| Safety poll       | hourly                                             | Catch drift **inside a window**, a revert that never landed after one closed (§6a), and the budget settle pass while an ended schedule's teardown has not landed (§5b) |
| `once` fires      | one-shots, deduped by time                         | Apply at the window start, revert at the end                                                                                |
| Bid optimizer     | `*/15` within the merged active hours              | The control loop. A one-time overnight window also gets the next day's cron for its tail                                    |
| Bid reset         | daily at each window's stop, **fired 1 min early** | De-escalate closed keywords to `min_bid`                                                                                    |
| Bid settle pass   | hourly at :37, **only while a rule needs settling** | Re-floor a rule that ended without its final reset landing (≤3 tries, ≤24 h after the close, §5b) |
| Cleanup           | daily 04:00                                        | Self-reconcile to prune expired schedules                                                                                   |

**Why the bid reset fires a minute early.** `cm_bid` and `cm_ops` are parallel lanes, so a reset
scheduled on the same minute as a budget window's stop races the budget engine — and once that
engine stops the campaign, a bid write may be refused. One minute of lead makes the ordering
deterministic with no cross-lane coordination. The engine compensates with a **2-minute
look-ahead** (`RESET_LOOKAHEAD_MINUTES`) so the early fire still sees the window as closed; the
look-ahead must stay larger than the lead.

**A `once` bid rule gets its own date-bound cron** (`*/15 h <day> <month> *`) so it can never recur.
An overnight one-time window's post-midnight tail goes on the **next** day's cron — pinned to the start
date alone, those hours never ran.

**An automation whose last window has closed schedules nothing** — no boundaries, no optimizer cron, no
reset — except the settle passes while its final teardown has not landed (§5b). There is no separate
expiry fire any more: the last window's own end is the teardown. So the daily cleanup really does prune
an ended automation's crons; it used to derive the same crons again.

---

## 5b. When an automation ends

Found 2026-09-10: automations that had **ended** kept acting. The end-of-window bid reset floored every
rule that was _not in its window_ — an ended rule is never in its window, so every reset fire of any
automation re-floored all of them — and the budget engine, finding no rule to match on an ended schedule,
wrote its `default_budget` every hour. On Dobra that replaced a budget someone had set by hand, two days
after the automation's only window. "Ended" existed only as a label the API computed; no engine could see
it.

### Two axes

| Axis         | Values                                                                  | Stored? | Decided by                        |
| ------------ | ----------------------------------------------------------------------- | ------- | --------------------------------- |
| **User**     | `active` / `paused` (bid rule) · `active` / `stopped` (budget schedule) | yes     | a person                          |
| **Calendar** | `scheduled` / `running` / `ended`                                       | derived | the dates, at `now` (`window.py`) |

The UI label is a projection: a non-`active` user state wins, otherwise the calendar state shows.
**`running` is calendar-only** — nobody can choose it. The two are never folded into one column: a rule
can be paused _and_ ended, and Pause and Resume need both facts.

### `window.py` — the one implementation

Window matching used to live in four places (`bid._in_window`, `budget._matches_rule`, the API's
`_expired`, the reconciler) with four ideas of when a window is over. `campaign_manager/window.py` is now
the only copy: `in_window`, `window_start`, `window_close`, `just_closed`, `last_window_close`,
`is_expired`, `calendar_state`. The engines keep their own field names through one-line adapters.

- **`is_expired` is minute-precise** for both rule types: ended once the _last_ window has closed.
  Recurring rules used to be date-granular — live until the midnight after their last window, while an
  overnight tail past `end_date` was cut off early. A rule that can never open (no date, an inverted
  range, weekdays nothing matches) counts as ended.
- Equivalence with the code it replaced is pinned by `tests/test_window_equivalence.py` against outputs
  recorded from that code (1,217 rule shapes × 25 boundary instants). The answers changed on purpose are
  held to a brute-force oracle instead.
- Times and dates are compared as strings, which is only correct for zero-padded `HH:MM` and
  `YYYY-MM-DD` — so the API refuses anything else (422).

### Selection is explicit

`repo.get_bid_rules` / `get_budget_schedules` take **required** `state=` and `calendar=` keywords
(`repo.ANY_STATE` / `repo.ANY_CALENDAR` where a caller wants everything). Every engine used to filter on
`state` and none on the calendar; now "which automations" is written at every call site.

### End-of-window actions fire on the edge

| Engine     | Acts on                                                                                                                       |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Bid reset  | Rules whose window **just closed** (`window.just_closed`; look-back = misfire grace + look-ahead) — never "not in its window" |
| Budget     | Schedules with something to do (`budget._has_work`): a window open, one just closed, a close still owed its revert, or a final teardown to settle |
| Reconciler | Only rules with windows left produce crons; the hourly poll only for recurring rules with windows left                        |
| Budget engine (§6a) | It acts inside a window and at a close, never between windows — a live schedule stopped re-asserting its default every hour too |

The budget check runs before sign-in, so a client whose automations have all ended does not log in to do
nothing.

### Settle-once — the safety net

Firing on the edge loses one thing the old "fire forever" behaviour had by accident: a _missed_ final
fire used to be repaired by the next one. Settle-once puts that back, bounded.

| Column            | Kind                            | Written by                              | Read by                       |
| ----------------- | ------------------------------- | --------------------------------------- | ----------------------------- |
| `ended_at`        | materialization — derivable     | the reconciler's sweep                  | UI, SQL — **never an engine** |
| `settled_at`      | fact: the final teardown landed | the engine run that performed it        | engines, reconciler           |
| `settle_attempts` | fact                            | engine runs whose final teardown failed | engines, reconciler           |

- **Final teardown** = the bid back to its floor; the budget back to `default_budget` and the campaign
  stopped if `stop_after_window`. Only a **live** run can latch it.
- **A latch covers an ending only while `settled_at >= that ending's close`.** Reopening needs no
  unlatching: a later ending is unsettled by construction.
- **Needs settling** (`lifecycle.needs_settle`): `active` · ended · not covered by a latch ·
  `settle_attempts < CM_SETTLE_MAX_ATTEMPTS` (3) · within `CM_SETTLE_MAX_AGE_HOURS` (24) of the close.
  Past that a person has had time to take over, and tearing down would overwrite their decision.
- **Paused and stopped automations never settle automatically** — the user's choice outranks the
  calendar. Reset is how a person tears one down.
- The **budget** hourly poll and a **bid** settle pass (`auto:cm:bid:…:settle`, hourly at :37) exist only
  while something needs settling. A settle pass does exactly what the missed run would have done: revert,
  then stop if the toggle is on.
- The **reconciler's sweep** runs on every reconcile: it sets `ended_at` to the close, clears it when the
  dates move forward, and clears latches and attempts that no longer apply. Only changed rows are written.
- Every step is in History (§9b): `ended`, `settled` (Finished), `settle-failed` (Couldn't finish),
  `reopened`.

**Migration `c1e5a9d3f7b2`** added the three columns and stamped `settled_at` = the migration time
(2026-09-10 18:45:26) on every existing row, so no ending that had already happened is torn down
retroactively.

### Reopening

Moving an ended automation's dates forward is all it takes. The engines recompute the calendar, so it is
live at once; the edit's reconcile restores its crons, clears the old ending and writes a `reopened` row;
and its next ending is covered by the safety net even before that reconcile runs. Editing an ended
automation _without_ moving its dates is refused (400, "move its dates forward to run it again").
Resume stays refused on an ended rule, because moving the dates is the thing that makes it runnable.

---

## 6. The budget engine

Each run, for every schedule: work out what should be true _now_, read the campaign, write if it
differs.

`plan_for_now` returns `(budget, state, reason)` where `state` has three answers:

- **`running`** — a rule is active. Starting is unconditional: a campaign with a budget window is
  meant to run during it, so finding it stopped and leaving it stopped would silently do nothing.
- **`paused`** — a window just ended _and_ the schedule opted in via `stop_after_window`.
- **`None`** — the campaign's run state is none of our business right now. With the toggle off this
  is the only non-running answer, so an existing schedule never has its status touched at all.

The first matching rule wins, ordered by rule id — oldest wins, which is stable and explainable
("the one you made first takes precedence").

`_window_just_ended` probes a **range**, not a single instant: a point probe silently missed any
window shorter than the misfire grace, and a late fire broke it the same way.

### 6a. Between windows, the budget is not ours (2026-09-12)

`default_budget` used to be the answer to "no rule matches", so every fire outside a window
re-asserted it — not once at the close, but for as long as the schedule existed. A budget set by
hand at 10:00 was gone by 11:00, and the hourly poll signed in to Blinkit around the clock to do it.

The engine now acts on a window's **edges** and inside it, and `plan_for_now` has a third answer —
**None, nothing to enforce**:

| When | What the engine does |
| --- | --- |
| A window is open | Applies that rule's budget, drift included |
| A window just closed (within the misfire grace) | Reverts to `default_budget`, and stops the campaign if `stop_after_window` is on |
| A close whose revert never landed | The **failsafe** — does what that fire would have done, then latches |
| Any other moment | Nothing. The campaign is not read, and if no schedule has work the run never signs in |
| A schedule with **no rules** | Unchanged: holding its default is the whole of what it does |

**The failsafe is a latch, not a timer** (`lifecycle.revert_owed`). `settled_at` means "the most
recent close this schedule has been torn down for", so a close is owed a revert until one lands —
and once it lands, the schedule is silent until the next close. Settle-once (§5b) is the same
question asked of the *last* close, which is why no new column was needed. Two guards keep a repair
from acting on something that was never its business: a close **before the schedule was created**
is not owed, and neither is one more than `CM_SETTLE_MAX_AGE_HOURS` (24 h) old — past that, the
campaign's budget is whatever the days since made it.

**The cost, accepted deliberately:** drift correction outside windows is gone. If Blinkit itself
changes a budget at 10:00, it stands until the window opens. Nothing can tell that apart from a
person choosing a number, and clobbering the person is the worse error.

**An ended schedule is left alone** (§5b): its last close is either latched, or owed one final
teardown that also records the ending in History.

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
steps _up_ from it, so the bid ratchets across days until it pins at `max_bid`.

**All-day rules are the exception** (2026-09-18). Their window closes at midnight and the next
opens the same minute, so a run of consecutive days is **one** window: no floor at midnight, and
a reset only where the run ends. Before this, an every-day rule was floored nightly — "tapioca
chips" went ₹842 → ₹200 at 00:01 and spent two hours climbing back. See §9.1 / §9.6.

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
a poor proxy for _rupee_ distance: the bid→position curve is a staircase with treads
hundreds of rupees wide, so "one slot away" can cost ₹50 or ₹600. Distance simply isn't the
signal. Whether the last raise moved the position is.

Typical climb from a ₹100 floor at the defaults (₹50 / 8% / ×1.5):

| Tick | Bid | Step |
| ---- | --- | ---- |
| 1    | 100 | +50  |
| 2    | 150 | +75  |
| 3    | 225 | +112 |
| 4    | 337 | +168 |
| 5    | 506 | +252 |
| 6    | 758 | +378 |

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
  product match differs. A _failed_ fetch is cached as the failure too — re-scraping a
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

> **The sponsored predicate is shared, not copied** (2026-09-04). "A non-empty
> `ads_campaign_id` under `tracking.common_attributes` means this slot was bought" now
> lives once, in `scraper/platforms/blinkit/public_data/ads.py`, and both readers call it:
> this scraper and the public keyword scrape (which had never read the marker at all —
> every Blinkit listing ever stored says organic). Two definitions of "sponsored" drifting
> apart is not hypothetical here; a second copy of the payload builder is exactly how the
> `city_ids` bug hid for months (§8.2b).
>
> ⚠️ The same key appears in `widget_meta` / `entry_source_map` on promotional BANNERS.
> Reading it off the snippet at large — rather than off a product's `common_attributes` —
> would flag a banner carousel as a sponsored product.
>
> `_parse_snippets` now also returns `campaign_id`, i.e. WHOSE ad it is. Nothing acts on it
> yet: `match_position` treats any sponsored slot matching our product as ours, which is
> right today (we match on our own PIDs and brand tokens) but cannot tell us apart from a
> reseller advertising the same SKU. Carrying the id is what makes that check possible.

### 7.3 Holding — "at target **or better**"

Being better than target is a **success, not an error to correct.** Sponsored slots sit on a sparse
lattice — ~89% of observed positions were 1/5/9/13/17 — so a target of 3 is frequently unreachable,
and demanding exact equality would mean never settling.

### 7.4 Drift-down — the cheapest price that holds

Once holding, shave `CM_BID_DRIFT_PCT`% off the bid each tick. When a shave goes one step too far
and the position is lost, snap back to `last_holding_cpm` and stop shaving for
`CM_BID_DRIFT_PAUSE_MINUTES`.

Why it matters: the climb stops at the _first_ bid that worked, which can be far above the real
threshold. Observed in practice — a keyword climbed ₹350 → ₹900 with the position stuck at 15 the
whole way, then showed position 15 again at ₹300. ₹600 bought nothing.

Four rules make it safe:

- **Two consecutive holds before shaving.** A single reading was unreliable in ~28% of repeatedly
  measured bid levels. It also gives a fresh raise one tick to prove itself before we undo it.
- **Overshoot vs market move** (`is_recovery`). Off target at a bid _below_ one known to hold = our
  own drift went too far → snap back **precisely** to it. Off target at or above it = a competitor
  moved → normal raise. A step-raise from ₹299 would jump to ₹399 and overshoot the known-good ₹322
  by ₹77, then spend an hour drifting back down.
- **The pause is a ONE-WAY valve.** It gates the decrease only. Raises are never blocked, so being
  outbid during peak hours is answered on the very next tick.
- **`last_holding_cpm` is refreshed on every holding tick**, not just the first, so the snap-back
  tracks the market instead of returning to a price that worked an hour ago.

⚠️ **The default is `CM_BID_DRIFT_PCT=7` — drift is ARMED and running on live campaigns.**
This paragraph used to say the default was `0`; it was wrong, and wrong in the direction that
matters: a reader would conclude cost minimisation was switched off when it is not. Setting it
to `0` is a **true revert** — at 0 the decision logic is behaviourally identical to pre-drift
(freeze at target, step down only when strictly better) — so it remains the kill switch, but
it is not where the system ships.

### 7.5 Unreachable target

Pinned at `max_bid` with the target still missed, the old behaviour recomputed `max_bid`, had the
no-op guardrail reject it, and wrote a junk `skip` row — every 15 minutes, all day, paying the
ceiling for a position the ceiling did not buy.

Now the position actually achieved becomes the **working target**, and drift finds the cheapest bid
that holds _it_.

- **Two confirmations before relaxing.** One bad scrape must not relax a target for a whole window.
- **Relaxes to the current position, not the better of the two.** Relaxing too far self-corrects
  (drift just optimises the cheaper position); relaxing not far enough puts us straight back to
  pinning at max and doing nothing.
- **`effective_at_max_bid` makes edits self-healing.** The relaxed target is void the moment the
  rule's `max_bid` differs from the ceiling it was concluded at. **Raising the ceiling is the
  dangerous direction** — a stale relaxed target would have the optimizer keep drifting _down_ right
  after being handed more room to climb.
- **Cleared at window open**, so every day re-climbs and retries the real target from scratch.
  ⚠️ Except an all-day rule, whose window opens only at the start of its run of days: its
  relaxed target holds until a `max_bid` edit, a resume, or the next run.

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
still receives a plain int and never has to know the field is optional. A rule that _does_
set a ceiling is capped at the lower of the two, which also catches a typo'd `max_bid`.

`CM_BID_MAX_ABSOLUTE` is a **runaway guard, not a tuning knob** — set well above any
realistic CPM (₹10,000 vs the ₹900 high-water mark) so it never binds in normal operation.
Real spend is bounded by the daily budget long before it: at a ₹10,000 CPM a ₹2,000 budget
is gone in 200 impressions and the campaign goes ON_HOLD.

✅ The old "a flat ₹100/tick tops out near ₹2,900 per window" limitation is **gone** — the
escalating raise (§7.2) reaches ₹10,000 in about 12 ticks, so an unbounded rule can now
actually reach a high target inside a window.

### 7.6b The marketplace's own floor

`min_bid` has the mirror-image problem, and it is the one the client actually raised: **Blinkit
sets its own minimum bid, per keyword.** It is not one number for the account — measured on Dobra,
`mango` floors at ₹50, `soda` at ₹100, `slice` at ₹200 and `cocktail` at ₹400, _two of those inside
one campaign_. A rule written weeks ago cannot know today's.

`effective_floor` is the sibling of `resolve_ceiling` and is resolved at the same point, under the
same rule — **`rule.min_bid` must not be read below that line**:

```
min_bid = max(rule.min_bid, marketplace_floor)   if the floor is known
          else rule.min_bid
```

The two directions mean different things and both are respected. A rule's `min_bid` is the
**client's** floor — a client who never wants to bid under ₹500 keeps that where Blinkit would
allow ₹200. The marketplace floor is what the auction will actually accept: below it the write is
refused or silently raised, so a rule set under it is not a cheap bid, it is an **ineffective** one.

An unknown floor (`None`) falls back to the rule's own value. That covers a failed lookup and a
keyword the campaign does not carry yet — refusing to bid because a _read_ failed would be worse
than bidding at the configured minimum.

**Read live, not from the scrape.** The nightly copy in `blinkit_ad_campaign_keywords` feeds the
setup form; the engine re-reads at write time because this is the number that decides what lands on
a real account. It costs **one request per campaign per run** — the endpoint takes the whole keyword
list at once (verified: 130 floors in a single call for a 65-keyword campaign), so it does not scale
with keyword count.

⚠️ It applies to the **end-of-window reset** too (§7.8). That write moves the bid _down_, so below
the floor it is refused — and the keyword would sit at its high in-window bid all night.

⚠️ `min_cpm_config`, which Blinkit returns alongside every campaign detail, is **not** this number.
See §8.6.

### 7.6c Where a rule measures — the city registry

A bid rule reads its keyword's position at **one real dark store**, so it needs a city. That city
used to be typed by hand, with nothing checking it against the campaign: a rule could measure in a
city the campaign does not advertise in, and nothing anywhere would say so.

The campaign now supplies it. `region_type` is `PAN_INDIA` or `CITY`; `region_ids` are resolved to
names at scrape time. One city auto-fills, several become a dropdown, pan-India leaves the choice
open.

Turning that name into a store needed a shared vocabulary, because **the same place is spelled
differently on every surface** — Blinkit's ads say `Gurugram`, Blinkit's _seller_ dashboard says
`Gurgaon`, our store catalog says `hr-ncr`, Zepto's says `delhi ncr`. The mismatch is per **surface**,
not per marketplace, so translating source→source would need a rule per pair.

Instead there is one canonical `cities` list, `city_aliases` keyed `<marketplace>:<surface>`, and —
the part that makes it work — **each store carries its own `city_id`, derived from its pincode**.
Grouped catalog names then stop mattering: `hr-ncr`'s 77 stores individually resolve to Gurugram,
and Zepto's `delhi ncr` blob splits per store with no Zepto-specific rule at all.

Resolution order, and the order is the design: **alias → canonical name → pincode**. Explicit human
decisions beat derived ones; pincode is last but is the only thing that can split a grouped name. No
match leaves `city_id` NULL and the store is simply not offered — visible and recoverable, unlike a
guess that would silently measure in the wrong city.

⚠️ A grouped name gets **no alias**, deliberately. `up-ncr` is not one city — it splits into Noida
(`2013`) and Ghaziabad (`2010`,`2011`) by pincode, and an alias can only point at one city. Four
digits, because `201xxx` alone cannot separate them.

Maintenance is the ~14 exceptions in `config.xlsx`'s `city_map` sheet; the other 228 cities match by
name. `cli cities seed` builds the list, `cli sync` applies the sheet and tags stores, `cli cities
status` reports what still resolves to nothing.

**Zepto's ad spellings** reach the registry the same way. A Zepto campaign's cities come in Zepto's
ADS spelling, which can differ from both our canonical name and Zepto's own store catalogue: city 498
is `Belgaum` to us, `belagavi` in Zepto's store catalogue (`zepto:catalog` alias) and **`Belgavi`**
in its ads (`zepto:ads` alias, added 2026-09-23 — the first `:ads` row of any marketplace; Blinkit's ad
names all match canonical ones). All 9 of Brik Oven's Zepto cities resolve. `cli cities seed` reads
**Blinkit's** directory only and refuses `--mp zepto`: Zepto publishes no account-independent city
list (its `targeting-options` is scoped to one brand), so seeding from it would shrink the registry.

#### The stores inside the city — a frozen set, and stock

A city is still not a store. Until 2026-09-11 the store was the city's **lowest `merchant_id`** —
deterministic, but a store nobody chose — copied onto the rule as lat/lon at save time, so moving it
meant editing every rule.

`cm_city_stores` (migration `d7c3e9a1f5b2`) freezes a **ranked set** of up to three stores per
(marketplace, city): rank 1 is the **anchor**, ranks 2–3 **validate** it. Two layers:

| Layer      | `tenant_id` | Set from                            | Wins                                  |
| ---------- | ----------- | ----------------------------------- | ------------------------------------- |
| Client set | the client  | `cm stores set -t <id> --rank N`    | first — **replaces the global set whole** |
| Global set | NULL        | `cm stores set --global --rank N`   | second                                |

A client's set is never mixed with the global one rank by rank: that could put one store in twice, or
pair a client's anchor with validators chosen for everyone else. A client with only rank 1 set measures
at that one store.

**CLI only, deliberately** (Deepansh, 2026-09-11): no API and no UI until this is proven in practice.
Rules created from the dashboard still record their city, so a set configured from the CLI reaches them.

A rule saved **by city** carries `cm_bid_rules.city_id` and **follows** that city's set, resolved on every
run (`bid.measurement_stores`), so changing a set moves every automation measuring there on the next
tick, with no rule edits. A rule saved by an explicit store (`location_id`, `--lat/--lon`) has `city_id`
NULL and stays **pinned** to that one store.

**The goal is the target position at every store where the campaign can actually be sold** (Deepansh,
2026-09-16 — "all", not "most"). Each tick reads the keyword at every store in the set and acts on the
**worst** store that counts. "All eligible stores at target" and "the worst eligible store at target" are
the same statement, so `compute_bid`'s decision logic and its tests are unchanged (it only gained an
optional `position_text`, so "not on the page" is worded as such rather than as a placeholder number):
it is handed the binding store's
position (`campaign_manager/coverage.py`). Reading every store every tick also means every reading in a
decision was taken at the same moment and the same bid. History names the store holding a bid up:
"… — worst of 3 stores is Block C".

**Stock** (`campaign_manager/stock.py`). Once per run, before any decision, one **brand search** per store
lists our catalogue there with availability (`cart_item.inventory` + `is_sold_out`, sold-out items
included), cached in `cm_store_stock` for `CM_STOCK_MAX_AGE_MINUTES`. One read serves every keyword and
campaign at the store. Product ids join a campaign's product list **exactly** — verified against Dobra
2026-09-17: the ads API's campaign product id, the catalogue's `cart_item.product_id` and the position
search's `identity.id` are one id space. Per store, the campaign is:

| Eligibility  | Test                                                         | Effect                    |
| ------------ | ------------------------------------------------------------ | ------------------------- |
| eligible     | ≥1 campaign product listed **and** in stock                   | read; counts              |
| out of stock | listed, none in stock, and the read saw our whole brand       | **not read; excluded**    |
| not listed   | none listed, and the read saw our whole brand                 | **not read; excluded**    |
| unknown      | no read, a failed or partial one, or no campaign product ids  | read; **counts**          |

⚠️ **Only confirmed absence of stock excludes a store.** Not being on the keyword's results page is a
ranking fact — exactly the case that must bid up — and "unknown" never becomes "sold out", or a campaign
climbing from its floor would be stopped. Every store excluded → **no bid change**, logged as a stock
problem, not a bidding one. A failed stock read is not cached, so the next run tries again; `stock.load`
never raises.

⚠️ **The brand search pads itself with other brands.** Following that tail walked 219 products (soda
water, baking soda…) and hit HTTP 429 in recon, so the read is capped at the watchlist's `brand_cap`
(default 48). A capped or 429-truncated read may not have reached all our products, so it is **complete**
only if it ran out cleanly before the cap, or its last 10 results are all other brands — one foreign
product mid-block proves nothing (a competitor's chips sat between our own combos). Only a complete read
can conclude "not listed" or "out of stock" (`blinkit/catalog.py::summarise`). A search returning none of
our products is a failed read, not a store that sells nothing.

**A store we can't trust this tick gets no vote this tick** (Deepansh, 2026-09-17 — keep the blast
radius small). A plain failed search was always excluded; the dangerous readings were the ones that
*answered* but misled, because "our ad isn't there" raises the bid. Each of these is now `untrusted`,
logged as "not counted — …", and left out of that tick's decision:

| Reading                                                | Was                                  | Now        |
| ------------------------------------------------------ | ------------------------------------ | ---------- |
| search failed (429, timeout)                           | excluded                             | `error`    |
| search returned **no products at all**                 | placeholder position 1 → "held" → **trim** | `untrusted` |
| page 1 answered, a later page failed, our ad not seen  | "not showing" → **raise**            | `untrusted` (an ad we DID see still counts) |
| the campaign's product list couldn't be read (and no brand name) | "not showing" everywhere → **raise** | `untrusted` |
| stock unknown + our ad not showing, **while another store gives a clear reading** | "not showing" → **raise** | `untrusted` |

A "clear reading" is our ad seen anywhere, or not seen at a store with confirmed stock. When "stock
unknown + not showing" is ALL we know — a new campaign, stock not readable yet — it still counts, so a
climb from the floor is never stopped. Nothing counted and at least one store unusable → no bid change
(an ERROR log only when a search actually failed; an untrusted-only tick is a warning).

**Giving up at the ceiling.** A store with confirmed stock that still doesn't show our ad at `max_bid`
is not a bad reading — the ceiling genuinely can't buy a slot there, and under "all stores at target"
it would hold the bid at the ceiling all window. After `CM_BID_GIVE_UP_TICKS` (2) checks in a row not
showing with the bid already at the ceiling, the store is `gave_up`: not searched, not counted, **for
the rest of that window** ("not chased — …"). It is sticky within the window, lifted by raising
`max_bid` (the give-up bid is then below the new ceiling), and every new window starts fresh. If every
counted store is given up, the bid stays where it is until the window closes (`unwinnable`). History for
this comes from `cm_bid_store_reads` (same dry-run mode only), loaded once per run; if that read fails,
nothing is given up.

**Warnings.** A store that gives no usable reading (`error` / `untrusted`) for
`CM_STORE_PROBLEM_WARN_TICKS` (2) checks in a row logs "Salt Lake has given no usable reading for N
checks in a row — decisions are running without it", every tick until it recovers. WARNING, not ERROR:
it narrows a decision, it is not an outage.

Where a rule measures, in order — the `rule.store` log line names which applied (`store_source`):

1. the client's set, using its stores that are still active catalog stores with coordinates;
2. the global set, same condition;
3. the store saved on the rule (`rule`) — **a city with nothing frozen moves nobody**; its stock is looked
   up via the catalog store at those coordinates;
4. the Bengaluru fallback (`default`), only for a rule with no store at all (stock unknown).

A new rule in a city with nothing frozen is still saved at the lowest `merchant_id` (`catalog`).

Every store read lands in `cm_bid_store_reads` (verdict, position, eligibility, the bid in force, whether it
bound the decision), trimmed to `CM_STORE_READS_RETENTION_DAYS` as it is written. `cm stores stock` shows
the stock cache.

⚠️ **Changing a set clears the engine's memory** for every rule it affects — the same `_RUNTIME_MEMORY`
set Resume clears. A different anchor reads different positions, and different validators change which
store is worst, so last position, holding price, relaxed target and escalation step would each describe
another set. The rules' `lat` / `lon` / `location_name` are re-snapshotted to the new anchor. Setting a
rank to the store it already holds changes nothing and clears nothing.

**Fewer stores without a deploy:** `cm stores clear --rank 2` / `--rank 3` drops a city back to its anchor.
Stock still applies to the anchor.

Keyed by `merchant_id`, not `marketplace_locations.id`, because `cli sync --prune` deletes and re-creates
catalog rows. A frozen store that leaves the catalog or closes is skipped (and logged), never honoured —
the set's lowest remaining rank becomes the anchor.

| Setting                          | Default | Meaning                                                    |
| -------------------------------- | ------- | ---------------------------------------------------------- |
| `CM_BID_MAX_STORES`              | 3       | ranks per city; `CM_ZEPTO_BID_MAX_STORES` = 1              |
| `CM_STOCK_MAX_AGE_MINUTES`       | 60      | reuse a store's stock read for this long                   |
| `CM_STOCK_DEFAULT_BRAND_CAP`     | 48      | brand-search cap when the watchlist sets no `brand_cap`    |
| `CM_STORE_READS_RETENTION_DAYS`  | 30      | trim `cm_bid_store_reads`                                  |
| `CM_BID_GIVE_UP_TICKS`           | 2       | checks not showing at the ceiling before a store is given up for the window; 0 disables |
| `CM_STORE_PROBLEM_WARN_TICKS`    | 2       | consecutive unusable readings before a store is warned about |

⚠️ **Zepto stays on one store** — its anonymous search allows ~4-5 requests a minute — and has no
catalogue read, so its stock is always unknown and it behaves exactly as before. It also still resolves
the store from the coordinate once per store per run (`get_page`): passing the frozen `merchant_id` would
skip that but drops the secondary hub ids the lookup returns, which can change what a search shows —
left alone until measured.

### 7.7 Bounds are invariants

`min_bid` / `max_bid` are enforced **every tick** against the live bid, not merely clamped onto a
value the optimizer chose to change. They used to be applied only to a computed change, so when the
decision was "no change" — the common case once a target is held — lowering `max_bid` below the live
bid did nothing at all until the next window opened, leaving the campaign a full day over its
ceiling. An out-of-bounds live bid is now written back into range before the position scrape.

### 7.8 The end-of-window reset

`cm.bid_optimizer --reset` writes each **just-closed** keyword back to `min_bid`. No position scrape, so
it's cheap. It skips keywords still covered by another in-window rule.

**The edge, not the level** (§5b). It used to take every rule _not in its window_ — which included every
rule that had ended and every rule not yet started, so each reset fire re-floored them all. Now only a
window that closed within the look-back (misfire grace 5 min + look-ahead 2 min) counts. The same run
settles rules whose final reset never landed, with their own History wording; a floor that is an
automation's last teardown latches `settled_at` (a bid already at the floor counts as landed).

It has **no status gate**: `held` (ON_HOLD) is a _running_ campaign whose budget ran out and the
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

| Guardrail          | Rule                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------- |
| Budget bounds      | Reject outside `[CM_MIN_BUDGET, CM_MAX_BUDGET]`. A bug computing `budget=0` must be refused, never sent       |
| Bid clamp          | Clamp into `[min_bid, max_bid]` — defence in depth                                                            |
| No-op skip         | Computed value equals current → skip the write                                                                |
| Rate limit         | Max `CM_MAX_WRITES_PER_WINDOW` successful writes per **keyword** per `CM_RATE_WINDOW_MINUTES`                 |
| Status transitions | A table, not a scalar bound — see below                                                                       |
| Live arming        | A live run requires a stored `advertiser_id`, injected onto the client so the write carries the right account |

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
- **Every field the builder does not read off the campaign, it overwrites with whatever it
  hardcodes.** That is not a theoretical risk — see 8.2b.

### 8.2b City targeting — the field that got overwritten (fixed 2026-09-03)

`campaign_targeting.city_ids` is rewritten by _all three_ write paths. `"-1"` means **all of
India**, and Blinkit accepts it silently on a campaign that was targeted at one city.

`update_keyword_bids` sent a hardcoded `"city_ids": "-1"`, while `update_campaign` and
`restart.build` each read `region_ids` off the campaign. So from mid-July every **keyword-bid**
write silently broadened its campaign to pan-India. Budget writes and restarts were never
affected — which is why it survived so long, and how it was finally confirmed:

| campaign             | bid writes | budget / restart writes | targeting after |
| -------------------- | ---------- | ----------------------- | --------------- |
| `Sprite [Delhi NCR]` | 1          | 11 / 4                  | **PAN_INDIA**   |
| `Sprite [BLR]`       | 0          | 5 / 1                   | CITY (1)        |
| `Sprite [Mumbai]`    | 0          | 9 / 1                   | CITY (1)        |

Across the whole account: **9 of 9** campaigns that ever took a live bid write were pan-India;
**all 7** the manager had touched that still held city targeting had taken none — one of them
after 23 budget writes and 10 restarts. The legacy `ad_campaigns` optimizer carried the same
hardcode and cost campaign 568887 its Delhi-NCR targeting on 2026-07-13.

There is now **one** implementation — `payload.city_ids`, in
[`marketplaces/blinkit/payload.py`](../backend/campaign_manager/marketplaces/blinkit/payload.py)
— and all three builders call it. It lives beside its own inverse deliberately (§8.2c): a
field whose writer and reader sit in different files is free to drift apart, which is this
bug in miniature.

It also **fails closed**: a campaign reporting `region_type=CITY` whose `region_ids` cannot
be read raises `writes.WriteRefused` instead of falling back to `-1`. A refused write is
visible; a broadened campaign is not. The choke point catches that one exception type and
turns it into a rejected write — the engines wrap their loops in `try/finally`, so anything
escaping a write aborts the whole run and silently skips every campaign after it. Only
_refusals_ are caught; a dead session still aborts, because continuing would fire the same
broken call at fifty more campaigns.

`tests/test_payload_invariant.py` covers both directions: it greps the builders for the
hardcoded literal, pins the fail-closed cases, and asserts a refusal costs one write rather
than the run. `tests/test_builders_pass_invariant.py` drives the real builders through a
fake transport to prove the check is not so strict that it refuses legitimate writes.

⚠️ **The damage is not self-healing.** A broadened campaign stays broadened until someone
re-enters its cities in the Blinkit dashboard, and our own record of what they were is gone:
the `region_type`/`cities` columns only landed 2026-08-27, after most of the writes. The
campaign names (`[Mumbai]`, `(Hyderabad)`, `[ROI]`) are the best surviving evidence of intent.
`scripts/snapshot_campaign_state.py` captures what is _still_ correct, to a local file — run it
before any work that touches the payload builders.

✅ **`region_type` is never sent, and must stay that way — settled by capture 2026-09-05.**
This used to read "still never sent … what the UI sends for a `CITY` campaign is unknown",
because the only captured dashboard payload came from a pan-India campaign. That unknown sat
on the exact field family that broadened nine live campaigns, so it was worth closing properly.

**How.** Playwright drove Blinkit's own dashboard on campaign 574687 (PRODUCT_LISTING,
targeting Mumbai + Pune, `region_ids [2, 787]`) through _Details → Budget details → Edit →
Next → Update Campaign_, with every `PUT`/`PATCH`/`DELETE` intercepted and **aborted before
it left the browser**. The UI composed a real payload; it was never sent. Verified after:
budget still 201, `region_type` still `CITY`, `region_ids` still `[2, 787]`, keyword
`pink toffee` still at ₹201.

**What it says.** `region_type` appears **nowhere** in the dashboard's payload. Its targeting
block is `campaign_targeting.city_ids: "2,787"` and nothing else — byte-identical to ours. So
`region_type` is read-only, derived server-side from `city_ids`, and **adding it to our
payloads would put an unverified field into the write path for no benefit.** Do not.

**The same capture found a real defect** — the one that took every write down six weeks
later. `campaign_start`: the dashboard sends `"7/15/2026"` where we sent `"7/14/2026"`.
`start_ts` is `2026-07-14T18:30:00+00:00`, and 18:30 UTC **is** midnight IST on the 15th —
but `build.fmt_date` stripped the timezone rather than converting it
(`.replace("+00:00", "")`). Every Indian campaign starts at midnight IST: **260 of 260 have a
`start_ts` at ≥18:30 UTC**, so every UPDATE payload carried a start date one day early. The
invariant could not catch it, because both halves were wrong in the same direction — our
output compared against our own derivation of the same field. Self-consistency, which §8.2c
exists to distrust.

🔥 **It stopped being harmless on 2026-09-15.** This paragraph used to end "Blinkit has
evidently ignored it on update". Overnight it stopped ignoring it and began answering
`HTTP 400 ['Start Date of Campaign is not allowed to be changed']`, which kills the **whole
PUT** — so no bid and no budget write landed on any campaign. The break is unusually clean:
last accepted write 23:46, first rejection 00:01, identical payload either side, no deploy
on our side since 12 Sep. Blinkit tightened the validator; nothing of ours moved.

**Fixed the same day.** `fmt_date` converts to IST (`build._ist`) instead of discarding the
offset, and `payload._date_expected` reads the campaign's own date the same way — **both
halves, or neither**: correcting only the builder makes `verify()` refuse every UPDATE
itself, trading Blinkit's rejection for ours. The reader deliberately does NOT call the
formatter; an inverse that borrows the code it checks is the §8.2c blind spot again.
`tests/test_campaign_dates.py` pins all of it, including the `12/31/9999` sentinel
(`18:29:59+00:00` → `23:59:59` IST, one second below `datetime.max`). The 18 bid/budget
golden payloads in `fixtures_blinkit_payloads.json` moved with it; `RESTART` never needed
fixing, because its start date comes from `today`.

Remaining differences are shape, not correctness — our writes work. The dashboard also sends
`image_url`, `preview_image_url`, `store_name`, `collection_id`, `creative_type`,
`highlighted_pids`, and `days_of_week` + `timeslots` inside `campaign_targeting`; we send
`brand_ids`, `infinite_campaign`, `is_extendable`, `pids` and `negative_keywords` instead.
This is the first time both payloads have been compared side by side.

### 8.2c The write invariant — what a PUT may change

Every builder now answers one question before its request goes out:

> Does this payload say the same thing as the campaign we just read, except for the change
> we intended?

[`marketplaces/blinkit/payload.py`](../backend/campaign_manager/marketplaces/blinkit/payload.py)
holds the rules; each builder calls `verify()` immediately before the PUT, and a failure
raises `WriteRefused` — caught at the choke point, so one bad campaign costs one write
rather than the run.

**It compares against the campaign, not against another payload.** This is the whole
design, and the obvious cheaper version does not work: building the payload twice (once
with the change, once without) and diffing them is blind to a hardcoded constant, because
both copies contain it. The `-1` bug would have sailed straight through such a check. So
every rule carries an **inverse** — it reads the payload's own value back into the
campaign's vocabulary (`"2010,2013"` → `{2010, 2013}`) and compares that to what Blinkit
reported. A constant can only pass if it happens to equal the campaign's real value.
`test_payload_invariant.py::test_a_self_consistency_check_would_not_have_caught_it` pins
the distinction so it cannot be "simplified" away later.

**Coverage: 21 of the 27 fields the builder sends** (§8.2d). The six that remain are
constants or addressing — `source_platform`, `requested_by`, `campaign_request_type`,
`campaign_id`, `is_extendable`, `preview_image_url` — which have no counterpart on the
campaign to compare against, and whose failure mode is a _rejected request_ rather than
silent damage. `test_payload_invariant.py::test_every_derived_field_is_checked` is a
**ratchet**: add a row to the field table and the suite fails until you either write a rule
or state in `UNCHECKABLE` why the field cannot have one. That gap is what let coverage sit
at 8/27 unnoticed.

Two fields are guarded **structurally** rather than against the campaign, because Blinkit
publishes no counterpart:

- **`advertiser_id`** — the account a write lands in. A wrong one spends against someone
  else's account, and `client.get_advertiser_id()` still falls back to the stale pre-split
  `234` when its read comes back without the field. Now refused outright, along with `0` on
  an UPDATE and any non-zero value on a RESTART (AD4).
- **`brand_name`** — compared to the campaign on updates, exempt on RESTART, which blanks it
  deliberately.

Each rule declares how the sent value must relate to the campaign's:

- **EXACT** — identical, for anything where both gaining and losing is damage. City
  targeting is the canonical case: `-1` _adds_ the whole country.
- **NO_LOSS** — the campaign's value must survive; additions are allowed. For collections
  where dropping is the damage and adding is a legitimate operation: a bid write may
  introduce a keyword, but nothing may silently delete one.

Three properties the first version got wrong, found by probing it and now pinned by tests:

|                                                      |                                                                                                                                                                                                                                              |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A field sent as **null** is a value, not an omission | `city_ids: None` was collapsed into "absent" and skipped unexamined                                                                                                                                                                          |
| A **bid** write may not drop keywords                | The first version exempted the keyword rule for bid writes — blinding the check for the exact operation that caused the incident. The rule checks the keyword _set_; a bid write changes a CPM, so it never needed exempting                 |
| A **thin detail** refuses instead of passing         | `_fetch` turns a Blinkit error page into `{}`. Every rule compares against the detail, so an empty one makes the check vacuous — it would wave anything through, exactly when the payload built from that same failed read is most dangerous |

Each write shape declares what it is _allowed_ to change:

| Shape     | May change                               | Because                                                                            |
| --------- | ---------------------------------------- | ---------------------------------------------------------------------------------- |
| `BID`     | the keyword bids                         | that is the call                                                                   |
| `BUDGET`  | the budget                               | that is the call                                                                   |
| `RESTART` | budget, `campaign_start`, `campaign_end` | a restart re-submits the campaign and stamps today + the no-end sentinel (AD4/AD5) |

Three shapes. There was a fourth, `BUDGET_NO_PIDS`, which alone was allowed to rewrite the
**product list** — `adapter.apply_budget` retried a rejected budget write with `pids: ""` to
work around a delisted catalog. **Removed 2026-09-05**, and worth recording why, because the
reasoning generalises.

Tested live 2026-09-04 (campaign 574687, PRODUCT_LISTING, one valid pid):

1. It does **not** clear the products — Blinkit does not read an empty list as "set to
   none". So it was never another instance of the city bug.
2. It does not work either. Blinkit **rejects the whole request** with
   `["Please select atleast one PID"]`. That validator fires on the payload _having_ no
   pids, which an empty list always does — so it could not rescue any `PRODUCT_LISTING`
   write. A safety net that never caught anything.

The deciding argument was not that it was useless but that it was **costing us the
diagnosis**: the retry's rejection replaced the first response, so a failed budget write
reported an error about a payload we invented rather than the one that was asked for. That is
the scorecard pattern — a fallback that cannot fire, whose message stands in for the truth.
`BANNER_LISTING` stayed untested (its pid validator may not apply, the one case where this
could have worked), but none of the 17 such campaigns is under automation, so it could not
help anything we actually write to.

Removing it also removed the only write shape permitted to touch products, so the invariant
got **simpler by one shape** — the tell that the fallback was always the anomaly. In its place
`writes.apply_budget` now logs the marketplace's own reason (`writes._why`), which had been
sitting in the response and going unread all along: a failed write logged `applied=False` and
`₹201 → ₹250`, and nothing about why.

⚠️ **This narrows the blast radius; it does not eliminate it.** A field with no rule is
unchecked, and a field a shape is allowed to change is unchecked for that shape. The
structural fix — building the payload by echoing the read instead of hand-listing fields,
so an un-enumerated field round-trips rather than resetting — is still outstanding. The
invariant is what holds until then, and stays useful afterwards.

### 8.2d The payload is derived, not typed (Layer 1)

The invariant in 8.2c catches a bad payload. This removes the way bad payloads were made.

Until 2026-09-03 each builder spelled the body out as literals — ~26 fields per shape,
every one an author's decision, and a field nobody thought of simply absent, which for a
whole-campaign PUT means _reset_. `city_ids: "-1"` was one such decision.

[`marketplaces/blinkit/build.py`](../backend/campaign_manager/marketplaces/blinkit/build.py)
replaces all three hand-written dicts with one **field table** — a row per field saying
where it goes, how to derive it from the campaign, and which shapes carry it. `build()`
walks the table. Three properties now come from the structure rather than from diligence:

- **A field cannot be forgotten** — nobody types fields any more.
- **A field cannot be quietly hardcoded** — a constant must be an explicit `const(...)` row,
  visible in review, not a literal buried mid-dict.
- **Coverage stops being a maintained list.** The table _is_ the payload.

**It is a refactor, and that is proven, not asserted.**
`tests/test_build_equivalence.py` freezes what the OLD builders produced for 9 campaign
shapes × 4 write types — 36 payloads — and asserts the table reproduces them exactly, down
to types (`502` vs `502.0`, `""` vs `None`). Those fixtures are a record of what shipped,
not a specification of what is right: matching them is what proves nothing changed. The
restart golden test, pinned against a real captured Blinkit payload, also still passes.

#### The dead UI write path is gone

`client.update_campaign_budget_via_ui` — 269 lines that drove the real Blinkit dashboard
with Playwright (find the campaign row, open the edit panel, type a budget, click Update)
and intercepted the resulting PUT — was **deleted on 2026-09-04**. Its only caller was
`ad_campaigns/main.py`, removed with the v1 engine. It was also the one write path the
invariant could never cover, because the payload was Blinkit's own. `client.py` went from
780 lines to 511.

#### What building the table exposed

Writing the derivations down in one place made two long-standing inconsistencies visible
that nobody could have seen while they were spread across three files:

| Found                                                                                                                                                                                                                                                                 | Status                                                                                                                                                                                                                                                                                                               |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **The three builders disagreed about where keywords live.** Bid and restart read nested-first with a top-level fallback; the budget builder read the **top level only** — so on a normal campaign it found none and omitted `keyword_targeting` from the PUT entirely | **Reproduced deliberately.** The omission is evidently safe (budget writes run constantly, keywords survive), and "fixing" it would make budget writes start restating the keyword list — _enlarging_ their blast radius. That is a behaviour change needing its own decision, not a silent ride-along in a refactor |
| The budget builder discards each keyword's `max_boost` and sends null; bid and restart preserve it                                                                                                                                                                    | Reproduced; harmless, but now written down                                                                                                                                                                                                                                                                           |

Both are encoded as explicit flags on `build.keywords()` with the reasoning attached, so the
next person sees a decision rather than an accident.

### 8.2e Validated live (2026-09-04)

The write path had never been exercised against a real Blinkit account end to end. It has
now, on **574687 (Foresight | Tech Test)**, through the table-driven builder and the
invariant, with the campaign restored afterwards each time.

The campaign was given **Mumbai + Pune targeting (`region_ids: [2, 787]`)** specifically so
the original failure would be reproducible — a pan-India campaign passes the city check
trivially and proves nothing.

| Test                                                       | Result                                                                                      |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **LIVE bid write on a CITY-targeted campaign** (₹201→₹202) | **cities unchanged `[2, 787]`** — this is the exact operation that broadened nine campaigns |
| **LIVE budget write on the same** (₹201→₹202)              | cities unchanged                                                                            |
| Products, name, start/end across both                      | unchanged                                                                                   |
| Restored to ₹201 / ₹201                                    | ✅ campaign exactly as found                                                                |
| Earlier pan-India run (budget + bid)                       | applied cleanly; keyword survived the budget write                                          |
| `empty_pids` fallback                                      | safe but non-functional — **removed 2026-09-05**, see §8.2c                                 |

Two things this settles that argument could not:

- **The fix works against a live account, not just in tests.** Every prior assurance rested
  on unit tests plus DB forensics.
- **A budget write does not delete keywords.** The keyword survived at its original bid, so
  an omitted `keyword_targeting` block genuinely means "leave them alone" (§8.2d).

It also produced the **first live bid write the campaign manager has ever made** — that loop
had never run end to end before, which is why the doc used to carry a ❌ against it.

### 8.3 Status vocabulary

| Marketplace | Canonical | Notes                                                                                                                                                             |
| ----------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ACTIVE`    | `running` |                                                                                                                                                                   |
| `STOPPED`   | `paused`  | User-stopped — resumable                                                                                                                                          |
| `ON_HOLD`   | `held`    | **Delivery paused because the daily budget ran out.** Still LIVE, not stopped: accepts an update (which is what revives it) and can be stopped. Never _restarted_ |
| `COMPLETED` | `ended`   | Terminal                                                                                                                                                          |
| `DRAFT`     | `draft`   | Never launched                                                                                                                                                    |
| `SCHEDULED` | `running` | **Transient** — reported for a minute or two after a RESTART before settling to `ACTIVE`                                                                          |

We only ever _write_ `running` / `paused`. The rest exist so the guardrail can recognise and refuse
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

### 8.4b A reply that never arrives is not a refusal

Blinkit can answer a bid PUT with nothing usable — an empty body, a non-JSON gateway page, a 200
with no success marker. **That does not mean the write failed.** On 2026-09-07, campaign 637511,
keyword `soda`, two ticks failed identically and meant opposite things:

| Tick  | What came back                                | What the bid actually did                        |
| ----- | --------------------------------------------- | ------------------------------------------------ |
| 12:16 | `{"message": ""}` (valid JSON, empty message) | **unchanged** — the next tick read the old value |
| 18:15 | not JSON at all → `_fetch` returns `{}`       | **changed** — ₹421 was live on Blinkit           |

Both took 35–42 s, which is a timeout, not a validator. Both raised a bare `RuntimeError` that
escaped the choke point, escaped the engine's per-rule loop, and escaped past its `finally` — so the
run died _before_ `write_bid_runtime` and `write_run_log`. The 18:15 tick was a drift **recovery**:
it had snapped the bid back to the last price known to hold and should have paused trimming for 90
minutes. That pause was never persisted, so the following tick trimmed straight back to the price
that had just lost the slot.

Three things changed:

- **`writes.WriteUnverified`** — raised instead of `RuntimeError` when the marketplace's answer does
  not say whether the write worked. `writes.apply_bid` resolves it by **reading the bid back**
  (`verify_bid`) and reports applied only when the marketplace now holds the value we sent. Guessing
  "failed" is not the safe default when a write may have landed: it makes our memory disagree with
  the account.
- **`bid._safe_apply_bid`** wraps all three of the optimizer's write sites (window-open floor, bounds
  correction, the optimizer decision). One failed write is now one failed write — an `error` row in
  History with the marketplace's own reason — and the run continues to its bookkeeping.
  `SessionExpired` still aborts, because every remaining keyword would fail identically.
- **The HTTP status is carried.** `_fetch` kept `__status` only long enough to detect 401/403 and
  then dropped it, which is why the two rows above were indistinguishable in the logs. The client now
  stashes the status and (for a non-JSON body) its first bytes, and puts them in the error.

Covered by `tests/test_write_survives.py`, including a guard that the engine never calls
`writes.apply_bid` directly.

### 8.5 Sessions — including one that dies mid-run

The campaign manager **consumes** the same `(tenant, "blinkit")` session as the scrapers and owns no
auth code of its own. Sessions live encrypted in the DB, not on disk. Engines call `ensure()`, so an
expired session self-heals. See [platform-auth.md](platform-auth.md).

**That used to be true only at run START.** `setup()` ran once and `ensure()` with it; a session that
died thirty seconds later was never noticed, because `_fetch` turned Blinkit's login redirect into
`{}` — which every caller reads as _"the marketplace refused this change"_. So a dead session logged

> not applied — Blinkit rejected the change to ₹250

for every remaining keyword: a false statement about Blinkit, and one that hid the real fault. A bid
run lasts minutes and writes real money, so losing its back half to a silent auth failure is not
acceptable.

Since 2026-09-04 `_fetch` carries the HTTP status out alongside the body, and on a 401/403 or a
login-page redirect it **re-authenticates once and replays the call**. Replaying a write is safe: an
auth failure means the request never reached the campaign.

|                                           |                                                                                                                                                                                                                                                                                                                              |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **How many attempts, really**             | One `_fetch` retry, but `ensure()` is a LADDER — probe → refresh → full login, and the login rung itself retries `MAX_LOGIN_ATTEMPTS` (2) with a 5 s backoff. So a single recovery is up to four escalating attempts                                                                                                         |
| **Why not more rounds**                   | A second ladder 200 ms later is identical to the first. What reaches it — broken config, dead inbox, Blinkit refusing us — does not resolve on that timescale, while retrying reliably burns OTP quota and hammers a login endpoint from one datacentre IP. `MAX_LOGIN_ATTEMPTS` is the honest lever, because it has backoff |
| **Parallel lanes**                        | `ensure()` locks per (tenant, platform), so the bid and budget engines cannot double-login — the second waits and finds the session already fixed                                                                                                                                                                            |
| **If login is broken**                    | Ticks 1–3 each attempt and fail; the circuit breaker (`MAX_CONSECUTIVE_FAILURES = 3`) then refuses **before any network call**, naming the manual fix command. Fail fast three times, then fail cheaply. Bids stay where they are — not reset, not raised                                                                    |
| **It swaps the CONTEXT, not the browser** | The engine holds `pw`/`browser` from `setup()` and closes them in a `finally`. Launching a second Chromium would leak ~1 GB and leave the caller closing the wrong one                                                                                                                                                       |
| **Giving up**                             | `writes.SessionExpired` (a `RuntimeError`, so startup behaviour is unchanged). The engine catches it, logs a genuine session-expired and reports _"stopped after 7 of 20 automations"_ rather than grinding on                                                                                                               |

⚠️ `setup_with_state` can be handed a bare storage state with **no tenant**. Such a client cannot look
up credentials and so cannot self-heal — it raises `SessionExpired` saying exactly that, rather than
pretending it re-authenticated.

### 8.6 The Blinkit API surface

Authenticated calls to `https://brands.blinkit.com` via in-page `page.evaluate(fetch)` — Cloudflare
blocks direct httpx even with valid cookies (an httpx attempt was written and reverted).

| Method | Path                                          | For                                                                                                                                                                          |
| ------ | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/adservice/v1/advertisers/campaigns`         | The campaign list. ⚠️ Carries **no budget field at all**                                                                                                                     |
| GET    | `/adservice/v1/campaigns/{id}`                | Detail: budget, keywords, pids, pacing, `region_type` + `region_ids`, `billed_amount`, `allowed_transitions`                                                                 |
| GET    | `/adservice/v1/campaigns/keywords/attributes` | **The bid floor**, per keyword: `bid_range.{exact_match,smart_match}.{min,max,suggested_min,suggested_max,min_for_boost}` + `keyword_searches`. Takes a comma-separated list |
| GET    | `/adservice/v{2,3}/campaigns/config`          | Enabled asset types, the city directory (`cities`, `states_and_cities`), `min_cpm_config`                                                                                    |
| GET    | `/adservice/v1/advertisers`                   | Advertiser id + name + `features` flags (`city_filter`, …)                                                                                                                   |
| POST   | `/adservice/v1/campaigns/reports/{id}`        | Keyword report (position, impressions, cpm)                                                                                                                                  |
| PUT    | `/adservice/v3/campaigns`                     | **The write** — budget, bids, and RESTART                                                                                                                                    |
| DELETE | `/adservice/v1/campaigns/{id}`                | **Stop** — see §8.4; it does not delete                                                                                                                                      |

> ⚠️ **`min_cpm_config` is not a bid floor, despite the name.** It is a per-campaign-type table
> (PRODUCT_LISTING 500, BRAND_BOOSTER 200, …) that Blinkit's dashboard feeds to its **budget**
> validator. Bids far below it are accepted and held: 51 of 55 campaigns carry one, active
> campaigns included, and 36 sub-₹500 bids we wrote ourselves (down to ₹226) read back unchanged.
> The bid floor is per keyword, from `keywords/attributes` (§7.6b). This doc previously stated the
> opposite; corrected 2026-08-26 after reading Blinkit's own dashboard JavaScript, which is also
> where the undocumented endpoint came from (`scripts/blinkit_ui_bid_rules.py` downloads it).
>
> There is likewise **no minimum-budget field** anywhere — Blinkit's dashboard derives one in the
> browser. We store the inputs (`min_cpm`, `pacing_type`, `billed_amount`, `campaign_cpm`) and let
> the marketplace reject a too-low budget rather than reimplementing its rules.

---

## 9. Edge-case reference

Everything below is the actual behaviour of the current code.

### 9.1 Window opens

| Scenario                                      | What happens                                                                                                            |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Normal open                                   | Writes `min_bid`. Doesn't trust it — re-checks each tick until the marketplace reads it back                            |
| Bid already at `min_bid`                      | Confirms, marks the window open, optimises from `min_bid`                                                               |
| Last night's reset failed, bid still high     | Writes `min_bid`. **This is what stops the multi-day ratchet**                                                          |
| Budget engine's RESTART overwrites our write  | Next tick sees the old bid and writes again. Self-correcting, costs one tick                                            |
| Campaign not running yet at open              | Skips, does **not** mark the window open, retries next tick                                                             |
| Yesterday's drift / pause / relaxed target    | All cleared — every day retries the real target from scratch                                                            |
| Overnight window (18:00–02:00), tick at 01:00 | Still the _same_ window. Midnight doesn't re-floor a bid mid-flight                                                     |
| **All-day** rule, tick at 00:01               | Still the _same_ window if yesterday was in the run (`window.run_start`): no floor, and the bid, holding price, raise step and relaxed target all carry over. Floors only on the first day of a run (e.g. Friday for Fri/Sat/Sun, the start date) or if nothing touched the rule since before yesterday's window opened. Before 2026-09-18 it re-floored every night |
| Dry run                                       | Simulates the write, then marks open anyway — otherwise a dry tenant re-opens forever and never exercises the optimizer |

### 9.2 Climbing

| Scenario                                                         | What happens                                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Position worse than target                                       | Raise by `next_raise_step` — **percentage-based, not distance-scaled**. Base is `max(min_step, bid × pct)`; it escalates ×`ESCALATE` while the position refuses to move and resets to base once it does. The old ₹100/50/25/12.5 distance tiers are gone                                                                                                                                                  |
| Raised, no improvement, <10 min since                            | HOLD — wait for the marketplace to reflect it                                                                                                                                                                                                                                                                                                                                                             |
| Position unreadable (scrape failed)                              | Error row, counted; run continues to the next keyword                                                                                                                                                                                                                                                                                                                                                     |
| **Ad not on the page** (organic-only, or product not in results) | **Raises**, on both marketplaces since 2026-09-04. Treated as position `len(results)+1` — a genuine lower bound that keeps escalation honest. Was a skip on Blinkit, which meant a keyword outbid off the page could never climb back, and the next window open wrote `min_bid`, lower still. ⚠️ A broken product match therefore climbs to `max_bid` and stays: the ceiling is the only bound (accepted) |
| Position scrape throws                                           | Error row, counted; the run continues to the next keyword                                                                                                                                                                                                                                                                                                                                                 |
| Reached `max_bid`, target still missed                           | See [9.4](#94-target-unreachable)                                                                                                                                                                                                                                                                                                                                                                         |

### 9.3 At target

| Scenario                             | Drift **off** (`BID_DRIFT_PCT=0`, the kill switch)                                                                                                           | Drift **on** (**the default — `7`**)                 |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| Exactly at target                    | Freeze — pays the climb price all day                                                                                                                        | Shave `DRIFT_PCT`%/tick                              |
| Better than target (pos 1, target 3) | **Freeze.** The ₹100/50/25/12.5 step-down ladder was removed 2026-09-01 — rupee-denominated steps cannot be right on two marketplaces whose bids differ ~40× | Counts as holding, shave                             |
| Held once only                       | —                                                                                                                                                            | Wait for a second confirmation                       |
| Shave went too far, position lost    | —                                                                                                                                                            | Snap back **precisely** to `last_holding_cpm`, pause |
| Outbid during the pause              | Raise normally                                                                                                                                               | **Raise normally** — the pause only blocks decreases |
| Already at `min_bid`                 | No change                                                                                                                                                    | No change                                            |

### 9.4 Target unreachable

| Scenario                                     | What happens                                                                                 |
| -------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Pinned at `max_bid`, target missed **twice** | Adopt the achieved position as the working target (`relax` row); drift then optimises for it |
| Missed once only                             | No relax — one bad scrape can't relax a target for a whole window                            |
| Still room below the ceiling                 | No relax — the climb hasn't finished trying                                                  |
| Relaxed to a poor position (e.g. 15)         | **Still held.** No acceptability floor — deliberately parked                                 |
| New window next day                          | Relaxation cleared, real target retried                                                      |
| Target becomes reachable mid-window          | **Not noticed until tomorrow.** Parked — see [12](#12-known-gaps--parked)                    |

### 9.5 Rule edited

| Scenario                             | What happens                                                                                                       |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `max_bid` lowered below the live bid | Forced into range on the next tick (`bounds` row)                                                                  |
| `min_bid` raised above the live bid  | Forced up on the next tick                                                                                         |
| `max_bid` **raised** while relaxed   | Relaxed target voided → climbs for the real target. Without this it would drift _down_ after being given more room |
| `max_bid` lowered while relaxed      | Voided, re-derived against the new ceiling                                                                         |
| `target_position` edited             | Relaxed target cleared explicitly (no self-healing tell for this one)                                              |
| Any in-window edit                   | Reconcile + an immediate engine run, so the change lands now rather than at the next tick                          |
| Editing an **ended** automation      | Rejected (400, "move its dates forward to run it again") unless the edit moves its dates forward               |
| Dates moved forward on an ended one  | **Reopened** — live at once; the reconcile restores its crons, clears `ended_at` and writes a `reopened` History row |
| Campaign on a rule                   | Not editable — it is the rule's identity                                                                           |

### 9.6 Window closes

| Scenario                                        | What happens                                                                                     |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Campaign running                                | Writes `min_bid`                                                                                 |
| Campaign **ON_HOLD** (budget exhausted)         | **Writes it** — ON_HOLD is a running campaign                                                    |
| Campaign stopped, write refused                 | Attempted anyway; logs a **visible failed** row. Window-open recovers it                         |
| Bid already at `min_bid`                        | Skips the write, but **logs** the skip                                                           |
| Bid unreadable                                  | Writes anyway — "unknown" is not "already at the floor"                                          |
| Keyword still covered by another in-window rule | Left alone                                                                                       |
| One keyword's write throws                      | Caught — the other keywords still get de-escalated                                               |
| Reset fire missed (runner down >7 min)          | Recurring rule: window-open recovers it. **Last window**: the hourly settle pass floors it (≤3 tries, ≤24 h) |
| Rule has **ended**, or not started yet          | **Never selected** — only a window that just closed is reset                                     |
| Rule **paused** before the window closed        | No reset fires — Resume repairs it, or Reset does. See [9.6b](#96b-pause--resume--reset--delete) |
| **All-day** rule                                | Resets at 23:59 only where its run of days ends — Sunday night for Fri/Sat/Sun, its end date, a `once` date. Every day with no end date never closes → no reset. The 23:59 cron runs nightly; the edge selection makes the other nights no-ops (no browser opened) |

### 9.6b Pause / Resume / Reset / Delete

A bid rule is **`active` or `paused`**. There is no third state: `stopped` was mechanically
identical to `paused` (every engine check is `state == "active"`) — two words for one
behaviour, and a Stop button with no undo. Removed 2026-09-07, along with `POST
/bid-rules/{id}/stop`.

**Pause freezes; it does not lower the bid.** Pausing is not a decision about price, so the
keyword stays wherever the optimizer left it. What pause _does_ remove is the automation's
schedules — including its **end-of-window reset**, which is why Resume and Reset both know
how to put that right.

| Rule state                                | Pause | Resume | Reset   | Delete | Delete + reset |
| ----------------------------------------- | ----- | ------ | ------- | ------ | -------------- |
| **running** (active, in window)           | ✅    | 409    | **409** | ✅     | ✅             |
| **scheduled** (active, before the window) | ✅    | 409    | ✅      | ✅     | ✅             |
| **paused**                                | 409   | ✅     | ✅      | ✅     | ✅             |
| **ended**                                 | 409   | 409    | ✅      | ✅     | ✅             |

Two of those cells carry the whole design:

- **Reset is refused only while the rule is RUNNING.** There the next tick undoes it inside
  15 minutes, so refusing states that plainly instead of spending a write that gets
  reverted.
- **Reset IS allowed on an ended rule**, and that is the case that matters. A rule paused
  across its window end never got its de-escalation, and Resume is refused on an ended rule
  — so Reset is the only thing left that can bring that bid down.

Gates read `state` and `_bid_ended()` directly, never the computed `status`: a paused rule
whose window has since ended still reports `paused`, because the state the user chose
outranks the calendar. "Ended" is minute-precise — the moment the last window closes — and a paused rule
that ends is **never settled automatically**: its bid stays where the pause left it until someone uses
Reset (§5b).

**Resume decides from current facts.** It clears every learned value —
`last_cpm`, `last_position`, `last_bid_updated_at`, `last_holding_cpm`,
`drift_paused_until`, `effective_target`, `effective_at_max_bid`, `raise_step` — because a
rule paused for six hours knows nothing useful about the auction and each of those is an
input to a decision. Clearing `last_cpm` is what makes the next tick read the **live** bid
rather than trusting its own memory.

> ⚠️ **`updated_at` is kept, deliberately.** The engine decides whether a window has already
> been opened with `runtime.updated_at >= window_start`, so preserving it makes both cases
> correct with no special-casing: paused and resumed **inside** one window → carry on from
> the live bid; paused **across** a window start → the next tick re-opens at the floor. This
> is also why `repo.clear_bid_runtime` cannot use `write_bid_runtime`, which stamps
> `updated_at = now()` on every call — doing so would make every resume look mid-window and
> silently skip the floor.

Resume also **repairs a window that closed during the pause**: if the window is shut when
you resume, the reset the pause removed is enqueued there and then.

**The write itself is `cm.set_bid`** — one keyword, one value, `cpm = the rule's min_bid`.
It takes plain values rather than a rule id because Delete-with-reset removes the rule
before the job runs, so anything that had to look one up would find nothing. It refuses to
touch a keyword an active, in-window rule is bidding on, and the floor is re-resolved
against the marketplace's published minimum at execution time, not at enqueue time.

Two scheduling details make these feel immediate:

- **Lane `cm_ops`, not `cm_bid`.** `cm_bid` has one slot and an optimizer tick holds it for
  87–547 s, so a reset queued there would wait minutes for the very engine it is
  countermanding. `cm_ops` runs in parallel and is nearly idle. Sharing its single slot with
  the other campaign writes is a bonus: two whole-campaign PUTs can never overlap.
- **`priority=10`** against a default of 100 — the queue claims by
  `(priority, scheduled_for)`, so a reset someone is waiting on jumps pending scheduled work.

And because a reset can now genuinely run beside an in-flight optimizer tick, the optimizer
**re-reads the rule's `state` immediately before every write** and skips if it is no longer
active or no longer exists (`bid._still_active`). That closes the pause, reset and delete
races in one place. It also skips the runtime write in that case — writing runtime would
bump `updated_at`, which is exactly what Resume depends on.

### 9.7 Budget engine

| Scenario                                  | What happens                                                                            |
| ----------------------------------------- | --------------------------------------------------------------------------------------- |
| A rule matches now                        | Apply its budget; start the campaign unconditionally if stopped                         |
| No rule matches, between windows          | **Nothing** — not read, not written (§6a)                                               |
| Window just ended, `stop_after_window` on | Stop the campaign                                                                       |
| Window just ended, toggle off             | Revert to default, **never** touch run state                                            |
| Two overlapping windows                   | The **oldest rule** wins — stable and explainable                                       |
| Campaign is ON_HOLD                       | Budget is writable — raising it is what revives delivery                                |
| Campaign is `ended` / `draft`             | Refused by the transition table (a draft is startable only by an explicit human action) |
| Schedule's last window closes             | That fire reverts (and stops, if toggled); the schedule is then **left alone**           |
| Hours or days after it ended              | **Nothing is written**, and the engine does not sign in                                 |
| Final fire missed while the runner was down | The hourly pass settles it: revert, then stop if toggled (≤3 tries, ≤24 h)             |
| Fire missed on a live recurring schedule  | The hourly safety poll catches it (in-window drift, or a revert that never landed)      |
| Someone sets a budget by hand between windows | It stands until the next window opens (§6a)                                           |

### 9.8 Safety and failure

| Scenario                                                | What happens                                                                                                                                              |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tenant not armed (`live_armed=false`)                   | Everything computes and logs; **nothing is written**                                                                                                      |
| No `advertiser_id` stored                               | Live run refused outright — it can't be derived, so it must be configured                                                                                 |
| Session expired **mid-run**                             | Re-authenticates once and replays the call (§8.5). If that fails, the run aborts and says how far it got                                                  |
| Session expired **at startup**                          | Run aborts cleanly — and now writes **one History row per affected automation** saying it could not sign in, so the client sees a reason instead of a gap |
| Campaign detail read fails                              | Status treated as _unknown_, not stopped — a read blip must not silently pause optimization                                                               |
| **Bid write not acknowledged** (empty / non-JSON reply) | The bid is **read back** and the outcome decided on what the marketplace actually holds — see [8.4b](#84b-a-reply-that-never-arrives-is-not-a-refusal)    |
| **A bid write throws**                                  | One `error` row in History with the marketplace's reason; the run continues and still persists its runtime + history                                      |
| >`MAX_WRITES_PER_WINDOW` writes on a keyword            | Rate limit blocks further writes                                                                                                                          |
| Computed budget is 0 or absurd                          | Rejected by the bounds guardrail, never sent                                                                                                              |
| `CM_BID_DRIFT_PCT=0`                                    | True revert to pre-drift behaviour                                                                                                                        |

---

## 9b. History — what the client sees, and why

`cm_run_log` is on its way to being a client-facing record: _what did the automation do to my
campaign, and why_. Three changes on 2026-09-04 made it one.

### Every tick is recorded, not just the changes

A tick that changed nothing used to write no row. "Held at ₹201 because the position is already at
target" existed only in Cloud Logging — which is not joinable to our data, has its own retention, and
cannot be shown in the product. But those are the ticks a per-automation view needs _most_: **"why has
my bid not moved for six hours"** is answered by them and by nothing else.

They are now written with `hold` (off target, waiting for the marketplace to reflect the last change)
or `no-op` (nothing to do).

The old reasoning — that a row every 15 minutes would bury the real changes — was right about the
symptom and wrong about the cure. The noise belonged in the default **view**, not in what we are
willing to remember. So `/history` **defaults to changes only**, and `?include_unchanged=true` returns
the full per-tick record. `?campaign_id=` / `?rule_id=` narrow it.

### Three columns that make a decision explainable

| Column     | Why                                                                                                                                                                                                                                                                  |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rule_id`  | Which automation the decision belongs to — the key a per-automation view groups by. **TEXT**, because a bid rule's id is a uuid hex string. **Not a foreign key**: history must outlive the rule it describes, and budget/activation rows point at a different table |
| `position` | The observed search position — THE input to every bid decision, and previously only prose inside `reason`                                                                                                                                                            |
| `target`   | The effective target it was judged against, which differs from the rule's whenever one has been relaxed                                                                                                                                                              |

Without the last two a UI can show _that_ a decision happened but never _why_, which is the whole
point of showing it.

> ⚠️ **`rule_id` shipped as INTEGER and broke every bid tick for three days** (2026-09-04 →
> 2026-09-07, fixed by migration `a4e7c2f19b83`). The only writer is the bid engine passing
> `cm_bid_rules.id` — a uuid hex string — so the INSERT died with an asyncpg `DataError`,
> **after** the bids had already been PUT to Blinkit. Two things that made it worse than a
> lost log row: the run exited 1, so a healthy optimizer alerted as a failing job every tick;
> and `repo.recent_write_count` — the runaway-write guard — counts `cm_run_log` rows with
> `dry_run = false`, so with nothing landing it counted zero and the cap was not counting at
> all. The row-shape tests missed it because they only inspect a dict; the type is now pinned
> against the model in `test_history_reasons.py`.

### Reasons are written for a client, not for a log reader

Every row already carried a `reason`; three of them were engineer-speak, and one was worse:

| Before                                   | Now                                                                             |
| ---------------------------------------- | ------------------------------------------------------------------------------- |
| `window opened → min`                    | "the window opened, so the bid starts at its ₹200 floor"                        |
| `window closed → min (campaign running)` | "the window closed, so the bid goes back to its ₹200 floor"                     |
| `live bid above — forced into [200–400]` | "the live bid of ₹450 was above the ₹400 limit, so it was brought back to ₹400" |

| `Zepto blocked the search: HTTP 299 {
 "error_code": …` — **four lines of raw JSON** | "could not check the search position, so the bid was left unchanged (… HTTP 299 { "error_code": "LOGIN_REQUIRED" })" |

`bid._plain()` collapses an exception to one line and caps it at 120 characters. The full text stays
in Cloud Logging where support can find it. `tests/test_history_reasons.py` greps the source for the
two mistakes that actually happened — arrow jargon in a reason, and `str(e)` passed straight in.

The `compute_bid` reasons were already right and are untouched: _"raising to ₹25 (+₹3) because
position 24 is worse than target 3"_ is the register the whole column aims at.

### Both engines narrate the same way

The bid engine reads as a block per keyword — header, configuration, what the marketplace showed,
what we decided, what landed. The budget engine printed flat lines instead
(`campaign 583049 applied ₹1202 → ₹802`), repeating the campaign id and writing an arrow where a
verb belongs. It now uses the same block (`logs.context` / `observed` / `decided`, and a
`write_result` that speaks in sentences):

```
[1/4] Reco 04 - Blueberry & Mango  (campaign 583049)
      default ₹802 · ₹1202 on Fri, Sat, Sun 19:30–02:00, from 11 Sep
      no rule applies right now, so the budget should be its ₹802 default
      the campaign is running · its budget is ₹1202
      applied — the budget is now ₹802 (was ₹1202)
```

Three things changed with it:

- **A no-op is narrated by the engine**, in its own words (_"the budget is already ₹1202, so there
  is nothing to change"_), and the guardrail line behind it dropped from WARNING to DEBUG. It is the
  hourly poll's normal answer — at WARNING it drowned every run that did something.
- **A failed write says what the value still is**, and why: _"not applied — the budget is still
  ₹1202 (campaign is not editable)"_. The marketplace's own reason used to be dropped.
- **A rule reads as English.** `_reason` rendered an open-ended rule as
  `sunday, friday, saturday (2026-09-11–None) / 19:30–02:00`; it now says
  `Fri, Sat, Sun 19:30–02:00, from 11 Sep` — week order, real dates, no `None`. The same string is
  what History shows a client.

### A blocked run explains itself too

A run that dies at `setup()` returns before writing anything, so History showed bids not moving for
hours with no row saying why. All six early exits — session and account-arming failures, across the
optimizer, the end-of-window reset and the budget engine — now write **one row per affected
automation**, per campaign rather than per run, because that is how the question is asked.

The write is wrapped: a bookkeeping failure must never mask the auth failure underneath it.

### An automation's end is recorded too

Four lifecycle actions (`lifecycle.py`). None is a marketplace write — they are outside the rate limit's
`_WRITE_ACTIONS` and outside `NO_CHANGE_ACTIONS`, so they never count as writes and always show in the
default view.

| Action          | UI label        | Written by                    | When                                                                   |
| --------------- | --------------- | ----------------------------- | ---------------------------------------------------------------------- |
| `ended`         | Ended           | the reconciler's sweep        | `ended_at` is first set — **timestamped at the close**, not when swept |
| `reopened`      | Reopened        | the reconciler's sweep        | `ended_at` is cleared because the dates moved forward                  |
| `settled`       | Finished        | the budget engine / bid reset | the final teardown landed (live runs only)                             |
| `settle-failed` | Couldn't finish | the budget engine / bid reset | the last allowed attempt failed — left as it is, recorded once         |

⚠️ **This table now grows with TIME rather than with ACTIVITY** — roughly 4 rows/hour per in-window
keyword, where it previously wrote none. It needs a retention policy; none is implemented.

---

## 10. Configuration

`campaign_manager/config.py`. Every value has a safe default; **no required `.env` keys.** All are
read at import, so **the runner must be restarted** for a change to take effect.

| Env                               | Default         | Meaning                                                                            |
| --------------------------------- | --------------- | ---------------------------------------------------------------------------------- |
| `CM_DRY_RUN_DEFAULT`              | `True`          | Every action is dry-run unless explicitly armed                                    |
| `CM_MIN_BUDGET` / `CM_MAX_BUDGET` | `1` / `100000`  | Budget bounds guardrail                                                            |
| `CM_MAX_WRITES_PER_WINDOW`        | `12`            | Rate limit, per keyword                                                            |
| `CM_RATE_WINDOW_MINUTES`          | `60`            | Rate-limit window                                                                  |
| `CM_BID_DRIFT_PCT`                | **`7`** (armed) | **The drift kill switch.** Set to `0` for a true revert to pre-drift behaviour     |
| `CM_BID_DRIFT_MIN_STEP`           | `5`             | Floor for one shave, so small bids still move                                      |
| `CM_BID_DRIFT_PAUSE_MINUTES`      | `90`            | How long before shaving resumes after an overshoot                                 |
| `CM_BID_RAISE_MIN_STEP`           | `50`            | Absolute floor for one raise                                                       |
| `CM_BID_RAISE_PCT`                | `8`             | Base raise as a % of the current bid                                               |
| `CM_BID_RAISE_ESCALATE`           | `1.5`           | Multiplier per tick the position doesn’t move. `1.0` = flat step                   |
| `CM_BID_MAX_ABSOLUTE`             | `10000`         | Runaway guard. The ceiling for a rule with no `max_bid`, and a cap on one that has |
| `CM_SETTLE_MAX_ATTEMPTS`          | `3`             | Failed final teardowns before the settle pass gives up (§5b)                       |
| `CM_SETTLE_MAX_AGE_HOURS`         | `24`            | How long after a close an unlanded final teardown is still settled                 |

Fixed constants: reflection `HOLD_MINUTES=10` · optimizer cadence 15 min · reset lead 1 min ·
reset look-ahead 2 min · reset look-back = misfire grace (300 s) + look-ahead · safety poll hourly ·
bid settle pass hourly at :37 · cleanup 04:00.

**Arming is per tenant**, not per env: `live_armed` on `cm_platform_accounts`. When armed, the
reconciler stamps `live=true` on that tenant's engine schedules so scheduled runs write for real.
Reversible — disarm, reconcile, back to dry.

---

## 11. Operating it

### CLI

```bash
python -m cli cm budget-scheduler --tenant <uuid> -m blinkit|zepto [--live]
python -m cli cm bid-optimizer    --tenant <uuid> -m blinkit|zepto [--live] [--reset]
python -m cli cm reconcile        --tenant <uuid> -m blinkit|zepto [--live]
python -m cli cm set-budget       --tenant <uuid> -m blinkit|zepto --campaign <id> --budget <n> [--live]
python -m cli cm status           --tenant <uuid> -m blinkit|zepto --campaign <id>     # READ ONLY
python -m cli cm set-advertiser   --tenant <uuid> -m blinkit|zepto --id <n|brand-uuid>
python -m cli cm arm|disarm       --tenant <uuid> -m blinkit|zepto
python -m cli cm rules add-bid|add-budget-schedule|list -m blinkit|zepto …
python -m cli cm rules remove-bid|remove-budget|add-budget-rule …     # by id — no -m needed
```

Everything defaults to dry-run. `--live` is always explicit. Full reference: [CLI.md](CLI.md#campaign-manager-cm).

### The marketplace is never assumed (2026-09-24)

Every layer names the marketplace it acts on, and **none has a default** — a forgotten one fails
rather than driving Blinkit's account by accident:

| Layer | How the marketplace is chosen | Without one |
|---|---|---|
| CLI | `-m blinkit\|zepto` (required) | usage error |
| API | `/campaign-manager/<marketplace>/…` ([api-reference.md](api-reference.md)) | old address → 400 saying the new form; unknown → 404 |
| API ids | a rule/schedule/job id must belong to the address's marketplace | 404 — `…/zepto/…` can never act on a Blinkit rule |
| Job queue | `marketplace` param on every `cm.*` job (API and reconciler stamp it) | the runner fails the job before it starts (`MissingMarketplace`) |
| Engines · repo | `platform` argument, required | `TypeError` at the call — caught by tests, never guessed |

Two deliberate exceptions: public-scrape jobs (reads, not operations) keep a Blinkit fallback, and the
queue's `uq_jobs_active` index still COALESCEs a missing marketplace to 'blinkit' — harmless now that
no `cm.*` job lacks one; changing it needs a migration.

### Rolling out a change

1. Apply any migration (shown and confirmed first — shared DB).
2. Merge to `main` and pull on the VM. **The VM runs `main`; nothing on a feature branch exists there.**
   A change to the API's addresses (like 2026-09-24's marketplace-in-the-path) must ship the
   **frontend, API (Render) and VM together** — API → VM → website — or the dashboard's automation
   buttons fail in the gap. Then run one live reconcile per tenant and marketplace
   (`cm reconcile --tenant <uuid> -m <marketplace> --live`), so its schedules and lifecycle markers
   match the new code now rather than at the 04:00 cleanup.
3. Create one bid rule on a **low-stakes campaign**, with drift off — which now takes an
   explicit `CM_BID_DRIFT_PCT=0`, because the default is `7` (armed).
4. Watch a day of `cm_run_log` + Cloud Logging: does the window-open floor land, does the end reset
   fire, does anything get refused?
5. Only then restore drift (drop the `0` override + runner restart) on that one keyword, and measure.

### What to watch first

- **A `bounds` line naming the marketplace floor.** Expected and healthy — it means Blinkit's
  minimum for that keyword is above the rule's `min_bid` and the engine bid at the floor (§7.6b).
  Worth watching only if it appears on a keyword whose floor you thought you knew.
- **`bounds` rows** appearing without an edit — would mean something else is moving the bid.
- **`relax` rows** — how often targets turn out to be unreachable, and at what position.
- **Failed `reset` rows** — how often the campaign is already dark at window close.

---

## 12. Known gaps & parked

### v1 retirement (completed 2026-09-03)

The v1 engine is **gone**, code and data. Deleted in one pass: `ad_campaigns/`, the
`cli ads` command group, the three `ads.*` job types, ~21 functions in `ads_service`, the
`/ads/budget-schedules` + `/ads/bid-optimizer` routes and their schemas, the v1 UI
(`frontend/src/features/campaign-manager/`), and — via migration **`e7a3c85f2b19`** — its
eight tables. That also removed the `bid_optimizer_rules.json` side-write, a global,
non-tenant-scoped file that three _live_ API routes were still writing to.

Dropped tables: `budget_schedules`, `budget_schedule_rules`, `budget_scheduler_log`,
`bid_optimizer_rules`, `bid_optimizer_log`, `campaign_data_cache`, plus the long-dead
`ad_automation_rules` / `ad_automation_actions` (an older abandoned experiment from
revision `9cba1aca0fa7` that never had a model or a caller). ~7,400 rows, reviewed as
stale before the drop. `downgrade()` restores the schema, never the rows.

With v1 gone, the surviving manager took its plain name back: the UI route is
`/campaign-manager` again and `/campaign-manager-v2` redirects to it.

**Two things deliberately survived the deletion:**

| Kept                                                             | Why                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Lane.budget_scheduler` / `bid_optimizer` / `sync_campaign_data` | ~3,700 historical `jobs` rows carry these values and `lane` is a str-Enum column — dropping a member breaks every read of that history. They have no `LANE_SLOTS` entry, so `lane_slots.get(lane.value, 0)` gives them zero slots and nothing can ever be claimed into them. And Postgres has **no `ALTER TYPE ... DROP VALUE` at all**: removing one means recreating the type and rewriting the column, on a shared DB with a live runner. Verified after the drop — `cli status --days 60` renders all 3,703 legacy rows fine, as raw type names rather than friendly labels (`label_for()`'s deliberate fallback for unknown types) |
| `/ads/campaigns/{id}/keywords` — **no**, this one went too       | It was the last v1 route with a live consumer: the bid form's keyword autocomplete. It served `campaign_data_cache`, unrefreshed since 2026-07-29, while `bid-context` served the _same_ campaign's keywords from the nightly scrape. Two sources for one fact, one of them five weeks stale. The form now derives its suggestions from `bid-context`, and the route, service function and schema are deleted                                                                                                                                                                                                                           |

### Deliberately parked

| Gap                                        | Consequence                                                                                                                                           |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Target becoming reachable **mid-window**   | Not noticed until the next day. Re-testing means climbing back to the ceiling, which burns most of a window and usually finds nothing                 |
| No acceptability floor on a relaxed target | A poor position is held cheaply rather than abandoned. "Below what rank is this worth paying for?" is a business call                                 |
| Drift parameters (7%, 90 min)              | Educated guesses, unmeasured. Tune from real History rows                                                                                             |
| Tiered position sourcing                   | Every distinct (keyword, store) is fetched live every run. Now one cheap API request each rather than a browser launch, so the pressure is much lower |
| Per-tenant guardrail bounds                | Global defaults for now; revisit when a second tenant with a different budget scale lands                                                             |

### Known, not yet fixed

| Gap                                                                     | Consequence                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reset schedule is `catchup=False`                                       | A firing missed while the runner is down waits until tomorrow. Window-open covers a recurring rule; an automation's last window is covered by the settle pass (§5b)                                                                                                                                                                                                                                                                                                                      |
| Reset and optimizer share the overlap-guard key `(job_type, tenant_id)` | **Fixed** 2026-09-05 — `uq_jobs_active` now includes `params->>'reset'` (migration `a2d5f81c9b34`)                                                                                                                                                                                                                                                                                                                                                                                       |
| One on-demand bid reset per client at a time                            | `uq_jobs_active` keys `cm.set_bid` on (type, tenant, marketplace), so resetting two automations in the same few seconds returns 409 "try again in a minute". Fine at one write per minute; add the keyword to the guard if it ever bites                                                                                                                                                                                                                                                 |
| Bid window scheduling is hour-granular                                  | A 09:30 start rounds to the 09:00 hour; `_in_window` filters the early ticks, so it's cosmetic                                                                                                                                                                                                                                                                                                                                                                                           |
| ~~Stale boundary crons after expiry~~                                   | **FIXED 2026-09-10** — an ended rule produces no crons, so the cleanup prunes them (it used to derive them again). The expiry one-shot is gone (§5b) |
| `cm_run_log` has no retention policy                                    | Grows unbounded against a 500 MB quota                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **Zepto automations get no schedules from the API**                    | The API service always reconciles Blinkit (`_reconcile` sends no marketplace), so a Zepto rule created in the UI gets no crons until someone runs `cm reconcile --marketplace zepto` |
| Unarmed tenants' settle passes sign in                                  | While an ended automation's teardown is unlanded, its hourly pass runs dry, never latches (a dry run lands nothing) and signs in each hour until `CM_SETTLE_MAX_AGE_HOURS` |
| A settle pass and a reset in the same minute                            | `uq_jobs_active` refuses the second `cm.bid_optimizer --reset` for the client. Rare — the settle cron sits at :37, away from the usual reset minutes |
| Bid rules with no stop time                                             | Other rules' reset runs treat them as closing at midnight, but they are never scheduled a reset of their own. Predates the lifecycle work; half-defined |
| Manual Reset does not latch `settled_at`                                | Harmless: if that rule still needs settling, the next settle pass finds its bid at the floor and latches it |
| `cm_campaign_catalog` not built                                         | The optimizer fetches products live. Not needed for bid floors or cities — those ride the daily scrape. The `cm.sync_campaign_data` stub that was to fill it was deleted 2026-09-03 along with `campaign_data_cache`; do not confuse it with `cm.sync_campaigns`, the live catalogue refresh behind the UI's Refresh button                                                                                                                                                              |
| **`campaign_start` is sent one day early on every UPDATE**              | `fmt_date` strips the timezone (`.replace("+00:00","")`) instead of converting it, and `start_ts` is midnight IST = 18:30 UTC the day before. **260 of 260 campaigns** are affected. Blinkit appears to ignore the field on update, but it is a wrong value in a whole-campaign PUT, and the invariant cannot see it — it checks our output against our own derivation of the same field. Found by the 2026-09-05 dashboard capture (§8.2b). Check `RESTART`'s `fmt_date(today)` with it |
| Coworker's `ADVERTISER_ID = 234` is stale                               | Their v1 writes would hit the dead pre-split account (the real one is 19802). Ours sends the stored id. Needs coordinating, not silently changing                                                                                                                                                                                                                                                                                                                                        |
| Nine stores have no canonical city                                      | Four `up-ncr` at `2032xx` (Bulandshahr-district, matching no ad-city), `pilkhuwa`, and three Zepto stores with **transposed pincodes** in the `locations` sheet (`120001`, `210305`×2). They are simply not offered as measurement points                                                                                                                                                                                                                                                |
| No `pytest`                                                             | Suites are standalone assert-based. Fine, but a team call eventually                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **~13 campaigns are still pan-India after the `city_ids` bug (§8.2b)**  | The code is fixed, the accounts are not. Their city lists must be re-entered in the Blinkit dashboard by hand — we never recorded what they were. Until then those campaigns spend nationally, and the metro/ROI splits overlap each other                                                                                                                                                                                                                                               |
| ~~Write payloads are hand-listed field sets~~                           | **FIXED 2026-09-03** — payloads are derived from the field table in `build.py` (§8.2d), so a field cannot be forgotten or silently hardcoded. Equivalence with the old builders is pinned by 36 golden payloads                                                                                                                                                                                                                                                                          |

### ⚠️ Validation status against the live marketplace

|                   |                                                                                                                                                                                                                                                   |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ✅ Validated live | Budget write (₹205 → 574687, reverted). Bid floors read per keyword. City targeting resolved on real campaigns. The scrape's write path.                                                                                                          |
| ⚠️ Partly         | The bid **write** itself now HAS run live (2026-09-04, §8.2e) and preserved city targeting. What is still unexercised against a real campaign is the surrounding bid ENGINE — window-open floor, reset, drift, relaxation and bounds enforcement. |

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
python -m campaign_manager.tests.test_bid_floor       # the marketplace floor + match-type mapping
python -m campaign_manager.tests.test_live_position   # consumer-search position matching
python -m campaign_manager.tests.test_window_equivalence    # window.py vs the recorded old code + the expiry oracle
python -m campaign_manager.tests.test_selection             # the loaders must be told state + calendar
python -m campaign_manager.tests.test_lifecycle             # settle-once + the sweep
python -m campaign_manager.tests.test_lifecycle_history     # lifecycle rows in History
python -m campaign_manager.tests.test_reopen                # reopening an ended automation, through the API layer
python -m campaign_manager.tests.test_rule_input_validation # HH:MM / YYYY-MM-DD refused at the API
```

The decision logic is **pure** and tested without a browser. The orchestration — where the real bugs
have been — is covered by a fake-adapter end-to-end simulation of `bid.run` that exercises ON_HOLD,
refused writes, unreadable bids, the RESTART clobber, bounds edits, relaxation and overnight
windows, run green with drift both armed and off.
