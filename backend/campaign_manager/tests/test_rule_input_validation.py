"""Rule times and dates are refused at the API unless they are in the exact format the
window comparisons need — pure, no DB, no marketplace.

`window.in_window` compares `"HH:MM"` and `"YYYY-MM-DD"` as strings. That is correct for
zero-padded values and silently wrong for anything else: `"9:00"` sorts after `"14:00"`, so
a 9:00–20:00 rule saved that way would never be open at 14:00. Nothing refused such values
until 2026-09-10.

    python -m campaign_manager.tests.test_rule_input_validation
"""
from pydantic import ValidationError

from app.schemas.campaign_manager import (
    BidRuleIn, BidRuleOut, BidRuleUpdate, BudgetRuleIn, BudgetRuleOut, BudgetRuleUpdate,
    BudgetScheduleIn,
)
from campaign_manager import window

GOOD_TIMES = ["00:00", "09:00", "12:30", "23:59"]
BAD_TIMES = ["9:00", "24:00", "12:60", "09:00:00", "", " 09:00", "09.00", "noon", "٠٩:٠٠"]
GOOD_DATES = ["2026-09-10", "2024-02-29", "2099-12-31"]
BAD_DATES = ["2026-9-10", "2026-02-30", "2025-02-29", "10-09-2026", "2026/09/10", "",
             "2026-09-10T00:00"]

_BID = {"campaign_id": 1, "keyword": "soda", "target_position": 3, "min_bid": 100}
_BUDGET = {"budget": 500}

# (model, the fields it requires, its time fields, its date fields)
MODELS = [
    (BudgetRuleIn, _BUDGET, ("start_time", "end_time"), ("start_date", "end_date", "date")),
    (BudgetRuleUpdate, {}, ("start_time", "end_time"), ("start_date", "end_date", "date")),
    (BidRuleIn, _BID, ("start_time", "stop_time"), ("start_date", "stop_date", "date")),
    (BidRuleUpdate, {}, ("start_time", "stop_time"), ("start_date", "stop_date", "date")),
]


def _refused(model, **fields) -> bool:
    try:
        model(**fields)
    except ValidationError:
        return True
    return False


def test_good_times_are_accepted_on_every_time_field():
    for model, required, times, _ in MODELS:
        for field in times:
            for t in GOOD_TIMES:
                assert not _refused(model, **required, **{field: t}), (
                    f"{model.__name__}.{field} refused {t!r}")


def test_anything_else_is_refused_on_every_time_field():
    for model, required, times, _ in MODELS:
        for field in times:
            for t in BAD_TIMES:
                assert _refused(model, **required, **{field: t}), (
                    f"{model.__name__}.{field} accepted {t!r}")


def test_good_dates_are_accepted_on_every_date_field():
    for model, required, _, dates in MODELS:
        for field in dates:
            for d in GOOD_DATES:
                assert not _refused(model, **required, **{field: d}), (
                    f"{model.__name__}.{field} refused {d!r}")


def test_anything_else_is_refused_on_every_date_field():
    """Including days that do not exist — a Feb 30 would otherwise compare "fine"."""
    for model, required, _, dates in MODELS:
        for field in dates:
            for d in BAD_DATES:
                assert _refused(model, **required, **{field: d}), (
                    f"{model.__name__}.{field} accepted {d!r}")


def test_null_still_clears_a_field():
    """The dashboard clears a field by sending an explicit null — refusing it would make
    every cleared date unsaveable (the bug `timingPayload` exists to prevent)."""
    for model, required, times, dates in MODELS:
        nulls = {f: None for f in (*times, *dates)}
        assert not _refused(model, **required, **nulls), f"{model.__name__} refused nulls"


def test_the_inline_first_rule_is_checked_too():
    assert _refused(BudgetScheduleIn, campaign_id=1, default_budget=100,
                    rule={"budget": 500, "start_time": "9:00"})
    assert not _refused(BudgetScheduleIn, campaign_id=1, default_budget=100,
                        rule={"budget": 500, "start_time": "09:00"})


def test_the_error_says_what_to_type():
    try:
        BidRuleIn(**_BID, start_time="9:00")
    except ValidationError as e:
        assert "HH:MM" in str(e)
    else:
        raise AssertionError("9:00 was accepted")


def test_output_models_stay_permissive():
    """A row that predates validation must still be listable, or the page it is on breaks
    and nobody can open the rule to fix it."""
    BudgetRuleOut(id=1, budget=500, type="recurring", start_time="9:00", end_date="2026-9-1")
    BidRuleOut(id="x", campaign_id=1, campaign_name="c", keyword="soda", target_position=3,
               min_bid=100, match_type="EXACT", type="recurring", state="active",
               platform="blinkit", start_time="9:00", stop_date="2026-9-1")


def test_every_accepted_time_sorts_the_same_as_a_string_and_a_number():
    """The property validation exists to guarantee — checked over every minute of the day."""
    accepted = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(60)]
    assert all(window.valid_hhmm(t) for t in accepted)
    assert all(window.parse_hhmm(t) == (int(t[:2]), int(t[3:])) for t in accepted)
    assert sorted(accepted) == sorted(accepted, key=window.parse_hhmm)


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
    print(f"\n{len(tests) - failed}/{len(tests)} rule-input-validation tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
