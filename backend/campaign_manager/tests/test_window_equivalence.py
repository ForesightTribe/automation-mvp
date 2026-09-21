"""window.py must answer what the implementations it replaced answered — except where the
ended-automations fix changed that on purpose, and there it must answer what is TRUE.

`campaign_manager/window.py` took over window matching from `bid._in_window`,
`bid._window_start`, `budget._matches_rule`, `budget._window_just_ended`, the API's
`_expired` / `_once_window_end`, and the reconciler's planning helpers. Every one of those
decides when real bids and budgets move, so "looks equivalent" is not the bar.

`fixtures_window_golden.json` was captured on 2026-09-10 by running the OLD code over 1,217
rule shapes — recurring and one-time; no times, overnight, start == end; date ranges
before, around and after the reference day; weekday filters (one capitalised); budget time
slots; one-time rules carrying `days` and a date range they must ignore — at 25 instants
placed on every boundary those shapes have (both sides of midnight, 01:59/02:00,
08:59/09:00, 23:29/23:30 …). At capture time window.py matched all of them.

⚠️ A RECORD OF WHAT SHIPPED, not a specification. Three answers were first changed
deliberately (2026-09-10) because what shipped was wrong:

  - `is_expired` — minute-precise for recurring rules (it was date-granular), and true for a
    rule that can never open. Checked against a BRUTE-FORCE oracle instead of the fixture,
    plus a guard proving the change moved in both directions.
  - `reconciler._bid_split` — follows `is_expired`, so an overnight tail is no longer cut off
    at midnight. Checked against its specification.
  - `reconciler.budget_boundaries` — drops rules whose last window has closed. Checked as
    "what shipped, minus the expired".

And one on 2026-09-18:

  - `reconciler._bid_reset_fires` — an all-day rule gets a 23:59 reset where its run of days
    ends (it got none). Checked as "what shipped, plus the all-day close".

Everything else is still held to exactly what shipped. Never edit the fixture to make a
failing test pass.

    python -m campaign_manager.tests.test_window_equivalence
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.services import campaign_manager_service as svc
from campaign_manager import bid, budget, reconciler, window

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures_window_golden.json").read_text(encoding="utf-8"))
INSTANTS = [datetime.fromisoformat(s) for s in FIXTURE["instants"]]
ACTIVE_NOWS = [datetime.fromisoformat(s) for s in FIXTURE["active_nows"]]
FIRE_NOWS = [datetime.fromisoformat(s) for s in FIXTURE["fire_nows"]]
CASES = FIXTURE["cases"]
REFERENCE_DAY = datetime(2026, 8, 12)
_ACTIVE = SimpleNamespace(state="active")


# ── Rebuilding each case the way its caller sees it ─────────────────────────

def _full(f: dict) -> dict:
    """The fixture omits empty fields; restore them."""
    return {"type": f.get("type", "recurring"), "date": f.get("date"),
            "days": f.get("days", []), "start_date": f.get("start_date"),
            "end_date": f.get("end_date"), "start_time": f.get("start_time"),
            "end_time": f.get("end_time"), "time_slots": f.get("time_slots", [])}


def _bid_dict(f: dict) -> dict:
    return {"type": f["type"], "date": f["date"], "days": f["days"],
            "start_date": f["start_date"], "stop_date": f["end_date"],
            "start_time": f["start_time"], "stop_time": f["end_time"]}


def _budget_dict(f: dict) -> dict:
    return {"type": f["type"], "date": f["date"], "days": f["days"],
            "time_slots": f["time_slots"], "start_time": f["start_time"],
            "end_time": f["end_time"], "start_date": f["start_date"],
            "end_date": f["end_date"], "budget": 1}


def _bid_rule(f: dict) -> SimpleNamespace:
    return SimpleNamespace(state="active", **_bid_dict(f))


def _budget_rule(f: dict) -> SimpleNamespace:
    return SimpleNamespace(id=1, **_budget_dict(f))


def _bits(values) -> str:
    return "".join("1" if v else "0" for v in values)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="minutes") if dt else None


def _compare(name: str, key: str, compute) -> None:
    """Run `compute(fields)` for every case that recorded `key`; name the first few misses."""
    bad, checked = [], 0
    for case in CASES:
        if key not in case:
            continue
        checked += 1
        f = _full(case["f"])
        got = compute(f)
        if got != case[key]:
            bad.append((f, case[key], got))
    assert checked, f"{name}: no case recorded `{key}` — the fixture is empty or was renamed"
    assert not bad, f"{name}: {len(bad)}/{checked} cases differ from what shipped:" + "".join(
        f"\n      {f}\n        old = {old!r}\n        new = {new!r}" for f, old, new in bad[:3])


def _expired_now(f: dict, t: datetime) -> bool:
    return window.is_expired(window.from_budget(_budget_dict(f)), t)


# ── The brute-force oracle for "has this rule finished for good" ─────────────

_PROBE_TIMES = ("00:00", "06:00", "12:00", "18:00", "22:00")


def _oracle_expired(w: window.Window, t: datetime) -> bool:
    """Closed at `t`, and closed at every later moment a window could open?

    A window can only START at midnight, at its own start time or at a slot boundary, so
    probing exactly those — on every day from the day before `t` to past the rule's last
    possible day — sees any window still to come. No reasoning about tails, weekdays or
    ranges: `in_window` (pinned above to what shipped) is asked directly.
    """
    if window.in_window(w, t):
        return False
    last = w.date if w.type == "once" else w.end_date
    if last:
        horizon = datetime.strptime(last, "%Y-%m-%d") + timedelta(days=2)
    else:
        start = datetime.strptime(w.start_date, "%Y-%m-%d") if w.start_date else t
        horizon = max(t, start) + timedelta(days=8)
    times = sorted({*_PROBE_TIMES, *([w.start_time] if w.start_time else [])})
    day = (t - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= horizon:
        for hhmm in times:
            probe = day.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]))
            if probe > t and window.in_window(w, probe):
                return False
        day += timedelta(days=1)
    return True


# ── window.py itself — held to what shipped ─────────────────────────────────

def test_in_window_budget_vocabulary():
    _compare("in_window (budget)", "ig", lambda f: _bits(
        window.in_window(window.from_budget(_budget_dict(f)), t) for t in INSTANTS))


def test_in_window_bid_vocabulary():
    _compare("in_window (bid)", "ib", lambda f: _bits(
        window.in_window(window.from_bid(_bid_dict(f)), t) for t in INSTANTS))


def test_window_start():
    def compute(f):
        w = window.from_bid(_bid_dict(f))
        return [[k, _iso(window.window_start(w, t))]
                for k, t in enumerate(INSTANTS) if window.in_window(w, t)]
    _compare("window_start", "ws", compute)


def test_was_open_within():
    for grace, key in ((300, "o5"), (900, "o15")):
        _compare(f"was_open_within ({grace}s)", key, lambda f, g=grace: _bits(
            window.was_open_within([window.from_budget(_budget_dict(f))], t, g)
            for t in INSTANTS))


def test_date_passed():
    _compare("date_passed", "xd", lambda f: _bits(
        window.date_passed(window.from_budget(_budget_dict(f)), t) for t in INSTANTS))


def test_window_close():
    _compare("window_close", "we", lambda f: _iso(
        window.window_close(f["date"], f["start_time"], f["end_time"])))


# ── is_expired — changed on purpose, held to the truth ──────────────────────

def test_is_expired_matches_the_brute_force_oracle():
    bad, checked = [], 0
    for case in CASES:
        f = _full(case["f"])
        w = window.from_budget(_budget_dict(f))
        for t in INSTANTS:
            checked += 1
            want, got = _oracle_expired(w, t), window.is_expired(w, t)
            if want != got:
                bad.append((f, t, want, got))
    assert not bad, f"is_expired disagrees with the oracle in {len(bad)}/{checked} cases:" + "".join(
        f"\n      {f} @ {t}\n        oracle = {w}\n        is_expired = {g}" for f, t, w, g in bad[:3])


def test_is_expired_changed_in_both_directions():
    """The proof the fix is the intended one, not a shift: against what SHIPPED, some recurring
    rules now end EARLIER (the day their last window closes, not the midnight after) and some
    LATER (an overnight tail past the end date is no longer cut off)."""
    earlier = later = 0
    for case in CASES:
        f = _full(case["f"])
        if f["type"] == "once":
            continue
        for k, t in enumerate(INSTANTS):
            old, new = case["xe"][k] == "1", _expired_now(f, t)
            earlier += new and not old
            later += old and not new
    assert earlier, "no recurring rule now ends on the day its last window closes"
    assert later, "no overnight tail is kept alive past its end date"


def test_bid_and_budget_vocabulary_agree_on_expiry():
    for case in CASES:
        if "ib" not in case:
            continue
        f = _full(case["f"])
        for t in INSTANTS[::4]:
            assert (window.is_expired(window.from_bid(_bid_dict(f)), t)
                    == _expired_now(f, t)), f"vocabularies disagree for {f} @ {t}"


# ── The entry points callers actually use ────────────────────────────────────

def test_engine_adapters_agree():
    """`bid._in_window` / `_window_start` and `budget._matches_rule` / `_window_just_ended`
    are the engines' views of window.py — pinned too, so a slip in the vocabulary
    translation cannot hide behind a passing window.py."""
    _compare("bid._in_window", "ib", lambda f: _bits(
        bid._in_window(_bid_dict(f), t) for t in INSTANTS))
    _compare("bid._window_start", "ws", lambda f: [
        [k, _iso(bid._window_start(_bid_dict(f), t))]
        for k, t in enumerate(INSTANTS) if bid._in_window(_bid_dict(f), t)])
    _compare("budget._matches_rule", "ig", lambda f: _bits(
        budget._matches_rule(_budget_dict(f), t) for t in INSTANTS))
    for grace, key in ((300, "o5"), (900, "o15")):
        _compare(f"budget._window_just_ended ({grace}s)", key, lambda f, g=grace: _bits(
            budget._window_just_ended([_budget_dict(f)], t, grace_seconds=g)
            for t in INSTANTS))


def test_api_status_projection_agrees():
    """The UI's label for an active rule is the calendar state: running if its window is open
    (pinned to what shipped), else ended if it has expired (held to the oracle above), else
    scheduled. `_bid_ended` reads the service's OWN `now_ist`, which is what lets the
    lifecycle tests pin its clock."""
    def label(open_bit: str, expired: bool) -> str:
        return "running" if open_bit == "1" else "ended" if expired else "scheduled"

    real, bad, checked = svc.now_ist, [], 0
    try:
        for case in CASES:
            f = _full(case["f"])
            budget_rule = _budget_rule(f)
            bid_rule = _bid_rule(f) if "ib" in case else None
            for k, t in enumerate(INSTANTS):
                checked += 1
                expired = _expired_now(f, t)
                want = label(case["ig"][k], expired)
                got = svc._budget_rule_status(budget_rule, t)
                if got != want:
                    bad.append(("_budget_rule_status", f, t, want, got))
                if bid_rule is None:
                    continue
                want = label(case["ib"][k], expired)
                got = svc._bid_status(bid_rule, t)
                if got != want:
                    bad.append(("_bid_status", f, t, want, got))
                svc.now_ist = lambda t=t: t
                if svc._bid_ended(bid_rule) != expired:
                    bad.append(("_bid_ended", f, t, expired, svc._bid_ended(bid_rule)))
    finally:
        svc.now_ist = real
    assert checked, "no status cases checked"
    assert not bad, f"{len(bad)} status answers are wrong:" + "".join(
        f"\n      {fn} {f} @ {t}\n        want = {w!r}\n        got  = {g!r}"
        for fn, f, t, w, g in bad[:3])


# ── Reconciler planning ──────────────────────────────────────────────────────

def test_reconciler_bid_split_keeps_exactly_the_rules_with_windows_left():
    """Changed on purpose: a rule leaves the plan when its last window CLOSES, not when its
    date passes (which cut an overnight tail off at midnight)."""
    def compute(f):
        out = []
        for t in INSTANTS:
            recurring, once = reconciler._bid_split([_bid_rule(f)], t)
            out.append(bool(recurring) or any(once.values()))
        return _bits(out)

    def spec(f):
        return _bits((bool(f["date"]) if f["type"] == "once" else True)
                     and not window.is_expired(window.from_bid(_bid_dict(f)), t)
                     for t in INSTANTS)

    bad = [(f, spec(f), compute(f)) for f in (_full(c["f"]) for c in CASES if "bs" in c)
           if spec(f) != compute(f)]
    assert not bad, f"_bid_split differs from its spec in {len(bad)} cases: {bad[:3]}"


def test_reconciler_reset_fires_are_what_shipped_plus_the_all_day_close():
    """Changed on purpose (2026-09-18): an all-day rule now gets a reset where its run of days
    ENDS — 23:59 on a `once` date, a daily 23:59 cron for a recurring rule with a weekday
    filter or an end date. What shipped gave all-day rules no reset at all. Every other shape
    is still held to exactly what shipped."""
    def all_day(f):
        return window.is_all_day(window.from_bid(_bid_dict(f)))

    def once_want(case, f):
        extra = (datetime.strptime(f["date"], "%Y-%m-%d").replace(hour=23, minute=59)
                 if f["date"] and all_day(f) else None)
        return [sorted(set(shipped) | ({_iso(extra)} if extra and extra > t else set()))
                for shipped, t in zip(case["rf"], FIRE_NOWS)]

    def rec_want(case, f):
        closes = window.all_day_closes(window.from_bid(_bid_dict(f)))
        return case["rc"] + (["59 23 * * *"] if closes and "59 23 * * *" not in case["rc"] else [])

    bad, checked, added = [], 0, 0
    for case in CASES:
        f = _full(case["f"])
        if "rf" in case:
            checked += 1
            got = [sorted(_iso(d.next_run_at) for d in reconciler._bid_reset_fires(
                [], {f["date"]: [_bid_rule(f)]}, "T", "blinkit", t)) for t in FIRE_NOWS]
            want = once_want(case, f)
            added += want != case["rf"]
            if got != want:
                bad.append(("once", f, want, got))
        if "rc" in case:
            checked += 1
            got = [d.cron for d in reconciler._bid_reset_fires(
                [_bid_rule(f)], {}, "T", "blinkit", REFERENCE_DAY)]
            want = rec_want(case, f)
            added += want != case["rc"]
            if got != want:
                bad.append(("recurring", f, want, got))
    assert checked, "no reset-fire cases recorded"
    assert added, "no all-day shape gained a reset — the fixture no longer covers the change"
    assert not bad, f"_bid_reset_fires wrong in {len(bad)}/{checked} cases:" + "".join(
        f"\n      {k} {f}\n        want = {w!r}\n        got  = {g!r}" for k, f, w, g in bad[:3])


def test_reconciler_budget_boundaries_are_what_shipped_minus_the_expired():
    bad = []
    for case in CASES:
        f = _full(case["f"])
        for t in ACTIVE_NOWS:
            want = [] if _expired_now(f, t) else case["bb"]
            got = sorted([list(hm) for hm in reconciler.budget_boundaries(
                [(_ACTIVE, [_budget_rule(f)])], t)])
            if got != want:
                bad.append((f, t, want, got))
    assert not bad, f"budget_boundaries wrong in {len(bad)} cases: {bad[:3]}"


def test_reconciler_once_fires():
    _compare("reconciler._once_fires", "of", lambda f: [
        sorted(_iso(d.next_run_at) for d in reconciler._once_fires(
            [(_ACTIVE, [_budget_rule(f)])], "T", "blinkit", t))
        for t in FIRE_NOWS])


def test_reconciler_rule_hours():
    bad = []
    for key, hours in FIXTURE["rule_hours"].items():
        s, e = (None if v == "None" else v for v in key.split("|"))
        got = sorted(reconciler._rule_hours(s, e))
        if got != hours:
            bad.append((key, hours, got))
    assert FIXTURE["rule_hours"], "no rule_hours recorded"
    assert not bad, f"_rule_hours differs from what shipped: {bad[:3]}"


# ── Guard ────────────────────────────────────────────────────────────────────

def test_the_fixture_actually_covers_the_shapes():
    """A guard against the suite passing vacuously — a truncated fixture, or a matrix where
    every answer is the same, would make every comparison above trivially true.

    Lowering these numbers is only correct alongside a deliberate re-capture."""
    assert len(CASES) == 1217, f"expected 1217 rule shapes, found {len(CASES)}"
    assert len(INSTANTS) == 25, f"expected 25 instants, found {len(INSTANTS)}"
    for key in ("ig", "ib", "o5", "o15", "xe", "xd", "bs"):
        joined = "".join(c[key] for c in CASES if key in c)
        assert "1" in joined and "0" in joined, f"`{key}` has only one answer — vacuous"
    flips = sum(1 for c in CASES if "ib" in c and "01" in c["ib"] and "10" in c["ib"])
    assert flips > 100, f"only {flips} shapes both open and close across the instants"


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} window-equivalence tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
