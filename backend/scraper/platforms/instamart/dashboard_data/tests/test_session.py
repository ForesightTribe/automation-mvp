"""Brand Portal session (seller/session.py) — the parts that need no real browser.

`signed_post` carries every sales and ads call, so its rules are pinned here:

  * a 403 (the portal's throttle) waits 60 / 120 / 240 s and tries again, with a
    FRESH request id, timestamp and signature each attempt — a replayed
    signature is exactly what the edge rejects
  * any other failure fails at once, as PortalError
  * a token close to expiry is renewed (no OTP) before the call

Plus the localStorage and token helpers the session is built on. The page is a
fake; the OTP login itself can only be exercised live.

Run:  python -m pytest scraper/platforms/instamart/dashboard_data/tests
"""
import asyncio
import base64
import json
import time

import pytest

from scraper.platforms.instamart.dashboard_data.seller import endpoints as ep
from scraper.platforms.instamart.dashboard_data.seller import session as ss


def _jwt(**claims) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'HS256'})}.{enc(claims)}.sig"


TOKEN = _jwt(sub="11214", email="ecom@brand.com", session_id="s-1", exp=time.time() + 4 * 3600)


class _Page:
    """Answers the two scripts signed_post runs: the token read, and the fetch."""

    def __init__(self, responses: list[dict], token: str = TOKEN):
        self.responses = list(responses)
        self.token = token
        self.sent: list[dict] = []

    async def evaluate(self, script: str, arg=None):
        if "localStorage.getItem" in script:
            return json.dumps(self.token)
        self.sent.append(arg)
        return self.responses.pop(0)


class _Sleeps:
    def __init__(self):
        self.waits: list[float] = []

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, s, *a, **k):
        self.waits.append(s)


class _Signer:
    def sign(self, ts, request_id, session_id):
        return f"sig:{request_id}:{session_id}"


def _portal(page: _Page) -> ss.PortalSession:
    p = ss.PortalSession(None, "tenant", "ecom@brand.com", "acc-1")
    p._page = page
    return p


@pytest.fixture
def fakes(monkeypatch):
    sleeps = _Sleeps()
    monkeypatch.setattr(ss, "asyncio", sleeps)
    monkeypatch.setattr(ss, "get_signer", lambda: _Signer())
    return sleeps


def _go(coro):
    return asyncio.run(coro)


# ── signed_post ──────────────────────────────────────────────────────────────

def test_403_waits_the_ladder_and_resigns_every_attempt(fakes):
    page = _Page([{"status": 403, "text": "Please reload"}, {"status": 403, "text": "Please reload"},
                  {"status": 200, "text": '{"ok": true}'}])
    assert _go(_portal(page).signed_post("/api/x", {"a": 1})) == {"ok": True}
    assert fakes.waits[-2:] == list(ep.SIGNED_RETRY_WAITS_S[:2])          # 60 s, then 120 s
    ids = [s["headers"]["x-client-request-id"] for s in page.sent]
    assert len(ids) == 3 and len(set(ids)) == 3                            # never replayed
    assert all(s["headers"]["x-signature"] == f"sig:{s['headers']['x-client-request-id']}:s-1"
               for s in page.sent)
    assert page.sent[0]["url"] == ep.DATA + "/api/x" and page.sent[0]["body"] == {"a": 1}


def test_403_on_every_attempt_fails_after_the_last_wait(fakes):
    page = _Page([{"status": 403, "text": "Please reload"}] * (len(ep.SIGNED_RETRY_WAITS_S) + 1))
    with pytest.raises(ss.PortalError, match="403"):
        _go(_portal(page).signed_post("/api/x", {}))
    assert len(page.sent) == len(ep.SIGNED_RETRY_WAITS_S) + 1


def test_other_errors_fail_at_once(fakes):
    page = _Page([{"status": 500, "text": "boom"}])
    with pytest.raises(ss.PortalError, match="500"):
        _go(_portal(page).signed_post("/api/x", {}))
    assert len(page.sent) == 1 and not [w for w in fakes.waits if w in ep.SIGNED_RETRY_WAITS_S]


def test_unparseable_json_is_a_portal_error(fakes):
    page = _Page([{"status": 200, "text": "<html>"}])
    with pytest.raises(ss.PortalError, match="unparseable"):
        _go(_portal(page).signed_post("/api/x", {}))


def test_a_token_near_expiry_is_renewed_before_the_call(fakes):
    page = _Page([{"status": 200, "text": "{}"}],
                 token=_jwt(sub="1", session_id="s-1", exp=time.time() + 60))
    portal = _portal(page)
    renewed = []

    async def renew():
        renewed.append(True)
    portal._renew_live_token = renew
    _go(portal.signed_post("/api/x", {}))
    assert renewed == [True]


# ── helpers ──────────────────────────────────────────────────────────────────

def test_local_storage_round_trip_keeps_the_apps_json_encoding():
    state = {"cookies": [], "origins": []}
    ss._ls_set(state, "__K__", "v1")
    assert state["origins"][0]["origin"] == ep.PORTAL
    assert state["origins"][0]["localStorage"] == [{"name": "__K__", "value": '"v1"'}]
    ss._ls_set(state, "__K__", "v2")
    assert ss._ls_get(state, "__K__") == "v2" and len(state["origins"][0]["localStorage"]) == 1
    assert ss._ls_get(None, "__K__") is None


def test_seconds_left_is_negative_for_a_bad_token():
    assert 3 * 3600 < ss._seconds_left(TOKEN) <= 4 * 3600
    assert ss._seconds_left("not-a-jwt") == -1.0


def test_brand_account_id_comes_from_the_picked_brand():
    portal = ss.PortalSession(None, "tenant", "e@x.com", "acc-1")
    picked = {"state": {"selectedBrands": {"acc-1": {"value": "brand-77"}}}}
    portal._state_dict = {"origins": [{"origin": ep.PORTAL, "localStorage": [
        {"name": "__IM_ADS_SELECTED_BRAND_KEYS__", "value": json.dumps(picked)}]}]}
    assert portal.brand_account_id() == "brand-77"
    portal.account_id = "other"
    assert portal.brand_account_id() is None


def test_user_block_comes_from_the_token():
    portal = ss.PortalSession(None, "tenant", "e@x.com", "acc-1")
    portal._token = TOKEN
    assert portal.user_block() == {"user_id": "11214", "email": "ecom@brand.com",
                                   "user_pool": ep.USER_POOL}


# ── Supply Portal token, cached in platform_sessions ─────────────────────────

def _supply(monkeypatch, stored_raw: dict | None):
    from platform_auth.types import AuthSession
    from scraper.platforms.instamart.dashboard_data.supply import session as sup
    saved: list = []

    async def load(_db, _tid, platform):
        assert platform == sup._TOKEN_SLUG
        return AuthSession(platform=platform, email="", raw=stored_raw) if stored_raw else None

    async def update(_db, _tid, session):
        saved.append(session)

    monkeypatch.setattr(sup.store, "load", load)
    monkeypatch.setattr(sup.store, "update", update)
    return sup, saved


def test_a_live_cached_supply_token_is_reused_without_a_browser(monkeypatch):
    sup, _ = _supply(monkeypatch, {"token": "abc", "brand_company_id": "b-9",
                                   "exp": time.time() + 3600})

    class _NoBrowser:
        def __init__(self, *a, **k):
            raise AssertionError("must not open the portal")
    monkeypatch.setattr(sup, "PortalSession", _NoBrowser)
    assert _go(sup.get_token(None, "t", "e@x.com", "acc")) == ("abc", "b-9")


def test_an_expired_cached_supply_token_is_not_used(monkeypatch):
    sup, _ = _supply(monkeypatch, {"token": "abc", "brand_company_id": "b-9",
                                   "exp": time.time() + 30})       # inside the headroom
    assert _go(sup._load_cached(None, "t")) is None


def test_a_minted_supply_token_is_stored_as_a_renewal_not_a_login(monkeypatch):
    sup, saved = _supply(monkeypatch, None)
    exp = int(time.time()) + 5 * 3600
    _go(sup._save_cache(None, "t", "e@x.com", _jwt(exp=exp), "b-9"))
    [s] = saved                                    # through store.update, never store.save
    assert s.platform == sup._TOKEN_SLUG
    assert s.raw["brand_company_id"] == "b-9" and s.raw["exp"] == exp
