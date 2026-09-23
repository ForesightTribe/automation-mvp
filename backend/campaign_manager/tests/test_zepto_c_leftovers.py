"""§C leftovers (2026-09-23): C11 budget-then-start, C12 wallet warning, C1 per-keyword
floor, C14/C9 on edit, C20 unrecognisable products, C22 login history.

Stubbed throughout — no Zepto, no Blinkit, no DB.

    python -m campaign_manager.tests.test_zepto_c_leftovers
"""
import asyncio
import inspect
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from campaign_manager import bid, repo, wallet, writes
from campaign_manager.marketplaces.zepto import adapter as zad
from campaign_manager.tests import test_budget_apply as tba

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")


# ── C11: Zepto sets the budget FIRST, then starts ───────────────────────────

def _zepto_like():
    """test_budget_apply's recording adapter, declared the way the Zepto adapter is."""
    tba.FakeAdapter.RESUME_RESUBMITS = False
    tba.FakeAdapter.BUDGET_WHILE_PAUSED = True


def _undo():
    del tba.FakeAdapter.RESUME_RESUBMITS
    del tba.FakeAdapter.BUDGET_WHILE_PAUSED


def test_the_zepto_adapter_declares_both_facts():
    assert zad.RESUME_RESUBMITS is False
    assert zad.BUDGET_WHILE_PAUSED is True


def test_a_window_start_on_a_paused_zepto_campaign_sets_the_budget_then_starts():
    """Zepto's activate restores the campaign's OWN budget, so assuming the start carries
    the window's budget (Blinkit's restart does) left it running at the old one."""
    _zepto_like()
    try:
        calls = tba._run(status="paused", toggle=True, now=tba.NOW_IN_WINDOW)
    finally:
        _undo()
    assert calls == [("budget", 1500.0), ("status", "running", 1500.0)], calls
    assert calls[0][0] == "budget", "the budget must land BEFORE the campaign goes live"


def test_no_budget_write_when_it_is_already_right():
    _zepto_like()
    try:
        calls = tba._run(status="paused", toggle=True, now=tba.NOW_IN_WINDOW,
                         current_budget=1500.0)
    finally:
        _undo()
    assert calls == [("status", "running", 1500.0)], calls


def test_blinkit_still_carries_the_budget_in_the_restart():
    """Unchanged: one call, the restart carrying the budget."""
    assert tba._run(status="paused", toggle=True, now=tba.NOW_IN_WINDOW) == [
        ("status", "running", 1500.0)]


def test_a_window_end_reverts_a_paused_zepto_campaigns_budget():
    """Blinkit cannot take a budget on a stopped campaign, so it skips; Zepto can, so the
    campaign rests at its default instead of the window's raised budget."""
    _zepto_like()
    try:
        calls = tba._run(status="paused", toggle=False, now=tba.NOW_AT_END,
                         current_budget=1500.0)
    finally:
        _undo()
    assert calls == [("budget", 500.0)], calls
    assert tba._run(status="paused", toggle=False, now=tba.NOW_AT_END,
                    current_budget=1500.0) == [], "Blinkit: still skipped"


# ── C11 in the one-off Start ────────────────────────────────────────────────

def _activate(budget):
    from campaign_manager import set_activation

    fake = tba.FakeAdapter("paused", 500.0)
    fake.RESUME_RESUBMITS = False
    fake.BUDGET_WHILE_PAUSED = True
    orig = (set_activation.get_adapter, repo.get_tenant_name, repo.get_advertiser,
            repo.write_run_log, repo.record_applied, repo.recent_write_count)
    set_activation.get_adapter = lambda platform: fake
    repo.get_tenant_name = tba._async_const("T")
    repo.get_advertiser = tba._async_const("brand")
    repo.write_run_log = tba._async_noop
    repo.record_applied = tba._async_noop
    repo.recent_write_count = tba._async_const(0)
    try:
        asyncio.run(set_activation.run(TENANT, 1, "running", budget=budget, dry_run=False,
                                       platform="zepto"))
    finally:
        (set_activation.get_adapter, repo.get_tenant_name, repo.get_advertiser,
         repo.write_run_log, repo.record_applied, repo.recent_write_count) = orig
    return fake.calls


def test_start_at_a_price_on_zepto_no_longer_drops_the_price():
    assert _activate(900.0) == [("budget", 900.0), ("status", "running", None)]


def test_a_plain_start_on_zepto_keeps_the_campaigns_own_budget():
    assert _activate(None) == [("status", "running", None)]


# ── C1: the keyword's own published minimum replaces the flat ₹10 ───────────

class _BidAdapter:
    MIN_BID = 10

    def __init__(self):
        self.sent = None

    async def apply_bid(self, client, campaign_id, keyword, cpm, match_type="EXACT"):
        self.sent = cpm
        return {"success": True}


def _bid(cpm, floor):
    a = _BidAdapter()
    ok = asyncio.run(writes.apply_bid(
        a, None, run_id="t", campaign_id=1, keyword="bread", new_cpm=cpm, current_cpm=50,
        min_bid=1, max_bid=100, dry_run=False, keyword_floor=floor))
    return ok, a.sent


def test_a_keyword_zepto_allows_at_three_can_be_bid_at_three():
    assert _bid(3, floor=3) == (True, 3)


def test_the_flat_ten_still_applies_when_no_floor_is_known():
    assert _bid(3, floor=None) == (False, None)


def test_a_published_floor_above_ten_is_enforced_too():
    assert _bid(12, floor=15) == (False, None)


def test_every_engine_bid_write_passes_the_keyword_floor():
    """Four call sites write bids; one missing the floor would fall back to the flat ₹10."""
    src = inspect.getsource(bid)
    assert src.count("keyword_floor=kw_floor") == 4


# ── C14 + C9 on EDIT ────────────────────────────────────────────────────────

class _Db:
    def __init__(self, row):
        self.row = row
        self.committed = False

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, model, rule_id):
        return self.row if model.__name__ == "CmBidRule" else None

    async def commit(self):
        self.committed = True

    async def refresh(self, row):
        return None


def _rule(**kw):
    base = dict(id="me", tenant_id=TENANT, platform="zepto", campaign_id=1, keyword="bread",
                match_type="EXACT", active=True, city_id=499, lat=12.9, lon=77.6)
    base.update(kw)
    return SimpleNamespace(**base)


def _edit(row, fields, *, dupe=None):
    async def _live(*a, **k):
        return dupe

    db = _Db(row)
    orig = (repo.AsyncSessionLocal, repo.live_bid_rule)
    repo.AsyncSessionLocal, repo.live_bid_rule = db, _live
    try:
        return asyncio.run(repo.update_bid_rule("me", fields)), db
    finally:
        repo.AsyncSessionLocal, repo.live_bid_rule = orig


def test_an_edit_cannot_strip_a_zepto_rules_location():
    try:
        _edit(_rule(), {"city_id": None, "lat": None, "lon": None})
    except repo.NotAutomatable as e:
        assert "Nothing was changed" in str(e)
    else:
        raise AssertionError("must refuse")


def test_moving_a_zepto_rule_to_another_city_is_fine():
    row = _rule()
    _, db = _edit(row, {"city_id": 500, "lat": 12.3, "lon": 76.6})
    assert db.committed and row.city_id == 500


def test_blinkit_rules_may_still_drop_their_location():
    _, db = _edit(_rule(platform="blinkit"), {"city_id": None, "lat": None, "lon": None})
    assert db.committed


def test_renaming_onto_a_live_keyword_is_refused():
    try:
        _edit(_rule(), {"keyword": "pink toffee"}, dupe=SimpleNamespace(id="other"))
    except repo.DuplicateBidRule as e:
        assert "rule other" in str(e)
    else:
        raise AssertionError("must refuse")


def test_a_non_keyword_edit_never_runs_the_duplicate_check():
    row = _rule()
    _, db = _edit(row, {"target_position": 2}, dupe=SimpleNamespace(id="other"))
    assert db.committed


# ── C12: the wallet ─────────────────────────────────────────────────────────

def test_wallet_levels():
    assert wallet.assess(20276, warn_below=5000) is None
    level, said = wallet.assess(3000, warn_below=5000)
    assert level == "warning" and "₹3,000" in said
    level, said = wallet.assess(0, warn_below=5000)
    assert level == "error" and "EMPTY" in said
    assert wallet.assess(None, warn_below=5000) is None
    assert wallet.assess("20276", warn_below=5000) is None, "unknown shape = no opinion"


def _check(adapter, *, last_note=None):
    notes = []

    async def _last(*a, **k):
        return last_note

    async def _write(rows):
        notes.extend(rows)

    orig = (repo.last_run_log_at, repo.write_run_log)
    repo.last_run_log_at, repo.write_run_log = _last, _write
    try:
        bal = asyncio.run(wallet.check(adapter, None, tenant_id=TENANT, platform="zepto",
                                       run_id="r", dry_run=False))
    finally:
        repo.last_run_log_at, repo.write_run_log = orig
    return bal, notes


def _wallet(balance=None, boom=False):
    async def read_wallet(client):
        if boom:
            raise RuntimeError("400 invalid filters")
        return {"current_balance": balance}
    return SimpleNamespace(read_wallet=read_wallet)


def test_a_marketplace_without_a_wallet_is_never_checked():
    assert _check(SimpleNamespace()) == (None, [])


def test_a_failed_wallet_read_never_costs_the_run():
    assert _check(_wallet(boom=True)) == (None, [])


def test_a_healthy_wallet_writes_nothing_to_history():
    assert _check(_wallet(20276)) == (20276, [])


def test_a_low_wallet_gets_one_history_line():
    bal, notes = _check(_wallet(1200))
    assert bal == 1200 and len(notes) == 1
    assert notes[0]["kind"] == "wallet" and notes[0]["campaign_id"] is None
    assert "Recharge it on Zepto" in notes[0]["reason"]


def test_the_history_line_is_not_repeated_every_run():
    from app.utils.time import now_ist
    _, notes = _check(_wallet(1200), last_note=now_ist() - timedelta(hours=1))
    assert notes == []


def test_both_engines_check_the_wallet():
    from campaign_manager import budget
    assert "wallet.check(" in inspect.getsource(budget.run)
    assert "wallet.check(" in inspect.getsource(bid.run)


def test_the_zepto_wallet_call_sends_the_dashboards_filters():
    """Without them Zepto answers 400 "invalid filters" — found on the first real call."""
    from campaign_manager.marketplaces.zepto import client as zc
    src = inspect.getsource(zc.get_wallet)
    for p in ("start_date", "end_date", "all_brands", "brand_ids"):
        assert f'"{p}"' in src, p


# ── C20: a campaign whose products cannot be read ───────────────────────────

def test_no_products_on_a_product_matching_marketplace_skips_the_tick():
    said, skip = bid.products_problem([], True, SimpleNamespace(), "Blinkit")
    assert skip and "no bid change" in said and "lists no products" in said


def test_a_failed_read_is_worded_as_a_failed_read():
    said, _ = bid.products_problem([], False, SimpleNamespace(), "Blinkit")
    assert "could not be read from Blinkit" in said


def test_zepto_carries_on_by_campaign_id():
    assert zad.RECOGNISES_AD_BY_CAMPAIGN is True
    said, skip = bid.products_problem([], True, zad, "Zepto")
    assert not skip and "campaign id" in said


def test_products_present_is_no_problem():
    assert bid.products_problem([{"pid": "1"}], True, SimpleNamespace(), "Blinkit") is None


def test_the_check_runs_before_any_search():
    src = inspect.getsource(bid.run)
    assert src.index("products_problem(") < src.index("await _read_stores("), (
        "must be decided before the search, or the search's 'absent' raises the bid first")


# ── C22: login history ──────────────────────────────────────────────────────

def test_login_history_is_carried_and_trimmed_to_a_week():
    from platform_auth import store
    now = datetime(2026, 9, 23, 12, 0)
    old = [(now - timedelta(days=8)).isoformat(), (now - timedelta(days=2)).isoformat(),
           "garbage"]
    out = store.carry_logins(old, now)
    assert out == [(now - timedelta(days=2)).isoformat(), now.isoformat()]


def test_logins_in_the_last_day_are_counted():
    from platform_auth import store
    now = datetime(2026, 9, 23, 12, 0)
    hist = [(now - timedelta(hours=h)).isoformat() for h in (1, 5, 23, 30)] + ["x"]
    assert store.logins_since(hist, now - timedelta(days=1)) == 3


def test_an_unreadable_envelope_starts_a_fresh_history():
    from platform_auth import store
    assert store._login_history(None) == []
    assert store._login_history("not-encrypted") == []


def test_the_history_key_does_not_break_loading_a_session():
    from platform_auth import store
    from platform_auth.types import AuthSession
    s = AuthSession(platform="zepto", email="a@b.c", raw={"jwt": "x"}, storage_state={})
    env = s.to_envelope()
    env[store.LOGIN_HISTORY_KEY] = ["2026-09-23T12:00:00"]
    back = AuthSession.from_envelope(env)
    assert back.raw == {"jwt": "x"} and back.platform == "zepto"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} §C leftover tests passed.")
