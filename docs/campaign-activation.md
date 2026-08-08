# Campaign Activation — start / stop campaigns as part of budget scheduling

> **Status: A0–A5 BUILT (uncommitted, not deployed).** What remains is a DEPLOY, then the
> click-through + one attended live window.
> Blinkit APIs captured 2026-08-06 (§2); on-demand start/stop proven live on campaign 574687
> 2026-08-07. Migration `b7e3f9c2a1d4` applied. 104/104 tests across eight suites.
> Extends Campaign Manager v2. Read [campaign-manager-refactor.md](campaign-manager-refactor.md)
> (design + decisions D1–D19) and [campaign-manager-v2-implementation.md](campaign-manager-v2-implementation.md)
> (build plan V0–V6) first — this doc assumes both and describes only what is new.
>
> _Rewritten 2026-08-06 after the API capture showed that resuming a campaign **is** a budget
> write. An earlier draft built activation as a separate engine with its own tables; that design
> is dead. §10 records why, so it doesn't get re-opened from scratch._

---

## 1. What this is

Today a campaign can only be started or stopped from the Blinkit dashboard. This adds it to
ours, folded into the budget scheduler rather than built beside it:

- **A per-campaign toggle on a budget automation** — _"stop this campaign when its window ends"_.
  With it on, the campaign is stopped at the end of each scheduled window and restarted at the
  next one. With it off (the default, and every existing schedule), the only change is that a
  stopped campaign is now restarted at a window start instead of being written to blindly.
- **On-demand Start / Pause buttons** for a campaign, independent of any automation.

**Why fold it in.** Blinkit's restart call carries the budget (§2.2), so starting a campaign and
setting its budget is one API call, not two. Modelling them as two engines meant two writes at
the same boundary, an ordering problem, and a mechanism for one engine to ask the other what
budget applied. All of that disappears when the rule that says _"₹1000 from 19:00"_ also says
_"and it should be running"_.

**Why it matters.** Dobra's account right now (`blinkit_ad_campaigns`):

| status      | campaigns |
| ----------- | --------- |
| `STOPPED`   | 145       |
| `ACTIVE`    | 79        |
| `COMPLETED` | 8         |
| `ON_HOLD`   | 5         |
| `DRAFT`     | 3         |

Most of the account is off at any moment, and turning it on and off is manual work done at the
times it matters least — late evenings and weekends.

---

## 2. The marketplace contract

### 2.1 Pause — cheap, safe, no payload

```
DELETE /adservice/v1/campaigns/{campaign_id}
```

No body. No budget. No dates.

> ⚠️ **`DELETE` does not delete — it stops.** Campaign 574687 survived this call and was
> restarted afterwards. Any future reader will assume an HTTP `DELETE` on a campaign is a
> catastrophic bug, so the adapter function carries a loud comment and is only ever reached
> through `apply_status(..., "paused")`.

### 2.2 Resume — a full campaign re-submission

```
PUT /adservice/v3/campaigns          campaign_request_type: "RESTART"
```

Captured from a real stop + restart of campaign 574687 on 2026-08-06, trimmed:

```jsonc
{
    "campaign_request_type": "RESTART", // vs "UPDATE" for budget/bid writes
    "campaign_id": 574687,
    "advertiser_id": 0, // ← 0 here; the budget UPDATE capture sends 19802
    "brand_name": "", // ← several known fields sent empty
    "campaign_start": "8/6/2026", // ← RESET TO TODAY
    "campaign_end": "12/31/9999", // ← "no end date" sentinel; we always send it (AD5)
    "bidding_strategy": { "total_budget": 200, "pacing_type": "DAILY" },
    "campaign_data": {
        "brand_ids": "",
        "category_ids": "",
        "pids": "554767",
        "products": [], // ← present but empty; our UPDATE builder omits it
        "ro_details": {
            "ro_number": null,
            "ro_amount": null,
            "ro_issue_date": null,
            "proof_url": null,
        },
    },
    "campaign_targeting": {
        "city_ids": "-1",
        "is_extendable": false,
        "keyword_targeting": {
            "keywords": [
                {
                    "keyword": "pink toffee",
                    "bids": [
                        {
                            "match_type": "EXACT",
                            "cpm": 201,
                            "max_boost": null,
                        },
                    ],
                },
            ],
        },
        // ← no negative_keywords, no repeat_order_suggestion (our UPDATE payload sends both)
    },
    "preview_image_url": "",
}
```

**Four consequences that shape everything below:**

1. **A resume rewrites the whole campaign** — budget, keywords, bids, pids, dates. A resume that
   races the bid optimizer can silently revert a keyword's CPM (**R1**).
2. **A resume must supply a budget.** In the merged design this is free: the matching rule's
   budget _is_ the budget.
3. ~~**`campaign_start` resets to today** on every restart.~~ **Disproved 2026-08-07 (A1).**
   The payload _sends_ today's date, but Blinkit **ignores it** — the campaign keeps its original
   start date. Verified across two independent restarts of 574687 (the 08-06 dashboard capture and
   our 08-07 live run): `start_ts` stayed `2026-07-14` throughout. We still send today's date,
   because it is what the dashboard sends (AD4) — it simply has no effect. **R2 is closed**, and
   with it the "nightly automation re-dates the campaign 365×/year" concern.
4. **`advertiser_id: 0`** where UPDATE sends the real 19802 — Blinkit derives the account from
   token + campaign for this request type (**AD4**).

`campaign_data` and `campaign_targeting` here differ from _both_ existing builders
(`update_campaign` and `update_keyword_bids`), so RESTART gets its own (**AD3**).

### 2.3 Status vocabulary

| Blinkit     | canonical | notes                                                    |
| ----------- | --------- | -------------------------------------------------------- |
| `ACTIVE`    | `running` |                                                          |
| `STOPPED`   | `paused`  | user-stopped — resumable                                 |
| `ON_HOLD`   | `held`    | **Blinkit paused delivery because the daily budget ran out.** LIVE, not stopped: accepts a budget write (which is what revives it) and can be stopped. Never *restarted* — hence `['UPDATE']`, never `['RESTART']`. |
| `COMPLETED` | `ended`   | terminal                                                 |
| `DRAFT`     | `draft`   | never launched                                           |
| `SCHEDULED` | `running` | **transient** — Blinkit reports this for a minute or two after a RESTART, before settling to `ACTIVE`. Too short-lived to appear in the scraped status table, which is why the first five values looked like the whole vocabulary. |

We only ever _write_ `running` / `paused`. The other three exist so the guardrail can recognise
and refuse them.

**Status is read from campaign _detail_, not from the campaigns list** — corrected 2026-08-07 on
live data (A0.4). `GET /adservice/v1/campaigns/{id}` carries `status`, so status and budget come
back in the same request the engine already makes. The obvious alternative is a trap:
`client.get_campaigns()` asks for **every** campaign type, and Blinkit rejects the whole request
when any one of them is disabled for the advertiser —

```jsonc
{
    "success": false,
    "message": "['BANNER_DIY', 'SHELF_DIY', 'BRAND_SPOTLIGHT_DIY'] are not enabled for given advertiser",
    "data": null,
}
```

— which `get_campaigns` turns into an **empty list, silently**. A bulk status read built on it
returns nothing at all and looks like "no campaigns to manage". (Narrowing to
`campaign_types: ["PRODUCT_LISTING"]` does work and returned 38 campaigns, but which types an
advertiser has enabled varies, so per-campaign detail is both simpler and cheaper here.)

**Blinkit reports its own legal moves — but only for the PUT.** Campaign detail includes
`allowed_transitions`:

| campaign state | `allowed_transitions`                    |
| -------------- | ---------------------------------------- |
| `STOPPED`      | `['RESTART']`                            |
| `ACTIVE`       | `['UPDATE']` — **no stop/delete listed** |

It enumerates `campaign_request_type` values for `PUT /adservice/v3/campaigns`, and the stop is a
different endpoint (`DELETE`) that never appears. **So it cannot gate the pause direction — doing
so would block every stop.** It _is_ authoritative for the resume direction, and that narrower use
is in the backlog. Observed on 574687, 2026-08-07 (A1).

### 2.4 Still worth capturing _(not blocking)_

| #   | What                                           | Why                                                                                                      |
| --- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| 1   | Starting a **DRAFT**                           | Probably a different `campaign_request_type`. 3 campaigns, on-demand only (**AD8**) — safe to defer.     |
| 2   | An **ACTIVE** campaign's `allowed_transitions` | Would let the guardrail use Blinkit's own answer instead of our inferred table. A1 provides it for free. |

**✅ Stopped-campaign detail verified 2026-08-07 (A0.4).** Read live against 574687 while it was
`STOPPED`: detail carries `campaign_budget: 202`, `pids: [554767]` and the full keyword list with
bids — everything the RESTART payload needs. A restart **can** be built from a stopped campaign,
which was the one open question that could have invalidated the design. Two shape notes worth
keeping: `pids` came back as a **list** there (the capture shows a string — the builder handles
both), and `campaign_data` was **null** (the builder defaults it).

**✅ Response shapes captured 2026-08-06 — both work with our existing success detection:**

```jsonc
// DELETE  → {"success": true, "message": "Successfully deleted campaign for the following id: 574687"}
// RESTART → {"status": true,  "message": "success", "data": {"campaign_id": 574687}}
```

`writes.apply_*` reads `resp.get("status") or resp.get("success")`, which is true for both. No
change needed, and the "success ≠ success" risk (**C1**) is closed for this feature.

**Confirmed by Deepansh:** Blinkit's own UI blocks bid updates on a stopped campaign. This is
load-bearing — see §6.

---

## 3. Decisions

| #        | Decision                                                                                                                                                                                                                             | Why                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **AD1**  | **Activation is part of the budget scheduler**, not a separate engine. One toggle on `cm_budget_schedules`.                                                                                                                          | A resume _is_ a budget write (§2.2). Two engines meant two writes, an ordering problem, and a mechanism for one to ask the other what budget applies. §10 records the design this replaced.                                                                                                                                                                                                                                                                                                                |
| **AD2**  | **A campaign is stopped only by a window _ending_** — never merely because no window happens to be active. Outside that moment we leave its status alone entirely.                                                                   | _Corrected 2026-08-06 — an earlier draft said "stopped whenever no rule is active", which would stop a campaign at moments nobody asked for:_ a schedule created at 14:00 for a 19:00–02:00 window would have its campaign stopped by the 15:00 poll, five hours before the automation had ever run. The trade accepted with this: if the window-end fire is missed (runner down), the stop doesn't happen and the campaign runs to the next window at its default budget — no self-healing from the poll. |
| **AD2b** | **Evaluation stays state-based** — at every fire, work out what should be true now. "A window just ended" is _derived_ from the rules, not remembered.                                                                               | State-based is why the engine survives restarts and missed fires, and why adjacent windows work: with 09:00–12:00 and 12:00–18:00 rules, a rule matches _at_ 12:00, so the campaign keeps running and the budget moves to ₹800. An event-based "A ended → stop" would fight "B started → start" on the same boundary.                                                                                                                                                                                      |
| **AD3**  | **RESTART gets its own payload builder**, not an extension of `update_campaign` / `update_keyword_bids`.                                                                                                                             | Its `campaign_data` and `campaign_targeting` shapes differ from both. Bending the existing (fragile, reverse-engineered) builders to a third shape endangers the budget and bid write paths that are already live.                                                                                                                                                                                                                                                                                         |
| **AD4**  | **Mimic the captured RESTART payload field for field**, including `advertiser_id: 0` and the empty `brand_name`. Keep `arm_live` as a _policy_ gate.                                                                                 | Deviating from a working capture on a reverse-engineered API is how you get a 400 at 19:00 on a Friday. The arm gate still answers "do we know whose account this is" before any write.                                                                                                                                                                                                                                                                                                                    |
| **AD5**  | **A restart never sets a real end date** — it always sends `"campaign_end": "12/31/9999"`, Blinkit's infinite sentinel. Not configurable.                                                                                            | Blinkit's end date is a campaign property, unrelated to our schedules — our own rule date-range decides when the automation stops. A finite `campaign_end` on a nightly-restarted campaign is a time bomb: once it passes, every restart fails. _Settled 2026-08-06: sending the sentinel matches the capture (AD4) and `client.py`'s existing hard-won handling; omitting the key entirely might also work but there's no reason to find out._                                                            |
| **AD6**  | **Revert the budget to `default_budget`, then stop** — in that order.                                                                                                                                                                | Failure modes. Revert-first: if the revert fails we still stop (campaign off, inert); if the stop fails it runs overnight at the _default_ budget. Stop-first: if the stop fails it runs overnight at the _elevated_ budget. Revert-first bounds the overspend, and leaves a stopped campaign resting at its default so a manual restart from Blinkit's dashboard (which pre-fills from the stored budget) doesn't come back hot.                                                                          |
| **AD7**  | **Starting is unconditional; only stopping is gated by the toggle.** At a window start a stopped campaign is _always_ restarted, toggle or not. The toggle answers one question only: when this window ends, does the campaign stop? | _Corrected 2026-08-06 — an earlier draft had the toggle gate both directions._ A campaign with a budget window is meant to run during that window; finding it stopped and leaving it stopped would silently do nothing all evening. Outside a window-end moment we never touch status at all (AD2).                                                                                                                                                                                                        |
| **AD8**  | **A `draft` may only be started on demand**, never by a rule.                                                                                                                                                                        | A human clicking Start on a draft means it. A cron reaching one does not — drafts are often incomplete.                                                                                                                                                                                                                                                                                                                                                                                                    |
| **AD9**  | **Read campaign detail immediately before building a RESTART**, and log a diff of every field the restart will overwrite.                                                                                                            | Resume rewrites keywords and bids. A stale read silently reverts the bid optimizer's work. The diff makes that visible in Cloud Logging rather than discoverable weeks later in a report.                                                                                                                                                                                                                                                                                                                  |
| **AD10** | **Budget Reset on a toggle-on schedule also restarts the campaign.**                                                                                                                                                                 | Reset means "undo what we did". Turning the automation off and silently leaving the campaign dark is the opposite of what anyone expects.                                                                                                                                                                                                                                                                                                                                                                  |

**Deliberately not doing** (both cut on 2026-08-06 as invented complexity):

- **No "schedule can never match again" guard.** A once rule that runs one night and leaves the
  campaign stopped afterwards is the feature working as asked, not a failure. Nothing to protect
  against — and with no rule matching there are no boundary fires at all, so the schedule simply
  goes quiet.
- **No manual-override tracking.** The engine stays stateless: evaluate what should be true now,
  make it so. Consequence, stated once and moved on from: if someone stops a campaign by hand
  mid-window, the hourly safety poll will start it again. In the backlog if that turns out to
  matter in practice.

---

## 4. Data model

**No new tables. One column.**

```
cm_budget_schedules
  …existing…
  stop_after_window   bool  NOT NULL DEFAULT false   -- AD1/AD2: the toggle
```

The name matters: it is _"stop this campaign when its window ends"_, not _"stop it whenever it
is idle"_. Those are different behaviours (AD2) and the column should not invite the wrong one.

`cm_budget_rules` is unchanged. `cm_run_log` is unchanged — `kind` gains the value
`"activation"` for status rows, with `old_value`/`new_value` holding the status strings.

**Migration:** one Alembic revision, one `ADD COLUMN`, defaulted. No data migration, no backfill,
no cutover. Every existing schedule gets `stop_after_window = false`, which is exactly today's
behaviour — and which makes the RESTART code path _unreachable_ for every schedule live today.

> ⚠️ `--autogenerate` on this shared DB sweeps in unrelated drift (it has previously tried to drop
> `ad_automation_*` and a `search_listings` index). **Hand-trim the migration to the single ADD
> COLUMN before applying**, and show Deepansh the exact command before running it.

`default_budget` keeps its meaning and gains a second one when the toggle is on: it is the
resting value written just before stopping (AD6). The UI labels it accordingly rather than hiding
it — it's the number that caps an overnight failure.

---

## 5. The engine

All of this lands in `campaign_manager/budget.py`. No new module, no new job type for the
scheduled path, no reconciler scheduling change.

### 5.1 Deciding what should be true now

`target_for_now` gains a second return value, with **three** possible states — the third being
"none of my business right now":

```python
def target_for_now(schedule, rules, now) -> tuple[float, str | None, str]:
    """→ (budget, state, reason). state is 'running' | 'paused' | None (don't touch status)."""
    for rule in rules:
        if matches_rule(rule, now):
            return rule.budget, "running", reason(rule)            # AD7: always start
    if schedule.stop_after_window and _window_just_ended(rules, now):
        return schedule.default_budget, "paused", "window ended"   # AD2: only here
    return schedule.default_budget, None, "no active rule — default budget"


def _window_just_ended(rules, now, grace=MISFIRE_GRACE) -> bool:
    """True when no rule matches now but one did `grace` ago — i.e. this fire IS a window
    end, not merely some moment outside a window. Derived from the rules; nothing stored."""
    return any(matches_rule(r, now - grace) for r in rules)
```

`grace` is the scheduler's own `SCHEDULER_MISFIRE_GRACE_SECONDS` (300s), which makes the rule
coherent with the rest of the system: a fire late enough that the scheduler would call it _missed_
is also late enough that we no longer treat it as a window end. Budget boundary schedules run with
`catchup=False`, so a missed boundary is skipped rather than replayed — consistent with AD2's
accepted trade.

Both functions stay **pure** and unit-tested without Blinkit or the DB.

### 5.2 Applying it

```
current_status, current_budget = read          # status from the bulk read, budget from detail

if target_state == "running":                  # a window is active
    paused   → RESTART(budget=target_budget)           # one call, budget included
    running  → apply_budget(target_budget) if it differs
    other    → refuse (§5.3)

elif target_state == "paused":                 # a window just ended, toggle on
    running  → apply_budget(default_budget) if it differs   # revert FIRST (AD6)
               apply_status("paused")                       # then DELETE
    paused   → no-op
    other    → refuse

else:                                          # status is not ours to touch right now
    running  → apply_budget(default_budget) if it differs
    paused   → skip, logged (can't write a budget to a stopped campaign)
    other    → skip, logged
```

With the toggle off, `target_state` is never `"paused"`, so the middle branch is dead and the only
new behaviour on an existing schedule is that a stopped campaign gets restarted at a window start
(AD7) instead of being written to blindly.

### 5.3 Guardrails

In `writes.py`, alongside the existing pure guardrails. The transition table:

| current ↓ / target → | `running`                                                   | `paused`                               |
| -------------------- | ----------------------------------------------------------- | -------------------------------------- |
| `running`            | no-op (skip)                                                | **apply** — revert budget, then DELETE |
| `paused`             | **apply** — RESTART                                         | no-op (skip)                           |
| `draft`              | on-demand only (AD8)                                        | refuse                                 |
| `held`  | **refuse** — nothing to restart; raise the budget instead | **apply** — it is live, so "off outside the window" applies to it |
| `ended`              | **refuse** — terminal                                       | refuse                                 |
| unknown              | **refuse** — an unmapped string means read again, not guess | refuse                                 |

Then, in order: the existing **budget bounds** (a RESTART writes a budget, so it inherits that
guardrail rather than bypassing it), the **rate limit** (`recent_write_count` — it matters more
here than for budget, since each flap costs a full re-submission rather than a scalar write), and
**arming** (`arm_live` unchanged per AD4).

```python
async def apply_status(adapter, client, *, run_id, campaign_id, target, current,
                       dry_run: bool, recent_writes: int = 0,
                       allow_draft: bool = False,
                       budget: float | None = None,       # required for target="running"
                       overwrites: dict | None = None) -> bool   # AD9 diff, logged
```

Same contract as `apply_budget` — `write_intent` → `write_guardrail` → `write_result`, returning
True on applied/would-apply, and **returning before `adapter.apply_status` in dry-run**, which is
the structural guarantee that a dry run cannot write.

**The two directions are not equally risky and the code must not treat them as symmetric.**
`paused` is a bodiless DELETE. `running` is a full campaign re-submission.

### 5.4 On-demand: `campaign_manager/set_activation.py`

Mirrors `set_budget.py`: setup → arm if live → `read_status` → `writes.apply_status` → one
`cm_run_log` row → summary. `allow_draft=True` here and only here (AD8). The UI passes an explicit
budget for a resume, since Blinkit's own restart modal asks for one.

---

## 6. Interaction with the bid optimizer

Blinkit blocks bid updates on a stopped campaign (confirmed). The bid reset logic itself doesn't
change; two small fixes around it do.

**The end-of-window bid reset races the stop.** At 02:00 the `cm_bid` lane fires
`cm.bid_optimizer --reset` while `cm_ops` reverts the budget and stops the campaign — **different
lanes run in parallel**. If the stop lands first, `update_keyword_bids` fails, a job errors, and
the ERROR alert pages someone at 2am on roughly half the nights.

- The reconciler emits the reset fire **one minute before** the stop boundary (`01:59` for an
  02:00 window end) — deterministic ordering with no cross-lane coordination.
- The bid engine treats _"campaign is stopped"_ as a **WARNING skip, not an ERROR** — even with
  the offset a slow run can land after the stop, and that shouldn't page anyone.

**The bid optimizer should skip stopped campaigns**, checked before scraping. The live consumer
search is the expensive part of a bid run, so this saves real browser time on a campaign that is
dark half the day.

**Each night restarts at the bid floor.** The 19:00 RESTART carries bids from the detail read,
which after the 01:59 reset sit at `min_bid`, so the optimizer re-climbs from the floor every
evening. That is the reset working as designed, but it is now load-bearing rather than
incidental, and worth a log line.

---

## 7. Jobs, CLI, API, UI

### 7.1 Jobs

**No new scheduled job type, no new lane, no reconciler scheduling change** — the budget
boundaries, hourly safety poll, `once` fires and expiry fires already exist and now carry the
status decision too. One new type, for the on-demand path only:

```python
"cm.set_activation": JobTypeSpec(Lane.cm_ops, 10 * 60, _cm_set_activation,
                                 param_keys=("campaign", "status", "budget", "live")),
```

The only reconciler change in the whole feature is the bid-reset offset (§6).

### 7.2 CLI

```bash
python -m cli cm set-activation -t <uuid> --campaign 574687 --status running --budget 200 [--live]

python -m cli cm rules add-budget-schedule -t <uuid> --campaign <id> --default 200 --stop-after-window
python -m cli cm rules set-stop-after-window --schedule <id> --on|--off
```

`cm rules list` shows the toggle per schedule. This is what makes solo dry-run testing possible
before any UI exists — the same Tier A / Tier B split used for budget and bid.

### 7.3 API

Under the existing `/clients/{client_id}/campaign-manager` router. Thin as ever: DB rows +
enqueue, **never Playwright** (D2 — Render is API-only).

| Method           | Path                                  | Change                                                                                 |
| ---------------- | ------------------------------------- | -------------------------------------------------------------------------------------- |
| `POST` / `PATCH` | `/budget-schedules[/{id}]`            | `stop_after_window` in the body and on the Out DTO                                     |
| `POST`           | `/budget-schedules/{id}/reset`        | also restarts the campaign when the toggle is on (AD10)                                |
| `POST`           | `/campaigns/{campaign_id}/activation` | **new** — body `{"status": "running"\|"paused", "budget": …}` → `EnqueuedOut {job_id}` |

`GET /jobs/{id}` polls the on-demand action, `GET /history?kind=activation` reads the log, and
**`GET /ads/campaigns` already returns `status` per campaign** — so the UI needs no new read
endpoint for badges. Every mutation enqueues `cm.reconcile live=true`, duplicate-guarded, plus the
immediate re-apply for armed tenants, exactly as budget rules do today.

Layering unchanged: routes (thin, `None`→404, `DuplicateActiveJob`→409) →
`app/services/campaign_manager_service.py` → `campaign_manager/repo.py`.

### 7.4 UI

`frontend/src/features/campaign-manager-v2/` — no new route, no new page, **no third composer
tile**. Activation is a property of a budget automation, and the UI says so.

**`AutomateBudgetForm` / `EditBudgetScheduleForm`** gain one checkbox:

> ☐ **Stop the campaign when the window ends**
> At the end of each window above, the budget returns to the default and the campaign is
> stopped. It starts again at the next window.

**`ActivateNowCard`** (new) sits beside `SetBudgetNowCard`: pick a campaign → current status badge
(free, from the campaigns list) → **Start** or **Pause** → `POST /campaigns/{id}/activation` →
`useJob` enqueue→poll with the real `JobStatus` spinner. Terminal statuses render the button
disabled _with the reason_ ("Completed campaigns can't be resumed"), so the transition table is
visible rather than discovered as a failed job.

**Pause is one click; Start opens a small confirm step** with a budget field pre-filled from the
campaign's current value — mirroring Blinkit's own restart modal. A resume writes a budget, and a
number that consequential should be shown to the person clicking it. The step also notes that
resuming re-submits the campaign (**R1**) — but _not_ that it re-dates it, which turned out not to
happen (**R2**, closed).

**`ScheduledPane`** shows an On/Off chip on toggle-on schedules. **`HistoryCard`**'s kind filter
gains **Activation**.

Conventions per [ui-rules.md](ui-rules.md): arrow components, tabs, theme tokens, feature-first,
`useClient()`, React Query with optimistic mutations, `Loading`/`ErrorState`/`EmptyState`.

---

## 8. File inventory

**New (6)**

| File                                                       | Purpose                                      |
| ---------------------------------------------------------- | -------------------------------------------- |
| `backend/campaign_manager/marketplaces/blinkit/restart.py` | the RESTART payload builder (AD3)            |
| `backend/campaign_manager/set_activation.py`               | on-demand start/pause                        |
| `backend/campaign_manager/tests/test_transitions.py`       | pure transition-table tests                  |
| `backend/campaign_manager/tests/test_restart_payload.py`   | golden-payload test against the §2.2 capture |
| `backend/alembic/versions/<rev>_cm_stop_after_window.py`   | one ADD COLUMN                               |
| `frontend/.../ActivateNowCard.jsx`                         | on-demand control                            |

**Changed (13)**

| File                                                                                                | Change                                                                   |
| --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `marketplaces/blinkit/adapter.py`                                                                   | `read_status` / `read_statuses` / `apply_status` + vocabulary mapping    |
| `campaign_manager/writes.py`                                                                        | `apply_status` + the transition table                                    |
| `campaign_manager/budget.py`                                                                        | `target_for_now` returns state; the apply branch                         |
| `campaign_manager/bid.py`                                                                           | skip stopped campaigns; tolerate the stopped-campaign error              |
| `campaign_manager/reconciler.py`                                                                    | bid-reset offset (−1 min)                                                |
| `campaign_manager/repo.py`                                                                          | `stop_after_window` CRUD                                                 |
| `campaign_manager/tests/test_budget_rules.py`                                                       | extended for the state return                                            |
| `app/models/campaign_manager_v2.py`                                                                 | one column                                                               |
| `app/schemas/campaign_manager.py`                                                                   | toggle field, `SetActivationIn`                                          |
| `app/services/campaign_manager_service.py`                                                          | toggle, Reset-restarts, on-demand orchestration                          |
| `app/routes/campaign_manager.py`                                                                    | 1 new route + 2 changed                                                  |
| `jobs/types.py`                                                                                     | 1 job type                                                               |
| `cli/commands/campaign_manager.py`                                                                  | `set-activation`, `--stop-after-window`, `set-stop-after-window`, `list` |
| `frontend/.../{AutomateBudgetForm,EditBudgetScheduleForm,ScheduledPane,HistoryCard,Page,api,hooks}` | toggle + card + integration                                              |

---

## 9. Build phases

### A0 — Foundations ✅ **DONE 2026-08-07** _(zero Blinkit writes)_

- **A0.1** ✅ Transition table + `apply_status` in `writes.py`, pure. `test_transitions.py` (8).
- **A0.2** ✅ `adapter.read_campaign` / `read_status` / `apply_status` + vocabulary mapping.
  _Changed during the phase:_ the planned bulk `read_statuses` was removed — the campaigns-list
  endpoint it relied on returns empty for this advertiser (§2.3). Status now comes from campaign
  detail, in the same call that already fetches the budget.
- **A0.3** ✅ `marketplaces/blinkit/restart.py` + `test_restart_payload.py` (9), pinned to the
  §2.2 capture. Verified against **live** detail too: the built payload matches the capture in
  every field except `campaign_start`, which is today by design.
- **A0.4** ✅ Stopped-campaign detail verified live (§2.4) — it carries everything RESTART needs.
- **Gate PASSED:** 85/85 across all seven `campaign_manager` suites; no Blinkit write path
  reached; `--autogenerate` not run and no migration created (A3 owns that).

### A1 — On-demand write ✅ **DONE 2026-08-07** _(first real write — attended)_

- ✅ `writes.apply_status` wired to the adapter, both directions; `campaign_manager/set_activation.py`;
  `cm.set_activation` job type (lane `cm_ops`); CLI `cm set-activation`, plus **`cm stop`**,
  **`cm restart`** and a read-only **`cm status`** (the read-back tool — it never writes, whatever
  flags are passed).
- **Gate PASSED.** Dry-run: a no-op resume was rejected (`already running`), a pause logged
  would-apply with zero writes. **Live pause + resume on 574687, attended by Deepansh**, reflected
  on the Blinkit dashboard. Read-back vs the pre-test baseline: `pids 554767` ✓, `bid pink toffee
₹201` ✓, `end 9999-12-31 infinite` ✓, `start_ts 2026-07-14` ✓ (**not** re-dated — R2 closed).
  Nothing silently reverted.

### A2 — Dashboard button ✅ **CODE DONE 2026-08-07** _(gate pending a dry tenant)_

- ✅ `POST /campaigns/{campaign_id}/activation` + `SetActivationIn` (a `Literal` so a bad status is
  a 422, not a job that fails on the VM) + `svc.set_activation_now`; `api.js` / `hooks.js`;
  **`ActivateNowCard`** on the Campaign Manager page. `api-reference.md` updated.
- Backend: 23 campaign-manager routes registered. Frontend: oxlint clean, `vite build` ✓.
- **⛔ Gate BLOCKED while Dobra is armed.** The gate is a click-through _on a dry tenant_, and the
  VM runner is live (heartbeats hourly). Enqueuing `cm.set_activation` for an armed tenant means
  the service stamps `live=true` and the runner performs a **real** stop/start within ~a minute.
  Disarm first: `cm disarm -t a870fd8d-7373-47ec-ad69-5dd08ce35542`.

### A3 — The merged engine ✅ **DONE 2026-08-07**

- ✅ Migration **`b7e3f9c2a1d4`** applied — one hand-written `ADD COLUMN`, `NOT NULL DEFAULT false`.
- ✅ `plan_for_now()` returning `(budget, state, reason)` with the three-valued state;
  `_window_just_ended()`; the apply branch; status + budget now read in ONE `read_campaign` call;
  Reset-restarts (AD10); the toggle through repo → schema → service → route → CLI.
- **Gate PASSED:** `test_budget_rules.py` **19/19** (8 new, covering AD2's "only at a window end")
  plus a new **`test_budget_apply.py` 7/7** proving the *wiring* — restart-carries-the-budget,
  unconditional start, and **revert-before-stop ordering**. **100/100 across eight suites.**
- *Changed from the plan:* the gate does NOT seed a temp schedule and run `cli runner start
  --only-cm`. The budget engine processes **every** schedule for a tenant, so a temp row would be
  picked up by that tenant's next live production fire — unacceptable against a client account.
  Stubbing the adapter proves the same wiring with no DB row, no Blinkit, and leaves a permanent
  test behind. Note those stubbed runs are **not** dry: a dry run returns before the adapter is
  reached (the structural no-write guarantee), so it records nothing to assert on.

### A4 — Bid interactions ✅ **DONE 2026-08-07**

- ✅ **Reset fires one minute early** (`reconciler._RESET_LEAD_MINUTES`), wrapping past midnight,
  for both recurring crons and `once` one-shots.
- ✅ **A matching look-ahead in `_reset_run`** (`bid.RESET_LOOKAHEAD_MINUTES = 2`). Without it the
  early fire is a silent no-op: `_reset_run` only resets keywords whose window is ALREADY closed,
  and at 22:59 a 23:00 window is still open. The look-ahead must exceed the lead, or browser-setup
  drift lands the run back inside the window — asserted in a test.
- ✅ **Bid optimizer skips stopped campaigns** before the position scrape (the expensive part — a
  live consumer search per keyword). Status now comes from the SAME detail read that already
  fetched the bids, via the new `adapter.bids_from_detail()`, so this costs no extra call. A status
  that could not be READ is not treated as stopped — a read blip must not silently pause optimization.
- ✅ **The reset tolerates a rejected write** — skip + WARNING, not an exception that aborts the whole
  run and pages someone at 2am.
- ✅ **Same overnight boundary bug fixed in `bid._time_ok`** as in `budget._matches_rule` (R10): an
  18:00–02:00 rule was still "in window" AT 02:00, which would have made the reset skip the very
  keyword it fired for. The two matchers must stay symmetric.
- **Gate PASSED:** reconciler **23/23** (reset at 22:59 not 23:00, midnight wrap, once-overnight
  one-shot at 01:59), bid-logic **26/26** (window open at the early fire, closed under the
  look-ahead, look-ahead > lead). **104/104 across eight suites.**

### A5 — UI ✅ **BUILT 2026-08-07** · cutover still pending

- ✅ **`AutomateBudgetForm`** — a checkbox under the window fields: _"Stop the campaign when the
  window ends"_, with the consequence spelled out beneath it. No third composer tile: activation is
  a property of a budget automation, and the UI says so.
- ✅ **`EditBudgetScheduleForm`** — same toggle, so it can be turned on or off later. Saving
  reconciles and re-applies, as every other schedule edit does.
- ✅ **`ScheduledPane`** — an **ON/OFF** chip beside the default-budget chip, plus `· on/off` in the
  one-line summary, so it's visible without expanding the row.
- ✅ **`HistoryCard`** — a kind filter (All / Budget / Bidding / **On/off**); changing it resets to
  page 1. Start/stop rows have no numeric change (a status isn't a number, and `cm_run_log`'s value
  columns are floats), so for those the **reason** text fills the Change column — `running→paused`
  rather than a bare dash.
- Prettier + oxlint clean, `vite build` ✅, backend 104/104.
- **Gate REMAINING:** the click-through (shared with A2) needs a deploy — the VM must have
  `cm.set_activation` before the UI can enqueue it. Then: arm, and watch one real window open and
  close, attended.

**Dependencies:** A0 → A1 → A2 is the complete on-demand feature and ships on its own.
A3 → A4 → A5 is the automation. A3 may start in parallel with A1/A2 — it needs no Blinkit access.

---

## 10. The design this replaced

Recorded so it isn't re-litigated from scratch.

The first draft built activation as a **separate subsystem**: `cm_activation_schedules` +
`cm_activation_rules`, an `activation.py` engine, a `cm.activation_scheduler` job type, its own
reconciler boundaries, and a precedence chain so the activation engine could ask the budget
automation what budget to send on a resume. It was chosen to keep a new write path out of the
budget engine, which is armed and writing real money.

**The API capture killed it.** Resume carries the budget, so the two engines would have written
the same campaign twice at the same boundary, in an order that mattered, with a cross-engine
lookup to agree on the value. The merged design deletes: two tables, their migration, two job
types, all reconciler scheduling changes, the precedence chain, and the ordering decision.

The isolation argument that motivated the split survives in a better form: **`stop_after_window`
defaults to false, so the RESTART path is unreachable for every schedule live today.** That is
stronger isolation than separate tables would have given, because it is enforced by data rather
than by structure.

---

## 11. Risks and open questions

| #      | Item                                                                                                                                        | Mitigation                                                                                                                                                                  |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R1** | A resume rewrites budget, keywords, bids, pids and dates. A stale detail read silently reverts the bid optimizer's work.                    | AD9 (read immediately before, log the diff) + the golden-payload test (A0.3)                                                                                                |
| ~~R2~~ | ~~Every resume re-dates the campaign (`campaign_start` → today).~~                                                                          | **Closed 2026-08-07 (A1)** — Blinkit ignores the `campaign_start` we send; the campaign keeps its original start date. No client conversation needed. §2.2.                 |
| **R3** | `advertiser_id: 0` is undocumented behaviour copied from one capture. On a multi-account login it might mean "default account".             | AD4 keeps the arm gate; verify on the first attended live resume that advertiser 19802's campaign is what actually changed                                                  |
| ~~R4~~ | ~~Success detection — response bodies not captured~~                                                                                        | **resolved 2026-08-06** — §2.4, both shapes work unchanged                                                                                                                  |
| ~~R5~~ | ~~`ON_HOLD` semantics unconfirmed.~~ | **Resolved 2026-08-08 (Deepansh): Blinkit puts a campaign ON_HOLD when its budget exhausts — it is effectively running, so treat it normally.** The over-cautious guardrail was actively harmful: it skipped the budget write on 5 of the client's 11 automated campaigns, withholding the one write that would have revived them. `held` is now budget-writable and stoppable; only the *restart* is refused, because there is nothing to restart. |
| **R6** | Blinkit may rate-limit or reject rapid status flips.                                                                                        | The rate-limit guardrail caps it; needs one real observation to tune                                                                                                        |
| **R7** | A campaign carrying a _finite_ end date is silently converted to no-end-date by a restart (AD5).                                            | Rare — nearly all Dobra campaigns are already infinite. Log at WARNING when a restart changes a finite end date.                                                            |
| **R11** | The window-end stop can also be lost to the **duplicate-job guard**, not just to a runner outage: the hourly safety poll and the boundary fire are the SAME job type on the same lane, so if a `cm.budget_scheduler` run is still active when the boundary fires, the producer drops that fire. The budget half self-heals at the next poll; the stop half does not (by 03:00 the window no longer counts as *just ended*). | Widens R8's accepted trade rather than adding a new one. Visible as a missing stop row in History. Revisit with the R8 recovery item in the backlog. |
| **R12** | **A bid window that outlasts the budget window never gets its end-of-window reset.** Budget 19:30–01:00 (toggle on) + bid 19:00–02:00: the campaign is stopped at 01:00, so the 01:59 reset finds it stopped and skips — bids stay at their peak and the next restart carries them, so "each night starts at the bid floor" quietly stops holding. | Keep bid windows ending at or before the budget window when the toggle is on. Fixing it properly means the stop path de-escalating bids too (cross-engine), which is why it is documented rather than built. |
| ~~R13~~ | ~~An unrecognised status silently cancelled the window-end STOP.~~ | **Hit in production 2026-08-08, fixed same day.** A 4-minute test window closed while campaign 574687 was still in the transient post-restart `SCHEDULED` state; the engine didn't recognise it, skipped everything, and left the campaign serving at its window budget with nothing left to stop it. Two fixes: `SCHEDULED` → `running` in the adapter map, and — the important one — **the stop is now attempted whatever the status read said**. Only the budget write is gated on status (Blinkit genuinely rejects it on a non-running campaign). Failing to START is cheap; failing to STOP costs money every hour, so an unfamiliar status must reach the transition table and be refused *there*, where it is logged, rather than vanish into a bare skip. |
| ~~R14~~ | ~~A window SHORTER than the misfire grace never triggered its stop.~~ | **Hit in local testing 2026-08-08, fixed.** `_window_just_ended` probed a single instant at `now - grace`; a 15:46–15:49 window fired at 15:49 looked back to 15:44 — before the window opened — found no match, and computed `state=None`, so the engine reverted the budget and never stopped the campaign. The History row read `"no active rule"` rather than `"window ended"`, which is the tell. Now probed as an INTERVAL, minute by minute across the grace. A late fire broke it the same way even on a long window. |
| ~~R15~~ | ~~A spent one-time rule showed as "Scheduled" for the rest of the day.~~ | **Fixed 2026-08-08.** `_expired` compared only `date < today`, so a one-time automation that had already run and reverted still read as upcoming until midnight. Now a `once` rule is ended when its WINDOW closes (overnight-aware). The two edit guards deliberately still use date-only, so rescheduling a spent rule to later the same day stays possible. |
| **R8** | A missed window-end fire means no stop that night (the trade accepted in AD2) — the campaign runs to the next window at its default budget. | Bounded by the default budget, which is the point of reverting first (AD6). Visible in History as a missing stop row. **Recovery deliberately deferred** — see the backlog. |
| ~~R10~~ | ~~An overnight window still matched AT its end time.~~ | **Found + fixed 2026-08-07 building A3.** `_matches_rule`'s two branches disagreed about whether `end_time` belongs to the window: the normal branch is exclusive (`current >= end_time` → out), the overnight branch was inclusive (`current > end_time` → out). So a 19:00–02:00 rule still matched at exactly 02:00 — and it bites in practice because the engine captures `now` *after* opening the browser (~10 s), so the 02:00 fire evaluates at 02:00:10, still `"02:00"`. **Two consequences.** (1) It would have made `stop_after_window` **silently never fire on overnight windows** — the main use case: the 02:00 fire computes "still running", and the 03:00 poll isn't a window end either (the look-back is 5 minutes), so nothing ever stops the campaign. (2) **It was already a live budget bug**: the elevated budget stayed applied at the 02:00 boundary and only reverted at the 03:00 safety poll, so every overnight window has been running ~an extra hour at its raised budget each night. Small enough that nobody traced it. Both branches are now exclusive; all 19 budget-rule tests incl. the three overnight ones pass. |
| **R9** | `DB_POOL_SIZE=3` on the VM still unconfirmed as applied (open item from 2026-07-31).                                                        | Confirm before A1 adds another cm job type                                                                                                                                  |

### Open

**O1 — should a D19-stopped _automation_ (as distinct from Reset) also restart the campaign?**
Reset means "undo" and does (AD10); "stop automating" arguably means "leave everything exactly as
it is". Leaning: leave as-is, and make the UI say which is which. Decide during A0.

_(The earlier O1 — whether to send `campaign_end` or omit it — is settled: send `12/31/9999`. See
AD5.)_

---

## 12. Testing

Same three tiers the rest of v2 uses (assert-based, standalone-runnable — **there is still no
pytest in this repo**; do not add the dependency without a team call).

- **Pure** — transition table, `target_for_now` with the state return, the golden RESTART payload,
  reconciler output. No DB, no Blinkit.
- **Dry-run against real Blinkit** — reads are real, writes structurally impossible. Local is fine
  (an authed API read from a home IP is low risk); the VM is better.
- **Live** — attended only, on campaign 574687, off-peak, reverted immediately, and verified by
  read-back rather than by the status field alone.

⚠️ **Never run `cli runner start` without `--only-cm` locally** — laptop and VM share one
database, so a bare local runner claims VM jobs and scrapes from a home IP.

---

## 13. Backlog _(append here whenever something is deferred mid-build — the convention from V0–V6)_

- **Recovering a missed window-end stop (R8).** Deferred as an edge case 2026-08-06. The whole
  knob is `_window_just_ended`'s `grace` (§5.1), currently the scheduler's 5-minute misfire grace,
  which is why the hourly poll never cleans up a missed stop. Widening it to ~70 minutes would let
  the next poll recover a brief outage, at the cost of stopping a campaign whose schedule was
  created shortly _after_ a window ended. A full fix bounds the lookback by the schedule's
  `created_at` (already on the row) so it can tell "we missed the stop" from "that window ended
  before this automation existed" — the distinction the rules alone can't make. Note that
  once-only schedules have no poll at all, so no grace value recovers them.
- **Gate the RESUME direction on `allowed_transitions`** — a stopped campaign reports
  `['RESTART']`, which is authoritative where our table is inferred. Resume only: the list covers
  PUT request types, so the `DELETE` stop never appears in it (§2.3).
- **Manual-override handling** — today the hourly poll will restart a campaign someone stopped by
  hand mid-window. Revisit only if that actually happens.
- Starting a `DRAFT` (needs its own capture; on-demand only per AD8).
- Bulk activation ("start every campaign in this group") — the engine already loops; the UI doesn't.
- Surface `ON_HOLD` in the dashboard as an alert — 5 campaigns sit in it and nobody is told.
- Per-window stop granularity, if a campaign ever genuinely needs _some_ windows to end in a stop
  and others not.
- Abstract `marketplaces/base.py` — **only** when MP #2 lands (**D17**). Until then the canonical
  `running`/`paused` vocabulary and the adapter's mapping are the whole multi-marketplace story.
