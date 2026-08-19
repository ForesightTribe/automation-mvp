"""Unit tests for the campaign status transition table (docs/campaign-manager.md §8.3).

Pure logic — no Blinkit, no DB. Same shape as test_guardrails.py (no pytest in the repo
yet), runnable with:

    python -m campaign_manager.tests.test_transitions

The table these cover is the whole safety story for start/stop: `ended` and `held` are
states we must never write through, and an unrecognised status must refuse rather than
guess. The asymmetry between the two directions is deliberate — resuming re-submits the
entire campaign, pausing is a bodiless DELETE.
"""
from campaign_manager import writes

denied = writes.status_transition_denied


def test_normal_transitions_allowed():
    assert denied("paused", "running") is None      # resume — the RESTART path
    assert denied("running", "paused") is None      # stop — the DELETE path


def test_completed_is_refused_both_ways():
    """COMPLETED is genuinely terminal: Blinkit is done with the campaign."""
    assert denied("ended", "running") is not None
    assert denied("ended", "paused") is not None


def test_on_hold_can_be_stopped_but_never_restarted():
    """ON_HOLD means the budget ran out and Blinkit paused delivery — the campaign is
    LIVE, so "off outside the window" still applies to it. What it can't be is restarted:
    it was never stopped, which is why Blinkit reports `['UPDATE']` and never `['RESTART']`
    for it. Raising its budget is the thing that revives it, and that is a budget write,
    not a status one."""
    assert denied("held", "paused") is None
    assert denied("held", "running") is not None


def test_draft_only_startable_on_demand():
    """AD8 — a human clicking Start on a draft means it; a cron reaching one does not."""
    assert denied("draft", "running", allow_draft=True) is None
    assert denied("draft", "running") is not None            # scheduled rule → refused
    assert denied("draft", "paused", allow_draft=True) is not None   # nothing to pause


def test_unknown_current_status_refused():
    """A Blinkit status we've never mapped is exactly when a blind write is most
    likely to be wrong — refuse and re-read rather than guess."""
    assert denied("SOMETHING_NEW", "running") is not None
    assert denied(None, "running") is not None
    assert denied(None, "paused") is not None


def test_only_running_and_paused_are_writable():
    """We never *write* held/ended/draft, whatever the current state is."""
    for target in ("held", "ended", "draft", "", "ACTIVE"):
        assert denied("running", target) is not None, target
    assert set(writes.WRITABLE_STATES) == {"running", "paused"}


def test_noop_is_not_a_denial():
    """current == target is a skip decided by the caller (so it logs as a no-op), not a
    guardrail trip — the table itself must stay silent about it."""
    assert denied("running", "running") is None
    assert denied("paused", "paused") is None


# ── Blinkit vocabulary mapping (the adapter's only pure logic) ──────────────

def test_blinkit_status_mapping():
    """Blinkit's words stop at the adapter; everything above speaks canonical."""
    from campaign_manager.marketplaces.blinkit.adapter import _canonical
    assert _canonical("ACTIVE") == "running"
    assert _canonical("STOPPED") == "paused"
    assert _canonical("ON_HOLD") == "held"
    assert _canonical("COMPLETED") == "ended"
    assert _canonical("DRAFT") == "draft"
    assert _canonical(" active ") == "running"      # tolerate whitespace/case
    assert _canonical(None) is None
    assert _canonical("") is None


def test_unmapped_blinkit_status_passes_through_to_be_refused():
    """A status Blinkit adds later must reach the guardrail by name and be refused —
    never coerced into something writable."""
    from campaign_manager.marketplaces.blinkit.adapter import _canonical
    assert _canonical("PENDING_REVIEW") == "PENDING_REVIEW"
    assert denied(_canonical("PENDING_REVIEW"), "running") is not None


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
    print(f"\n{len(tests) - failed}/{len(tests)} transition tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
