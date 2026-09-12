"""What an automation's END means — the settle-once teardown (MP-agnostic, pure).

Two kinds of fact are stored per automation (`cm_bid_rules`, `cm_budget_schedules`):

- **`ended_at` is a materialization.** When its last window closed — or, for an automation
  that could never open, when it was created. Derivable from the row at any moment; written
  by the reconciler's sweep for the UI and for SQL, and never read by an engine.
- **`settled_at` + `settle_attempts` are facts.** The final teardown (bid back to its floor;
  budget back to its default, the campaign stopped if the toggle is on) actually landed.
  Nothing else knows that, which is why it is the one stored value that changes what an
  engine does.

A latch only covers the ending it was written for: it is valid while `settled_at >= close`.
So moving an automation's dates forward needs no unlatching — its next ending is later than
any settle, and is unsettled by construction. The migration gave every existing row
`settled_at` = the migration time, which is exactly "every ending that already happened is
done".

Settling is a SAFETY NET for a final end-of-window run that never landed — the runner was
down, or the write failed. It is bounded twice: `SETTLE_MAX_ATTEMPTS`, and
`SETTLE_MAX_AGE_HOURS` after the close. Past that a person has had time to take over, and
tearing down would overwrite their decision — the exact harm the ended-automations fix
exists to stop (2026-09-09: a budget chosen by hand, replaced by an automation that had
ended two days earlier).
"""
from datetime import datetime, timedelta

from campaign_manager import config, window


def rule_close(w: window.Window) -> datetime | None:
    """When one rule's last window closes (see `window.last_window_close`); None when it has
    no last window or a date cannot be read."""
    try:
        return window.last_window_close(w)
    except ValueError:
        return None


def schedule_close(windows) -> datetime | None:
    """When a budget schedule's LAST window closes: the latest close across its windows.

    None while any window has no last close, and for a schedule with no windows at all — it
    exists to enforce its default budget and never ends."""
    closes = [rule_close(w) for w in windows]
    if not closes or any(c is None for c in closes):
        return None
    return max(closes)


def ended_at(close: datetime | None, created_at: datetime | None,
             now: datetime) -> datetime | None:
    """The `ended_at` to store: the close once it has passed, or `created_at` for an automation
    that could never open. None while it has not ended."""
    if close is None or close > now:
        return None
    return created_at if close == datetime.min else close


def needs_settle(close: datetime | None, state: str, settled_at: datetime | None,
                 attempts: int | None, now: datetime) -> bool:
    """Has this automation ENDED without its final teardown landing — recently enough that
    tearing it down now is still the automation's call, not an override of a person's?

    Only an `active` automation settles. A paused one was told to make no writes, and the
    user's choice outranks the calendar; Reset is how a person tears a paused one down.
    An automation that never opened has nothing to tear down.
    """
    if state != "active" or close is None or close == datetime.min or close > now:
        return False
    if settled_at is not None and settled_at >= close:
        return False
    if (attempts or 0) >= config.SETTLE_MAX_ATTEMPTS:
        return False
    return now - close <= timedelta(hours=config.SETTLE_MAX_AGE_HOURS)


def revert_owed(last_close: datetime | None, created_at: datetime | None,
                settled_at: datetime | None, now: datetime) -> bool:
    """Has a window closed whose revert-to-default never landed?

    The budget engine acts on the EDGES of a window — it applies a rule while one is open and
    reverts at the close — so between windows it must do nothing at all. That leaves one gap:
    a close whose revert was missed (the runner was down, the write was refused) would sit at
    the raised budget until the next window. This is that gap's answer, and the reason the
    engine can be edge-triggered safely.

    `settled_at` is the latch, and it means "the most recent close this schedule has been torn
    down for". A close is owed until a revert lands at or after it; `needs_settle` is this same
    question asked only of the LAST close, with retry limits, because that one also ends the
    automation's life.

    Two guards keep a latch from acting on something that was never its business:
      - a close BEFORE the schedule existed is not owed — a schedule created at 14:00 must not
        revert for a window that closed at 02:00 that morning;
      - a close older than `SETTLE_MAX_AGE_HOURS` is not owed either. Past that the campaign's
        budget is whatever the last day made it, and re-asserting a default nobody asked for is
        the very behaviour this replaces.
    """
    if last_close is None or last_close == datetime.min or last_close > now:
        return False
    if created_at is not None and last_close <= created_at:
        return False
    if settled_at is not None and settled_at >= last_close:
        return False
    return now - last_close <= timedelta(hours=config.SETTLE_MAX_AGE_HOURS)


def settle_stamp(close: datetime | None, now: datetime) -> datetime:
    """The `settled_at` to write — never earlier than the close it settles.

    The end-of-window bid reset fires a minute BEFORE the stop, so stamping it with `now`
    would produce a latch that reads as not covering the very ending it tore down."""
    if close is None or close == datetime.min:
        return now
    return max(now, close)


def marker_changes(close: datetime | None, created_at: datetime | None,
                   stored_ended_at: datetime | None, settled_at: datetime | None,
                   attempts: int | None, now: datetime) -> dict:
    """What the reconciler's sweep should write for one automation: {column: value}, only for
    columns whose stored value is wrong — empty when nothing changes, so sweeping live
    automations writes nothing.

    - `ended_at` follows the rules both ways: set once the last window has closed, cleared
      when the dates are moved so that it has not.
    - While NOT ended, attempts go back to 0 — a reopened automation starts its next ending
      with a full set of retries.

    `settled_at` is never cleared here. It used to be, for any automation that had not ended,
    on the reasoning that a stamp which cannot cover the coming ending is stale. It is not:
    the stamp records the most recent close that was torn down (`revert_owed`), which is what
    keeps the budget engine from re-asserting a default between windows, and the sweep runs on
    every edit — clearing it would re-arm a revert that had already landed. Nothing is lost,
    because every reader compares `settled_at >= close` rather than treating it as a flag: a
    stamp from an earlier close is automatically not a latch on a later one.
    """
    ended = close is not None and close <= now
    want_ended = ended_at(close, created_at if created_at is not None else now, now)
    want_settled, want_attempts = settled_at, attempts or 0
    if not ended:
        want_attempts = 0
    out: dict = {}
    if want_ended != stored_ended_at:
        out["ended_at"] = want_ended
    if want_settled != settled_at:
        out["settled_at"] = want_settled
    if want_attempts != (attempts or 0):
        out["settle_attempts"] = want_attempts
    return out


# ── The same questions, asked of the rows themselves ─────────────────────────
#
# One place turns a bid rule or a budget schedule into the arguments above, so the budget
# engine, the bid engine and the reconciler cannot drift apart on what "needs settling" means.

def bid_rule_close(rule) -> datetime | None:
    return rule_close(window.from_bid(rule))


def bid_rule_needs_settle(rule, now: datetime) -> bool:
    return needs_settle(bid_rule_close(rule), getattr(rule, "state", "active"),
                        getattr(rule, "settled_at", None),
                        getattr(rule, "settle_attempts", 0), now)


def bid_rule_markers(rule, now: datetime) -> dict:
    return marker_changes(bid_rule_close(rule), getattr(rule, "created_at", None),
                          getattr(rule, "ended_at", None), getattr(rule, "settled_at", None),
                          getattr(rule, "settle_attempts", 0), now)


def budget_schedule_close(rules) -> datetime | None:
    return schedule_close([window.from_budget(r) for r in rules])


def schedule_needs_settle(schedule, rules, now: datetime) -> bool:
    return needs_settle(budget_schedule_close(rules), getattr(schedule, "state", "active"),
                        getattr(schedule, "settled_at", None),
                        getattr(schedule, "settle_attempts", 0), now)


def schedule_previous_close(rules, now: datetime) -> datetime | None:
    return window.schedule_previous_close([window.from_budget(r) for r in rules], now)


def schedule_revert_owed(schedule, rules, now: datetime) -> bool:
    """Does this schedule owe a revert to its default — the budget engine's failsafe?"""
    if getattr(schedule, "state", "active") != "active":
        return False
    return revert_owed(schedule_previous_close(rules, now),
                       getattr(schedule, "created_at", None),
                       getattr(schedule, "settled_at", None), now)


def schedule_markers(schedule, rules, now: datetime) -> dict:
    return marker_changes(budget_schedule_close(rules), getattr(schedule, "created_at", None),
                          getattr(schedule, "ended_at", None),
                          getattr(schedule, "settled_at", None),
                          getattr(schedule, "settle_attempts", 0), now)


# ── What the client reads in History ─────────────────────────────────────────
#
# An automation's lifecycle is recorded in `cm_run_log` beside the decisions it made, so "is
# this automation done?" is answered on the page. None of these is a write to the marketplace:
# they are outside the rate limit's `repo._WRITE_ACTIONS` and outside
# `repo.NO_CHANGE_ACTIONS`, so they never count as writes and always show in the default view.

ENDED, REOPENED, SETTLED, SETTLE_FAILED = "ended", "reopened", "settled", "settle-failed"
ACTIONS = frozenset({ENDED, REOPENED, SETTLED, SETTLE_FAILED})

REOPENED_REASON = "this automation's dates were moved forward, so it will run again"


def history_row(*, tenant_id, platform: str, kind: str, action: str, campaign_id,
                campaign_name, reason: str, timestamp: datetime, keyword: str | None = None,
                rule_id=None, run_id: str | None = None, success: bool = True) -> dict:
    """One lifecycle row, in `cm_run_log`'s shape. `dry_run` is False because nothing here was
    simulated: an ending or a reopening is a fact about the automation, and a final teardown is
    only ever recorded by a live run."""
    return {"tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": kind,
            "campaign_id": campaign_id, "campaign_name": campaign_name, "keyword": keyword,
            "action": action, "old_value": None, "new_value": None, "reason": reason,
            "rule_id": None if rule_id is None else str(rule_id), "position": None,
            "target": None, "dry_run": False, "success": success, "timestamp": timestamp}


def ended_reason(ended: datetime, never_opened: bool) -> str:
    if never_opened:
        return ("this automation's dates and times leave no window it could run in, so it "
                "will never run — change them to use it")
    return (f"this automation's last window closed on {ended:%d %b} at {ended:%H:%M} — it will "
            f"not run again unless its dates are moved forward")


def settled_reason(kind: str) -> str:
    if kind == "bid":
        return ("this automation has ended and its bid is back at its floor — it will not "
                "change this keyword again")
    return ("this automation has ended and its final run is done — it will not change this "
            "campaign again")


def settle_failed_reason(kind: str) -> str:
    what = ("its bid could not be put back to its floor" if kind == "bid"
            else "its final budget change could not be made")
    return (f"this automation has ended, but {what} after {config.SETTLE_MAX_ATTEMPTS} "
            f"attempts, so it was left as it is — check the campaign in the marketplace")


def _transition_row(change: dict, stored_ended_at: datetime | None, close: datetime | None,
                    now: datetime, **row) -> dict | None:
    if "ended_at" not in change:
        return None
    new = change["ended_at"]
    if new is not None and stored_ended_at is None:
        return history_row(action=ENDED, timestamp=new, **row,
                           reason=ended_reason(new, never_opened=close == datetime.min))
    if new is None and stored_ended_at is not None:
        return history_row(action=REOPENED, timestamp=now, reason=REOPENED_REASON, **row)
    return None


def sweep_history(budget_schedules, bid_rules, bid_markers: dict, budget_markers: dict, *,
                  tenant_id, platform: str, run_id: str | None, now: datetime) -> list[dict]:
    """History rows for the transitions a sweep is about to write, computed from the markers as
    stored BEFORE it writes them.

    `ended` when an automation gains an `ended_at` — timestamped AT the close, so the row sits
    where the ending happened rather than wherever the sweep happened to run. `reopened` when
    it loses one, timestamped now. An `ended_at` that moves between two closes (dates edited
    while it stays ended) is not a transition and records nothing."""
    rows = []
    for r in bid_rules:
        row = _transition_row(bid_markers.get(r.id, {}), getattr(r, "ended_at", None),
                              bid_rule_close(r), now, tenant_id=tenant_id, platform=platform,
                              run_id=run_id, kind="bid", campaign_id=r.campaign_id,
                              campaign_name=r.campaign_name, keyword=r.keyword, rule_id=r.id)
        if row:
            rows.append(row)
    for s, rules in budget_schedules:
        row = _transition_row(budget_markers.get(s.id, {}), getattr(s, "ended_at", None),
                              budget_schedule_close(rules), now, tenant_id=tenant_id,
                              platform=platform, run_id=run_id, kind="budget",
                              campaign_id=s.campaign_id, campaign_name=s.campaign_name)
        if row:
            rows.append(row)
    return rows
