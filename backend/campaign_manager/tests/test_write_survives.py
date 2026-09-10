"""A write whose outcome is unknown must be CHECKED, and must never kill the run.

The 2026-09-07 incident, Blinkit campaign 637511, keyword "soda". Two ticks failed the
same way and meant opposite things:

    12:16   body `{"message": ""}`   the bid did NOT change
    18:15   body was not JSON at all  the bid DID change — ₹421 was live on Blinkit

Both raised a bare `RuntimeError` out of the client, which escaped `writes.apply_bid`,
escaped the engine's per-rule loop, and escaped past its `finally` — so the run died
before `write_bid_runtime` and `write_run_log`. The 18:15 tick had just performed a drift
RECOVERY: it snapped the bid back to the last price known to hold and should have paused
trimming for 90 minutes. That pause was never persisted, so the next tick trimmed straight
back to the price that had just lost the slot.

Two rules, both enforced here:
  1. An unacknowledged write is resolved by READING THE BID BACK, not by assuming failure.
  2. No write failure, of any kind, is allowed to abort the run. Only `SessionExpired`,
     because every remaining keyword would fail identically.

    python -m campaign_manager.tests.test_write_survives
"""
import asyncio

from campaign_manager import bid, writes


# ── 1. an unacknowledged write is verified, not guessed ─────────────────────

class _Adapter:
    """Raises `WriteUnverified` like a marketplace that answered with nothing usable.
    `read_bids` reports whatever the marketplace 'really' holds afterwards."""

    def __init__(self, live_after: dict | None, *, read_raises: bool = False):
        self._live_after = live_after
        self._read_raises = read_raises
        self.sent = None
        self.reads = 0

    async def apply_bid(self, client, campaign_id, keyword, cpm, match_type="EXACT"):
        self.sent = cpm
        raise writes.WriteUnverified("Blinkit did not acknowledge the bid update "
                                     "(HTTP 502, body: <html>gateway timeout)")

    async def read_bids(self, client, campaign_id):
        self.reads += 1
        if self._read_raises:
            raise RuntimeError("the read failed too")
        return dict(self._live_after or {})


def _apply(adapter, new_cpm=150):
    return asyncio.run(writes.apply_bid(
        adapter, None, run_id="t", campaign_id=1, keyword="soda", new_cpm=new_cpm,
        current_cpm=100, min_bid=100, max_bid=10000, dry_run=False))


def test_a_write_that_landed_is_reported_as_applied():
    """The 18:15 case. The reply was lost, the bid moved — reporting failure would leave
    our memory disagreeing with the marketplace, and lose the drift pause with it."""
    a = _Adapter({"soda": 150})
    assert _apply(a) is True
    assert a.reads == 1, "an unacknowledged write must be checked against the marketplace"


def test_a_write_that_did_not_land_is_reported_as_failed():
    """The 12:16 case — same exception, opposite truth."""
    assert _apply(_Adapter({"soda": 100})) is False


def test_an_unreadable_keyword_is_not_treated_as_success():
    assert _apply(_Adapter({"other": 150})) is False


def test_a_failed_read_back_is_not_treated_as_success():
    """'We could not confirm it' must never be logged as an applied write."""
    assert _apply(_Adapter(None, read_raises=True)) is False


def test_a_marketplace_with_no_read_back_path_fails_closed():
    class _NoRead:
        async def apply_bid(self, client, campaign_id, keyword, cpm, match_type="EXACT"):
            raise writes.WriteUnverified("no answer")
    assert _apply(_NoRead()) is False


# ── 2. a failed write never aborts the run ──────────────────────────────────

class _Boom:
    def __init__(self, exc):
        self._exc = exc

    async def apply_bid(self, client, campaign_id, keyword, cpm, match_type="EXACT"):
        raise self._exc

    async def read_bids(self, client, campaign_id):
        return {}


def _safe(exc):
    return asyncio.run(bid._safe_apply_bid(
        _Boom(exc), None, run_id="t", campaign_id=1, keyword="soda", new_cpm=150,
        current_cpm=100, min_bid=100, max_bid=10000, dry_run=False))


def test_a_marketplace_error_is_returned_not_raised():
    """This is the whole fix: the run has to reach `write_bid_runtime` / `write_run_log`
    even when the write it is describing failed."""
    ok, err = _safe(RuntimeError("Blinkit bid update failed"))
    assert ok is False and isinstance(err, RuntimeError)


def test_a_network_failure_is_returned_not_raised():
    ok, err = _safe(TimeoutError("read timed out"))
    assert ok is False and isinstance(err, TimeoutError)


def test_a_dead_session_still_aborts():
    """The one exception that must propagate — every remaining keyword would fail the
    same way, and the engine reports it as an expired session rather than as fifty
    marketplace rejections."""
    try:
        _safe(writes.SessionExpired("session is gone"))
    except writes.SessionExpired:
        return
    raise AssertionError("SessionExpired must not be swallowed")


def test_the_engine_uses_the_safe_wrapper_everywhere_it_writes():
    """Guards the three write sites in `run()` — window-open floor, bounds correction and
    the optimizer decision. A direct `writes.apply_bid(` in the engine is the bug."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "bid.py").read_text(encoding="utf-8")
    body = src.split("async def _reset_run")[0]        # the reset path has its own catch
    assert "writes.apply_bid(" not in body, (
        "the optimizer must call _safe_apply_bid — a raw write can abort the run")
    assert body.count("_safe_apply_bid(") == 3, (
        "all three of the optimizer's write sites must go through the safe wrapper")


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
    print(f"\n{len(tests) - failed}/{len(tests)} write-survival tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
