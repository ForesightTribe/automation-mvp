"""Rule windows — the ONE implementation of "when does an automation apply" (MP-agnostic).

Every question about a rule's schedule is answered here: is it open now, when did the
current window open, when does a one-time window close, was anything open a moment ago,
has the rule finished for good. Until this module existed the same logic lived in four
places — `bid._in_window`, `budget._matches_rule`, the service's `_expired` and the
reconciler's planning helpers — each with its own idea of when a window is over, and the
place that knew what "ended" meant was the one place no engine could see.

Pure: no DB, no settings, no clock. **`now` is always passed in.** Callers read their own
module's `now_ist()` and hand it over, which is what lets a test pin one module's clock
without reaching into this one.

Two vocabularies, one shape. Bid rules say `stop_time` / `stop_date`; budget rules say
`end_time` / `end_date` and may use `time_slots` instead of times. `from_bid` / `from_budget`
translate either — a dict or an ORM row — into a `Window`, and nothing below them knows
which engine asked.

⚠️ Times and dates are compared as STRINGS inside `in_window`, exactly as both engines always
did. That is correct only for zero-padded `HH:MM` and `YYYY-MM-DD` — which the API enforces on
every rule it accepts (`valid_hhmm` / `valid_date`, applied in the request schemas), so a
hand-written `"9:00"` is refused instead of saved and matched at the wrong times.

Two axes (see "The calendar axis" below): the USER state a person chose is stored on the row;
the CALENDAR state — scheduled / running / ended — is derived here and never stored as a gate.

Equivalence with the four implementations this replaced is pinned by
`tests/test_window_equivalence.py` against outputs recorded from the old code.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Window:
    """A rule's schedule, in one vocabulary. `type` is `"once"` or anything else (recurring)."""
    type: str = "recurring"
    date: str | None = None                 # the single day of a "once" rule
    days: tuple = ()                        # weekday filter; empty = every day
    start_date: str | None = None
    end_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    time_slots: tuple = ()                  # budget only: used when there are no times


def _field(rule, name: str):
    if isinstance(rule, dict):
        return rule.get(name)
    return getattr(rule, name, None)


def from_bid(rule) -> Window:
    """A bid rule (dict or row) → Window. Bid rules have no time slots."""
    return Window(
        type=_field(rule, "type") or "recurring",
        date=_field(rule, "date"),
        days=tuple(_field(rule, "days") or ()),
        start_date=_field(rule, "start_date"),
        end_date=_field(rule, "stop_date"),
        start_time=_field(rule, "start_time"),
        end_time=_field(rule, "stop_time"),
    )


def from_budget(rule) -> Window:
    """A budget rule (dict or row) → Window."""
    return Window(
        type=_field(rule, "type") or "recurring",
        date=_field(rule, "date"),
        days=tuple(_field(rule, "days") or ()),
        start_date=_field(rule, "start_date"),
        end_date=_field(rule, "end_date"),
        start_time=_field(rule, "start_time"),
        end_time=_field(rule, "end_time"),
        time_slots=tuple(_field(rule, "time_slots") or ()),
    )


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_hhmm(s: str | None) -> tuple[int, int] | None:
    """'HH:MM' → (hour, minute); None if empty, unparseable or out of range."""
    if not s:
        return None
    try:
        parts = s.split(":")
        h, m = int(parts[0]), int(parts[1])
    except (ValueError, IndexError, AttributeError):
        return None
    return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None


def current_slot(now: datetime) -> str:
    h = now.hour
    if 6 <= h < 12:
        return "morning"
    if 12 <= h < 18:
        return "afternoon"
    if 18 <= h < 22:
        return "evening"
    return "night"


# ── Is it open? ──────────────────────────────────────────────────────────────

def _time_ok(current: str, start: str | None, end: str | None) -> bool:
    """Is `current` inside [start, end)? `end` is EXCLUSIVE in both branches — an 18:00–02:00
    window is closed AT 02:00. It used to be inclusive on the overnight branch, which made the
    end-of-window reset skip the keyword it fired for and the 02:00 budget fire compute "still
    running" and never stop the campaign (fixed 2026-08-07)."""
    if not (start or end):
        return True
    if start and end and end <= start:           # crosses midnight
        if current < start and current >= end:
            return False
    else:
        if start and current < start:
            return False
        if end and current >= end:
            return False
    return True


def in_window(w: Window, now: datetime) -> bool:
    """Does this rule apply at `now`?

    Time-of-day gate first, then the date/weekday checks against the window's START day: an
    overnight window's post-midnight tail belongs to the day it started, so a Sun 16:00–02:00
    rule runs to Mon 02:00, and a Fri/Sat/Sun filter still covers Sunday's tail. A `once`
    rule matches only its own date and ignores `days` and the date range.
    """
    current = now.strftime("%H:%M")
    start, end = w.start_time, w.end_time
    if start or end:
        if not _time_ok(current, start, end):
            return False
    elif w.time_slots and current_slot(now) not in w.time_slots:
        return False

    overnight = bool(start and end and end <= start)
    in_tail = overnight and current < end
    eff = (now - timedelta(days=1)) if in_tail else now
    eff_date = eff.strftime("%Y-%m-%d")

    if w.type == "once":
        return eff_date == (w.date or "")
    if w.start_date and eff_date < w.start_date:
        return False
    if w.end_date and eff_date > w.end_date:
        return False
    days = [d.lower() for d in w.days]
    if not days:
        return True
    return eff.strftime("%A").lower() in days


def was_open_within(windows, now: datetime, grace_seconds: float) -> bool:
    """Was any of `windows` open at some minute in the last `grace_seconds` (excluding now)?

    Probed as an INTERVAL, minute by minute, never as one instant at `now - grace`: a point
    probe misses every window shorter than the grace, which is how campaign 574687 was left
    running on 2026-08-08. Says nothing about NOW — a caller asking "did a window just end"
    must also check that nothing is open at `now`.
    """
    for minutes_ago in range(1, max(1, int(grace_seconds // 60)) + 1):
        at = now - timedelta(minutes=minutes_ago)
        if any(in_window(w, at) for w in windows):
            return True
    return False


# ── Boundaries ───────────────────────────────────────────────────────────────

def window_start(w: Window, now: datetime) -> datetime:
    """When the CURRENT window opened. Only meaningful while `in_window` is true.

    The overnight tail belongs to the day it started, so at 01:00 an 18:00–02:00 rule reports
    YESTERDAY 18:00 — which is what keeps "first fire of this window" from re-firing at
    midnight. No start time → midnight of the effective day. Seconds are stripped: the result
    is compared against DB timestamps.
    """
    start, end = w.start_time, w.end_time
    sh, sm = parse_hhmm(start) or (0, 0)
    overnight = bool(start and end and end <= start)
    in_tail = overnight and now.strftime("%H:%M") < end
    eff = (now - timedelta(days=1)) if in_tail else now
    return eff.replace(hour=sh, minute=sm, second=0, microsecond=0)


def window_open(date: str, start_time: str | None) -> datetime:
    """When a window on `date` opens (no start time → midnight). Raises ValueError on a bad date."""
    sh, sm = parse_hhmm(start_time) or (0, 0)
    return datetime.strptime(date, "%Y-%m-%d").replace(hour=sh, minute=sm)


def window_close(date: str, start_time: str | None, end_time: str | None) -> datetime:
    """When a window on `date` closes — overnight-aware (end ≤ start → the next day), and a
    window with no end time runs to the following midnight. Raises ValueError on a bad date."""
    base = datetime.strptime(date, "%Y-%m-%d")
    eh, sh = parse_hhmm(end_time), parse_hhmm(start_time) or (0, 0)
    if eh is None:
        return base + timedelta(days=1)
    end = base.replace(hour=eh[0], minute=eh[1])
    return end + timedelta(days=1) if eh <= sh else end


# ── Is it over? ──────────────────────────────────────────────────────────────

_SLOT_BOUNDS = {"morning": ((6, 0), (12, 0)), "afternoon": ((12, 0), (18, 0)),
                "evening": ((18, 0), (22, 0)), "night": ((0, 0), (24, 0))}


def _span_on(w: Window, day: datetime) -> tuple[datetime, datetime] | None:
    """(opens, closes) of the window that STARTS on `day`, from its times or slots alone —
    whether that day is eligible at all is `in_window`'s call. None when the slots name
    nothing real."""
    if not (w.start_time or w.end_time) and w.time_slots:
        bounds = [_SLOT_BOUNDS[s] for s in w.time_slots if s in _SLOT_BOUNDS]
        if not bounds:
            return None
        (oh, om), (ch, cm) = min(b[0] for b in bounds), max(b[1] for b in bounds)
        closes = day + timedelta(days=1) if ch == 24 else day.replace(hour=ch, minute=cm)
        return day.replace(hour=oh, minute=om), closes
    date = day.strftime("%Y-%m-%d")
    return window_open(date, w.start_time), window_close(date, w.start_time, w.end_time)


def _closes_if_open(w: Window, day: datetime) -> datetime | None:
    """When the window starting on `day` closes — or None if it does not open that day."""
    span = _span_on(w, day)
    return span[1] if span and in_window(w, span[0]) else None


def last_window_close(w: Window) -> datetime | None:
    """When this rule's LAST window closes.

    None when there is no last window: a recurring rule with no end date that opens at all.
    `datetime.min` when the rule can never open — a one-time rule with no date, an inverted
    date range, a weekday filter nothing in range matches, an end of 00:00 with no start:
    nothing is left to run. Raises ValueError on an unparseable date.
    """
    if w.type == "once":
        if not w.date:
            return datetime.min
        return _closes_if_open(w, datetime.strptime(w.date, "%Y-%m-%d")) or datetime.min
    if not w.end_date:
        # Eligibility repeats weekly, so if no day of one week opens, no day ever will.
        anchor = (datetime.strptime(w.start_date, "%Y-%m-%d") if w.start_date
                  else datetime(2000, 1, 3))
        opens = any(_closes_if_open(w, anchor + timedelta(days=b)) for b in range(7))
        return None if opens else datetime.min
    end = datetime.strptime(w.end_date, "%Y-%m-%d")
    for back in range(7):                        # the last eligible day is within a week
        day = end - timedelta(days=back)
        if w.start_date and day.strftime("%Y-%m-%d") < w.start_date:
            break
        close = _closes_if_open(w, day)
        if close:
            return close
    return datetime.min


# A week covers every weekday filter; the eighth day catches an overnight window that
# opened on the first eligible day of the previous week and closed after midnight.
_LOOK_BACK_DAYS = 8


def previous_close(w: Window, now: datetime, *, days_back: int = _LOOK_BACK_DAYS) -> datetime | None:
    """The most recent close of this window at or before `now` — None if it has never closed.

    `last_window_close` answers "when does it close for the LAST time"; this answers "when did
    it last close", which is the question an end-of-window action has to ask when it may have
    been missed. A window that opened yesterday at 19:30 and closed at 02:00 today is found by
    scanning back from the day it OPENED, so overnight spans are counted at their close, not
    their start.
    """
    best: datetime | None = None
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for back in range(days_back):
        try:
            close = _closes_if_open(w, midnight - timedelta(days=back))
        except ValueError:                       # unparseable date — it has no windows to close
            return None
        if close is not None and close <= now and (best is None or close > best):
            best = close
    if best is not None:
        return best
    # Older than the scan: a `once` rule from last month still has exactly one close, and
    # a rule whose last window closed before that is what `last_window_close` knows.
    try:
        last = last_window_close(w)
    except ValueError:
        return None
    return last if last is not None and last != datetime.min and last <= now else None


def schedule_previous_close(windows, now: datetime) -> datetime | None:
    """The most recent close across a schedule's rules — the close it owes a revert for."""
    closes = [c for c in (previous_close(w, now) for w in windows) if c is not None]
    return max(closes) if closes else None


def is_expired(w: Window, now: datetime) -> bool:
    """Has this rule finished for good — has its LAST window closed?

    Minute-precise for both kinds of rule. A recurring rule used to count as expired only once
    its end DATE was behind today, which was wrong both ways: a rule whose last window closed at
    19:42 read as live until midnight (and the hourly poll overwrote a budget set by hand at
    19:43), while an overnight window's post-midnight tail was treated as over before it had
    run. Fixed 2026-09-10. A one-time rule that has run and reverted reads as ended the moment
    its window closes, not at midnight.
    """
    try:
        close = last_window_close(w)
    except ValueError:                           # unparseable date — don't claim it ended
        return False
    return close is not None and close <= now


def just_closed(w: Window, now: datetime, grace_seconds: float) -> bool:
    """Is `now` the END of a window — closed now, but open within the last `grace_seconds`?

    The edge, never the level. An end-of-window action gated on this fires once, at the close.
    Gated on "not open" it fires on every run while the rule is outside its window — which is
    how automations that had ended days earlier kept being reset (found 2026-09-10).
    """
    return not in_window(w, now) and was_open_within([w], now, grace_seconds)


def date_passed(w: Window, now: datetime) -> bool:
    """Is the rule's last DATE behind today? A different question from `is_expired`, on
    purpose: it ignores times, so a one-time rule dated today has NOT passed even after its
    window closed. That is what an edit guard wants — rescheduling a spent rule to later the
    same day is the most natural correction, and must not be refused."""
    today = now.strftime("%Y-%m-%d")
    if w.type == "once":
        return bool(w.date and today > w.date)
    return bool(w.end_date and today > w.end_date)


# ── The calendar axis ────────────────────────────────────────────────────────
#
# An automation has two independent states. The USER axis — `active` / `paused` on a bid
# rule, `active` / `stopped` on a budget schedule — is what a person chose, and is stored.
# The CALENDAR axis — scheduled / running / ended — is what the dates say about `now`, and
# is always derived, here. "running" belongs to the calendar alone: nobody can choose it.

SCHEDULED, RUNNING, ENDED = "scheduled", "running", "ended"
ANY_CALENDAR = frozenset({SCHEDULED, RUNNING, ENDED})


def calendar_state(w: Window, now: datetime) -> str:
    """One rule's calendar state. Says nothing about whether anyone paused it."""
    if in_window(w, now):
        return RUNNING
    if is_expired(w, now):
        return ENDED
    return SCHEDULED


def schedule_calendar_state(windows, now: datetime) -> str:
    """A budget schedule's calendar state across all of its windows: running if any window
    is, ended only once EVERY window has. A schedule with no windows is scheduled forever —
    it enforces its default budget and has nothing that could end."""
    states = [calendar_state(w, now) for w in windows]
    if not states:
        return SCHEDULED
    if RUNNING in states:
        return RUNNING
    return ENDED if all(s == ENDED for s in states) else SCHEDULED


# ── Input format ─────────────────────────────────────────────────────────────
#
# `in_window` compares times and dates as STRINGS, which is only correct for zero-padded
# 24-hour `HH:MM` and ISO `YYYY-MM-DD`. The API refuses anything else using these, so the
# format is defined next to the comparisons that depend on it.

def valid_hhmm(s: str) -> bool:
    """Exactly `HH:MM`, zero-padded, 00:00–23:59. `9:00` and `09:00:00` both PARSE, and both
    compare wrongly as strings (`"9:00" > "14:00"`), so both are refused."""
    return (isinstance(s, str) and len(s) == 5 and s.isascii() and s[2] == ":"
            and s[:2].isdigit() and s[3:].isdigit() and parse_hhmm(s) is not None)


def valid_date(s: str) -> bool:
    """Exactly `YYYY-MM-DD`, and a day that exists."""
    if not (isinstance(s, str) and len(s) == 10 and s.isascii()):
        return False
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d") == s
    except ValueError:
        return False
