"""Every History row must explain itself, in language a client can read.

`cm_run_log` is becoming a client-facing record: "what did the automation do to my campaign,
and why". A row with an empty `reason`, or one carrying a raw API error, is worse than no row
— it tells someone their bid moved and refuses to say why.

Two rules, both enforced here:
  1. Every row carries a non-empty reason.
  2. A reason is ONE LINE and human. Raw exceptions get summarised, not pasted — a Zepto
     block used to land as four lines of JSON in this column.

    python -m campaign_manager.tests.test_history_reasons
"""
from campaign_manager import bid

# The shape a bid rule's id really has (`cm_bid_rules.id` is a uuid hex), not a tidy int —
# the fixture that used `42` is why the INTEGER column looked fine in tests.
_RULE_ID = "d657c360345f421d866bcde09a702e42"


def _row(**over):
    base = dict(tenant_id="t", platform="blinkit", run_id="r", cid=1, cname="c",
                kw="soda", action="apply", old=100, new=120, reason="because",
                dry_run=False, success=True)
    base.update(over)
    return bid._row(base["tenant_id"], base["platform"], base["run_id"], base["cid"],
                    base["cname"], base["kw"], base["action"], base["old"], base["new"],
                    base["reason"], base["dry_run"], base["success"],
                    rule_id=over.get("rule_id"), position=over.get("position"),
                    target=over.get("target"))


# ── the row carries the decision's inputs ───────────────────────────────────

def test_a_row_records_reason_position_target_and_rule():
    r = _row(reason="raising to ₹120 because position 9 is worse than target 3",
             rule_id=_RULE_ID, position=9.0, target=3)
    assert r["reason"].startswith("raising")
    assert r["rule_id"] == _RULE_ID and r["position"] == 9.0 and r["target"] == 3


def test_the_rule_id_column_accepts_the_id_the_engine_actually_writes():
    """The 2026-09-04 bug: `cm_run_log.rule_id` was created INTEGER, but the only writer is
    the bid engine passing `cm_bid_rules.id` — a uuid hex string. Every tick carrying a rule
    died on the INSERT, AFTER the bid had already been written to Blinkit. These row tests
    never caught it because they only inspect a dict, so pin the column type itself."""
    from app.models.campaign_manager_v2 import CmBidRule, CmRunLog
    # Compare the compiled DDL, not the Python class: SQLModel maps `str` to its own
    # AutoString decorator, which is neither a String subclass nor has a `python_type`.
    def ddl(col):
        return col.type.compile().upper()
    assert "CHAR" in ddl(CmRunLog.__table__.c.rule_id), (
        f"rule_id is {ddl(CmRunLog.__table__.c.rule_id)} — it must hold a bid rule's uuid hex id")
    assert "CHAR" in ddl(CmBidRule.__table__.c.id), (
        "if a bid rule's id ever stops being a string, cm_run_log.rule_id must follow")


def test_every_row_is_timestamped_at_decision_time():
    """Not at insert time — the batch is persisted at the end of the run, and the model
    default gave thirteen rows the same timestamp with no usable ordering."""
    assert _row()["timestamp"] is not None


# ── raw errors must not reach a client-facing column ────────────────────────

def test_a_raw_api_error_is_summarised_to_one_line():
    """The real one: Zepto returned four lines of JSON, which went into `reason` verbatim."""
    raw = 'Zepto blocked the search: HTTP 299 {\n  "error_code": "LOGIN_REQUIRED",\n  "x": 1\n}'
    out = bid._plain(raw, "could not check the search position")
    assert "\n" not in out, "a History reason must be a single line"
    assert out.startswith("could not check the search position")
    assert "LOGIN_REQUIRED" in out, "the technical detail is kept, just tamed"


def test_a_very_long_error_is_truncated():
    out = bid._plain("x" * 500, "could not check the search position")
    # The detail is truncated INSIDE the parentheses, so the string ends with ")".
    assert len(out) < 200, f"reason is {len(out)} chars — too long for a table cell"
    assert "…" in out and out.endswith(")")


def test_an_empty_error_still_produces_a_sentence():
    """`_plain("")` must not yield a dangling '( )'."""
    out = bid._plain("", "the window closed, so the bid goes back to its floor")
    assert out == "the window closed, so the bid goes back to its floor"
    assert "(" not in out


# ── no jargon left in the orchestration's own reasons ───────────────────────

def test_no_reason_in_the_engine_uses_arrow_jargon():
    """`window opened → min` and `window closed → min` were written for an engineer reading
    a log, not for a client reading their campaign's history. Both now say what happened to
    the bid and why, in words."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "bid.py").read_text(encoding="utf-8")
    for jargon in ('"window opened → min"', '"window closed → min', "· already at min"):
        assert jargon not in src, f"{jargon} is engineer-speak in a client-facing column"


# ── a budget rule describes itself in English ───────────────────────────────
#
# `budget._reason` is not just a log line: it IS the reason column a client reads for every
# budget change. It used to render the stored shape — `sunday, friday, saturday
# (2026-09-11–None) / 19:30–02:00` — where `None` is a missing end date and `/` separates
# fields nobody outside the code knows about.

def _budget_reason(**over):
    from campaign_manager.budget import _reason
    rule = {"type": "recurring", "days": [], "time_slots": [], "start_time": "19:30",
            "end_time": "02:00", "start_date": None, "end_date": None, "date": None}
    rule.update(over)
    return _reason(rule)


def test_an_open_ended_rule_never_says_none():
    out = _budget_reason(days=["sunday", "friday", "saturday"], start_date="2026-09-11")
    assert out == "Fri, Sat, Sun 19:30–02:00, from 11 Sep", out
    assert "None" not in out and "/" not in out


def test_day_names_come_out_in_week_order():
    assert _budget_reason(days=["sunday", "monday"]).startswith("Mon, Sun ")
    assert _budget_reason(days=[]).startswith("every day ")
    assert _budget_reason(days=["monday", "tuesday", "wednesday", "thursday", "friday",
                               "saturday", "sunday"]).startswith("every day ")


def test_date_spans_read_as_dates():
    assert _budget_reason(end_date="2026-10-01").endswith(", until 1 Oct")
    assert _budget_reason(start_date="2026-09-11",
                          end_date="2026-10-01").endswith(", 11 Sep–1 Oct")
    assert _budget_reason(type="once", date="2026-09-11") == "one-time 11 Sep 19:30–02:00"


def test_an_unparseable_date_is_shown_rather_than_crashing():
    assert "not-a-date" in _budget_reason(start_date="not-a-date")


def test_str_e_is_never_passed_straight_into_a_reason():
    """The guard against the original bug: `str(e)` as a reason argument."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "bid.py").read_text(encoding="utf-8")
    assert "current_cpm, str(e), dry_run" not in src, (
        "a raw exception is being written into a client-facing reason — wrap it in _plain()")


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
    print(f"\n{len(tests) - failed}/{len(tests)} history-reason tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
