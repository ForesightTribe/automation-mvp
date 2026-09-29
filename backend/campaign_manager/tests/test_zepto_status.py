"""ZC-A5..A8 — Zepto's status vocabulary, and the messages built on it.

  A5  `INSUFFICIENT_WALLET_BALANCE` (7 campaigns) and `ENDED` (2) were unmapped, so the
      write guards saw an unknown status. Wallet → `held` with its OWN reason (a budget
      change does not revive it); `ENDED` → `ended`.
  A6  the session-expired line named Blinkit on every marketplace.
  A7  the budget engine described a Zepto resume with Blinkit's restart summary.
  A8  the API now returns each campaign's canonical `state`, computed by a PURE module
      the web process may import (the adapters pull in Playwright).

    python -m campaign_manager.tests.test_zepto_status
"""
import asyncio
import subprocess
import sys
from pathlib import Path

from campaign_manager import budget, logs, writes
from campaign_manager.marketplaces import canonical_status
from campaign_manager.marketplaces.zepto import adapter as zad
from campaign_manager.marketplaces.zepto import status as zst

WALLET, SPENT = "INSUFFICIENT_WALLET_BALANCE", "DAILY_BUDGET_EXHAUSTED"


# ── A5: the vocabulary ──────────────────────────────────────────────────────

def test_every_status_seen_in_the_data_is_mapped():
    assert zst.canonical("ACTIVE") == "running"
    assert zst.canonical("PAUSED") == "paused"
    assert zst.canonical(SPENT) == "held"
    assert zst.canonical(WALLET) == "held"
    assert zst.canonical("ENDED") == "ended"


def test_the_adapter_still_answers_through_its_own_name():
    # Engines and older tests reach it as `adapter._canonical`.
    assert zad._canonical(WALLET) == "held" and zad._canonical("ENDED") == "ended"


def test_an_unmapped_status_still_passes_through():
    assert zst.canonical("SOME_NEW_STATE") == "SOME_NEW_STATE"
    assert zst.canonical(None) is None and zst.canonical("  ") is None


def test_the_two_holds_give_opposite_advice():
    wallet, spent = zst.hold_reason(WALLET), zst.hold_reason(SPENT)
    assert "wallet" in wallet and "will not revive" in wallet
    assert "Raise the budget" in spent
    assert zst.hold_reason("ACTIVE") is None


def test_a_wallet_held_start_is_refused_with_the_wallet_reason():
    why = writes.status_transition_denied("held", "running",
                                          hold_reason=zst.hold_reason(WALLET))
    assert "wallet" in why and "budget is exhausted" not in why


def test_a_held_campaign_can_still_be_stopped():
    assert writes.status_transition_denied("held", "paused",
                                           hold_reason=zst.hold_reason(WALLET)) is None


def test_blinkit_keeps_its_own_hold_wording():
    assert "ON_HOLD" in writes.status_transition_denied("held", "running")


def test_an_ended_campaign_cannot_be_restarted():
    assert writes.status_transition_denied(zst.canonical("ENDED"), "running") is not None


def test_the_hold_reason_helper():
    detail = {"status": WALLET}
    assert "wallet" in writes.hold_reason(zad, "held", detail)
    assert writes.hold_reason(zad, "running", detail) is None      # only for held
    assert writes.hold_reason(object(), "held", detail) is None    # adapter without one


def test_the_start_path_reports_the_wallet_reason():
    """End to end through the choke point, dry run: Start on a wallet-held campaign is
    refused with advice that works."""
    outcome: dict = {}
    ok = asyncio.run(writes.apply_status(
        zad, None, run_id="t", campaign_id=2427461, target="running", current="held",
        dry_run=True, outcome=outcome,
        hold_reason=writes.hold_reason(zad, "held", {"status": WALLET})))
    assert ok is False and "wallet" in outcome["reason"]


# ── A6: the session-expired line names the right marketplace ────────────────

def test_session_expired_names_the_marketplace_it_ran_on():
    seen = []
    orig = logs._emit
    logs._emit = lambda level, event, dry_run, msg, **kw: seen.append(msg)
    try:
        logs.session_expired("t", dry_run=True, platform="zepto")
    finally:
        logs._emit = orig
    assert "Zepto" in seen[0] and "auth login zepto" in seen[0]
    assert "Blinkit" not in seen[0]


def test_every_engine_passes_its_platform():
    root = Path(__file__).resolve().parents[1]
    for name in ("bid.py", "budget.py", "set_budget.py", "set_activation.py",
                 "sync_campaigns.py"):
        src = (root / name).read_text(encoding="utf-8")
        for line in src.splitlines():
            if "logs.session_expired(" in line:
                assert "platform=platform" in line, f"{name}: {line.strip()}"


# ── A7: the resume summary is the adapter's own ─────────────────────────────

def test_a_zepto_resume_is_described_by_zepto():
    """Zepto's resume overwrites nothing, so there is nothing to summarise — it used to log
    Blinkit's restart summary of a Zepto detail."""
    seen = {}
    orig = writes.apply_status

    async def capture(adapter, client, **kw):
        seen.update(kw)
        return True

    writes.apply_status = capture
    try:
        asyncio.run(budget._restart(zad, None, "t", 2427461, 700, {"status": "PAUSED"},
                                    True, None, "zepto"))
    finally:
        writes.apply_status = orig
    assert seen["overwrites"] is None


# ── A8: canonical state, safe for the API ───────────────────────────────────

def test_canonical_status_speaks_for_both_marketplaces():
    assert canonical_status("zepto", SPENT) == "held"       # live — the UI must offer Stop
    assert canonical_status("zepto", WALLET) == "held"
    assert canonical_status("blinkit", "ON_HOLD") == "held"
    assert canonical_status("blinkit", "SCHEDULED") == "running"
    assert canonical_status("instamart", "WHATEVER") == "WHATEVER"   # unknown MP: unchanged


def test_the_api_can_compute_state_without_loading_a_browser():
    """Checked in a fresh interpreter: the test process itself may already hold Playwright."""
    code = ("import sys; import app.services.ads_service; "
            "print(any(m.startswith('playwright') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parents[2], timeout=120)
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.strip().splitlines()[-1] == "False", "the API pulled in Playwright"


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
    print(f"\n{len(tests) - failed}/{len(tests)} zepto-status tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
