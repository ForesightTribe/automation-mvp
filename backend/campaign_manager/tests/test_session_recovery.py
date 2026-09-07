"""A session dying mid-run must not cost the rest of the run.

The gap this closes: `setup()` ran once, at the start, and `ensure()` (load → probe →
refresh → re-login) ran only there. A session that expired thirty seconds later was never
noticed — because `_fetch` turned the login redirect into `{}`, which every caller reads as
"the marketplace refused this change". So a dead session logged

    not applied — Blinkit rejected the change to ₹250

for every remaining keyword: a false statement about Blinkit, and one that hid the real
fault. A bid run can last minutes and writes real money, so losing the back half of one to a
silent auth failure is not acceptable.

Pure — no browser, no Blinkit, no DB. The page is a stub that scripts HTTP responses.

    python -m campaign_manager.tests.test_session_recovery
"""
import asyncio

from campaign_manager.marketplaces.blinkit.client import BlinkitClient, _looks_logged_out
from campaign_manager.writes import SessionExpired

LOGIN_HTML = "<html><body>Please sign in to continue</body></html>"


class _Page:
    """Stands in for the Playwright page. Returns the queued responses in order and counts
    the calls, so a test can assert the call was actually REPLAYED and not just retried."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def evaluate(self, _script, _args):
        self.calls += 1
        return self.responses.pop(0) if self.responses else {
            "__status": 200, "__body": {"status": True}, "__html": None}


def _client(responses, tenant_id="t-1"):
    c = BlinkitClient.__new__(BlinkitClient)          # skip __init__: no real page to bind
    c._page = _Page(responses)
    c._token = "tok"
    c._email = "ops@example.com"
    c._tenant_id = tenant_id
    return c


def _run(coro):
    return asyncio.run(coro)


# ── telling a dead session from a rejection ─────────────────────────────────

def test_a_login_page_is_recognised_as_logged_out():
    assert _looks_logged_out(LOGIN_HTML) is True
    assert _looks_logged_out("<html>502 Bad Gateway</html>") is False
    assert _looks_logged_out(None) is False


def test_a_real_rejection_is_not_mistaken_for_a_dead_session():
    """The important negative. Blinkit rejecting a bid is a 200 with `success: false` — it
    must NOT trigger a re-login, or every legitimate refusal would rebuild the session."""
    c = _client([{"__status": 200,
                  "__body": {"success": False, "message": ["Please select atleast one PID"]},
                  "__html": None}])
    out = _run(c._fetch("PUT", "/adservice/v3/campaigns", {"x": 1}))
    assert out["success"] is False
    assert c._page.calls == 1, "a rejection must not be retried"


def test_a_non_json_body_still_returns_an_empty_dict():
    """Unchanged for every caller: a body we cannot parse, that is NOT a login page, is
    still `{}` — the behaviour the whole client was built on."""
    c = _client([{"__status": 500, "__body": None, "__html": "<html>oops</html>"}])
    assert _run(c._fetch("GET", "/adservice/v1/campaigns/1")) == {}


# ── recovery ────────────────────────────────────────────────────────────────

def test_a_401_reauthenticates_and_replays_the_call():
    c = _client([
        {"__status": 401, "__body": None, "__html": LOGIN_HTML},   # session died
        {"__status": 200, "__body": {"status": True}, "__html": None},  # after re-login
    ])
    reauths = []

    async def fake_reauth():
        reauths.append(True)
    c.reauth = fake_reauth

    out = _run(c._fetch("PUT", "/adservice/v3/campaigns", {"x": 1}))
    assert out == {"status": True}
    assert reauths == [True], "it should re-authenticate exactly once"
    assert c._page.calls == 2, "the original call must be replayed after re-authenticating"


def test_a_login_redirect_without_a_401_also_recovers():
    """Blinkit answers a dead session with an HTML login page, not always a clean 401."""
    c = _client([
        {"__status": 200, "__body": None, "__html": LOGIN_HTML},
        {"__status": 200, "__body": {"status": True}, "__html": None},
    ])
    async def fake_reauth():
        pass
    c.reauth = fake_reauth
    assert _run(c._fetch("GET", "/adservice/v1/campaigns/1")) == {"status": True}


# ── giving up ───────────────────────────────────────────────────────────────

def test_it_gives_up_after_one_attempt_rather_than_looping():
    """Still dead after re-authenticating → raise. Retrying forever inside a bid run would
    hammer the login endpoint from one datacentre IP, which is what the auth circuit
    breaker exists to prevent."""
    c = _client([
        {"__status": 401, "__body": None, "__html": LOGIN_HTML},
        {"__status": 401, "__body": None, "__html": LOGIN_HTML},
    ])
    async def fake_reauth():
        pass
    c.reauth = fake_reauth

    try:
        _run(c._fetch("PUT", "/adservice/v3/campaigns", {"x": 1}))
    except SessionExpired as e:
        assert "401" in str(e)
        assert c._page.calls == 2, "exactly one replay, then give up"
        return
    raise AssertionError("a permanently dead session must raise, not return {}")


def test_a_client_with_no_tenant_cannot_self_heal_and_says_so():
    """`setup_with_state` can be handed a bare storage state with no tenant to look up.
    Such a client must fail honestly rather than pretend it re-authenticated."""
    c = _client([{"__status": 401, "__body": None, "__html": LOGIN_HTML}], tenant_id=None)
    try:
        _run(c._fetch("GET", "/adservice/v1/campaigns/1"))
    except SessionExpired as e:
        assert "cannot re-authenticate itself" in str(e)
        return
    raise AssertionError("expected SessionExpired")


def test_session_expired_is_a_runtimeerror():
    """The engines already catch RuntimeError around `adapter.setup()` and report it as an
    expired session, so startup behaviour is unchanged by this class existing."""
    assert issubclass(SessionExpired, RuntimeError)


# ── a blocked run must still explain itself in History ──────────────────────

def test_a_blocked_run_writes_one_row_per_automation():
    """The silent gap: a run that dies at `setup()` used to write NOTHING, so History showed
    the bid simply not moving for hours with no row saying why — which is precisely the
    question that screen exists to answer."""
    from campaign_manager import bid, repo

    class Rule:
        # A bid rule's id is a uuid hex string, not an int — see test_history_reasons.
        id = "d657c360345f421d866bcde09a702e42"
        campaign_id, campaign_name, keyword, target_position = 111, "C", "soda", 3

    written = []
    original = repo.write_run_log

    async def capture(rows):
        written.extend(rows)
    repo.write_run_log = capture
    try:
        asyncio.run(bid._record_run_blocked(
            "t", "blinkit", "run-1", [Rule()],
            "could not sign in to Blinkit, so no bids were changed", dry_run=False))
    finally:
        repo.write_run_log = original

    assert len(written) == 1
    row = written[0]
    assert row["campaign_id"] == 111 and row["keyword"] == "soda"
    assert row["rule_id"] == "d657c360345f421d866bcde09a702e42"
    assert row["action"] == "error" and row["success"] is False
    assert "could not sign in" in row["reason"]


def test_recording_the_block_never_masks_the_real_fault():
    """If writing the explanation fails, the run must still report the ORIGINAL problem —
    a bookkeeping error swallowing an auth error would be its own silent gap."""
    from campaign_manager import bid, repo

    class Rule:
        # A bid rule's id is a uuid hex string, not an int — see test_history_reasons.
        id = "d657c360345f421d866bcde09a702e42"
        campaign_id, campaign_name, keyword, target_position = 111, "C", "soda", 3

    async def boom(rows):
        raise RuntimeError("db down")
    original = repo.write_run_log
    repo.write_run_log = boom
    try:
        asyncio.run(bid._record_run_blocked("t", "blinkit", "r", [Rule()], "why", False))
    finally:
        repo.write_run_log = original          # must not raise


def test_no_rules_means_no_rows():
    from campaign_manager import bid
    asyncio.run(bid._record_run_blocked("t", "blinkit", "r", [], "why", False))


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} session-recovery tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
