"""The deadman check's "is this schedule overdue?" rule. Pure: no DB, no marketplace.

The real-world case this exists for: `auto:cm:bid:<tenant>:blinkit:opt` fires
`*/15 15-17 * * *`, so it runs every 15 minutes between 15:00 and 17:45 and never outside
that. The old check derived a cadence from the next two fires — 15 minutes — and demanded
a success that often ALL DAY, so every hour from 18:00 to 15:00 raised an alert. The rule
here asks whether anything has succeeded since the schedule was last DUE instead.

    python -m jobs.tests.test_deadman
"""
from datetime import datetime, timedelta

from jobs.monitor import _ago, missed_fire
from jobs.scheduler import previous_fire_before

GRACE = 300                                  # SCHEDULER_MISFIRE_GRACE_SECONDS on the VM
BID_CRON = "*/15 15-17 * * *"                # the Dobra optimiser: in-window only
DAILY = "0 12 * * *"
# ⚠️ TUESDAYS, not Mondays. `CronTrigger.from_crontab` reads day-of-week the APScheduler
# way (0 = Monday), so the repo's `0 10 * * 1` weeklies fire a day later than a crontab
# reader expects — `DOBRA | Blinkit scorecard weekly` is next due Tue 2026-09-15. Asserted
# here as it actually behaves; changing it would move real schedules.
WEEKLY = "0 10 * * 1"
ONCE_A_YEAR = "*/15 15-17 11 9 *"            # a spent `once` bid cron: 11 Sep only
CREATED = datetime(2026, 1, 1)               # old enough never to be the reason


def _missed(cron=BID_CRON, *, last, now, created=CREATED):
    return missed_fire(cron, last_success=last, created_at=created, now=now,
                       grace_seconds=GRACE)


# ── previous_fire_before ─────────────────────────────────────────────────────

def test_previous_fire_walks_back_within_a_window():
    assert previous_fire_before(BID_CRON, datetime(2026, 9, 12, 16, 20)) == \
        datetime(2026, 9, 12, 16, 15)


def test_previous_fire_crosses_the_overnight_gap():
    # 09:00 on a Saturday — the last fire was 17:45 the evening before, NOT 15 min ago.
    assert previous_fire_before(BID_CRON, datetime(2026, 9, 12, 9, 0)) == \
        datetime(2026, 9, 11, 17, 45)


def test_previous_fire_daily_and_weekly():
    assert previous_fire_before(DAILY, datetime(2026, 9, 12, 9, 0)) == \
        datetime(2026, 9, 11, 12, 0)
    # Saturday 12 Sep 2026 → the weekly's last fire was Tuesday the 8th.
    assert previous_fire_before(WEEKLY, datetime(2026, 9, 12, 9, 0)) == \
        datetime(2026, 9, 8, 10, 0)


def test_previous_fire_reaches_back_a_year():
    # Widening lookbacks must find last year's fire, not give up at 40 days.
    assert previous_fire_before(ONCE_A_YEAR, datetime(2026, 9, 1)) == \
        datetime(2025, 9, 11, 17, 45)


# ── the false alarm this fix is for ──────────────────────────────────────────

def test_night_after_the_bid_window_is_quiet():
    """18:00 yesterday was the last run; at 10:00 the next morning that is still fine."""
    assert _missed(last=datetime(2026, 9, 11, 18, 0),
                   now=datetime(2026, 9, 12, 10, 0)) is None


def test_every_hour_of_the_night_is_quiet():
    last = datetime(2026, 9, 11, 17, 46)
    for hour in range(18, 24):
        assert _missed(last=last, now=datetime(2026, 9, 11, hour, 0)) is None, hour
    for hour in range(0, 15):
        assert _missed(last=last, now=datetime(2026, 9, 12, hour, 0)) is None, hour


def test_a_missed_in_window_fire_is_still_caught():
    """Same schedule, but the 15:00 and 15:15 runs never happened."""
    assert _missed(last=datetime(2026, 9, 11, 17, 46),
                   now=datetime(2026, 9, 12, 15, 30)) == datetime(2026, 9, 12, 15, 15)


def test_a_run_inside_the_grace_is_not_yet_missed():
    """15:15 fired two minutes ago — it has not had time to finish."""
    assert _missed(last=datetime(2026, 9, 12, 15, 0, 40),
                   now=datetime(2026, 9, 12, 15, 17)) is None


def test_success_after_the_due_fire_clears_it():
    assert _missed(last=datetime(2026, 9, 12, 15, 15, 50),
                   now=datetime(2026, 9, 12, 15, 30)) is None


# ── daily / weekly / never-ran ───────────────────────────────────────────────

def test_daily_scrape_overdue_the_hour_after_its_fire():
    assert _missed(DAILY, last=datetime(2026, 9, 10, 12, 20),
                   now=datetime(2026, 9, 11, 13, 0)) == datetime(2026, 9, 11, 12, 0)


def test_daily_scrape_healthy_while_it_is_still_running():
    # Fired at 12:00, heartbeat at 12:00:05 — yesterday's success still covers it.
    assert _missed(DAILY, last=datetime(2026, 9, 10, 12, 20),
                   now=datetime(2026, 9, 11, 12, 0, 5)) is None


def test_weekly_overdue_only_after_its_own_day():
    assert _missed(WEEKLY, last=datetime(2026, 9, 8, 10, 30),
                   now=datetime(2026, 9, 12, 9, 0)) is None
    assert _missed(WEEKLY, last=datetime(2026, 9, 1, 10, 30),
                   now=datetime(2026, 9, 8, 11, 0)) == datetime(2026, 9, 8, 10, 0)


def test_a_new_schedule_is_not_overdue_before_it_existed():
    """A weekly created on Tuesday must not be flagged for the Monday it missed."""
    assert _missed(WEEKLY, last=None, now=datetime(2026, 9, 9, 12, 0),
                   created=datetime(2026, 9, 8, 12, 0)) is None


def test_never_succeeded_is_reported_once_a_fire_has_passed():
    assert _missed(DAILY, last=None, now=datetime(2026, 9, 9, 13, 0),
                   created=datetime(2026, 9, 8, 13, 0)) == datetime(2026, 9, 9, 12, 0)


# ── formatting ───────────────────────────────────────────────────────────────

def test_ago_reads_as_minutes_then_hours():
    assert _ago(timedelta(minutes=40)) == "40 min"
    assert _ago(timedelta(hours=16)) == "16h"


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
    print(f"\n{len(tests) - failed}/{len(tests)} deadman tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
