"""Campaign dates are IST dates, on both sides of the write.

Blinkit stores campaign dates in UTC, and every Indian campaign starts at midnight IST — so
a campaign that starts on 15 July is stored as `2026-07-14T18:30:00+00:00`. Reading the date
off that stamp without converting it yields the 14th, and a whole-campaign PUT carrying the
14th is a PUT that changes the campaign's start date.

That is what shipped, for months, on every UPDATE payload we built (260 of 260 campaigns).
Blinkit ignored it — until overnight on 2026-09-15, when it began answering
`HTTP 400 ['Start Date of Campaign is not allowed to be changed']` and every bid and budget
write stopped landing. The evidence is unusually clean: the last accepted write was 23:46,
the first rejection 00:01, and the payload was byte-identical across the boundary.

**The two halves must move together.** `build.fmt_date` writes the date; `payload.
_date_expected` reads the campaign's own date back to check it. Fix only the builder and
`verify()` refuses every UPDATE itself — "payload says (2026,7,15) but the campaign is
(2026,7,14)" — trading Blinkit's rejection for ours. Fix only the reader and the wrong date
sails through again. `test_both_halves_agree` is the test that fails if either one is
reverted alone.

Pure — no Blinkit, no DB, no browser. Run with:

    python -m campaign_manager.tests.test_campaign_dates
"""
from datetime import datetime, timedelta, timezone

from campaign_manager.marketplaces.blinkit import build, payload as pl

IST = timezone(timedelta(hours=5, minutes=30))

# 18:30 UTC. Midnight IST the next day — the shape of every real campaign's `start_ts`.
MIDNIGHT_IST = "2026-07-14 18:30:00+00:00"
NO_END_DATE = "9999-12-31 18:29:59+00:00"       # Blinkit's no-end-date sentinel

# A campaign as `get_campaign_detail` returns one, with real UTC timestamps.
DETAIL = {
    "name": "Foresight | Tech Test",
    "brand_name": "Dobra",
    "campaign_type": "PRODUCT_LISTING",
    "objective_type": "PERFORMANCE",
    "campaign_budget": 210,
    "pacing_type": "DAILY",
    "pids": "554767,554768",
    "start_ts": MIDNIGHT_IST,
    "end_ts": NO_END_DATE,
    "infinite_campaign": True,
    "region_type": "CITY",
    "region_ids": [2, 787],
    "campaign_targeting": {
        "keyword_targeting": {
            "keywords": [
                {"keyword": "pink toffee", "bids": [{"match_type": "EXACT", "cpm": 210}]},
            ],
        },
    },
}


def _bid_payload(detail: dict | None = None) -> dict:
    return build.build(detail or DETAIL, shape=build.BID, campaign_id=574687,
                       requested_by="ops@foresighttribe.com", advertiser_id=19802,
                       keyword_updates=[{"keyword": "pink toffee",
                                         "match_type": "EXACT", "cpm": 205}],
                       min_cpm={"PRODUCT_LISTING": 500})


# ── the formatter ───────────────────────────────────────────────────────────

def test_utc_evening_is_the_next_ist_day():
    """THE regression. 18:30 UTC is midnight IST tomorrow, not 18:30 today."""
    assert build.fmt_date(MIDNIGHT_IST) == "7/15/2026"


def test_a_z_suffix_converts_too():
    """`Z` and `+00:00` are the same offset, and both have to survive the parse."""
    assert build.fmt_date("2026-07-14T18:30:00Z") == "7/15/2026"


def test_an_offset_that_is_not_utc_is_honoured():
    assert build.fmt_date("2026-07-15T00:00:00+05:30") == "7/15/2026"


def test_naive_timestamps_are_taken_as_ist():
    """`today` is `datetime.now(IST)` and the restart's dates are ours, not Blinkit's —
    nothing to convert, and converting anyway would move them a day."""
    assert build.fmt_date("2026-07-08T18:30:00") == "7/8/2026"
    assert build.fmt_date(datetime(2026, 9, 3)) == "9/3/2026"
    assert build.fmt_date(datetime(2026, 9, 3, tzinfo=IST)) == "9/3/2026"


def test_a_midday_utc_stamp_stays_on_its_own_day():
    """Only the evening stamps cross the date line — a guard against "add a day" as the fix."""
    assert build.fmt_date("2026-07-14 06:00:00+00:00") == "7/14/2026"


def test_the_no_end_date_sentinel_survives():
    """`9999-12-31 18:29:59Z` → `23:59:59` IST the same day. One second of headroom."""
    assert build.fmt_date(NO_END_DATE) == "12/31/9999"


def test_an_unrepresentable_sentinel_does_not_raise():
    """One second later the conversion runs past `datetime.max`. A payload builder is the
    wrong place to raise, so the date is kept as stored."""
    assert build.fmt_date("9999-12-31 18:30:00+00:00") == "12/31/9999"


def test_junk_is_returned_unchanged():
    assert build.fmt_date("not a date") == "not a date"
    assert build.fmt_date("") == ""
    assert build.fmt_date(None) == ""


# ── the two halves ──────────────────────────────────────────────────────────

def test_both_halves_agree():
    """Fixing the builder without the invariant's reader swaps Blinkit's refusal for ours.

    `_date_back` inverts what the builder wrote; `_date_expected` states what the campaign
    IS. They are written independently on purpose (§8.2c) — this asserts they say the same
    thing, and fails the moment either one is reverted alone.
    """
    for key, stamp in (("start_ts", MIDNIGHT_IST), ("end_ts", NO_END_DATE)):
        written = pl._date_back(build.fmt_date(stamp))
        campaign = pl._date_expected({key: stamp}, key)
        assert written == campaign, f"{key}: builder wrote {written}, campaign is {campaign}"


def test_the_invariant_passes_a_real_bid_payload():
    """End to end, pure: build a BID payload from a campaign with UTC timestamps and assert
    the guardrail finds nothing to complain about. This is the failure the outage would have
    produced locally — `check` returning a campaign_start mismatch."""
    assert pl.check(DETAIL, _bid_payload(), shape=pl.BID) == []


def test_a_bid_payload_carries_the_ist_start_date():
    payload = _bid_payload()
    assert payload["campaign_start"] == "7/15/2026"
    assert payload["campaign_end"] == "12/31/9999"


def test_the_old_off_by_one_is_now_caught():
    """The invariant's job is to catch a wrong date, not only to permit a right one.

    Before 2026-09-15 both halves were wrong in the same direction, so the check passed and
    Blinkit was the only thing that noticed. A payload carrying the old UTC date must now be
    refused here, before it reaches a live account.
    """
    stale = {**_bid_payload(), "campaign_start": "7/14/2026"}
    problems = pl.check(DETAIL, stale, shape=pl.BID)
    assert any("campaign_start" in p for p in problems), problems


def test_a_budget_payload_carries_it_too():
    """The start date rides on budget writes as well — the outage stopped both."""
    payload = build.build(DETAIL, shape=build.BUDGET, campaign_id=574687,
                          requested_by="ops@foresighttribe.com", advertiser_id=19802,
                          budget=211.0, min_cpm={"PRODUCT_LISTING": 500})
    assert payload["campaign_start"] == "7/15/2026"
    assert pl.check(DETAIL, payload, shape=pl.BUDGET) == []


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
    print(f"\n{len(tests) - failed}/{len(tests)} campaign-date tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
