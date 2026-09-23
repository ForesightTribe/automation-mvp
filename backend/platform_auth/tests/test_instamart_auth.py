"""Instamart Brand Portal authenticator — against the bodies captured live on
2026-09-21 from the Brik Oven account. No network: httpx is mocked.
"""
import base64
import json
import time

import httpx
import pytest

from platform_auth.errors import LoginFailed
from platform_auth.marketplaces.instamart import brand_portal as bp
from platform_auth.marketplaces.instamart import endpoints as ep
from platform_auth.types import AuthSession, Credentials, SecretKind

# ── fixtures built from the real capture ─────────────────────────────────────

USER_HASH = "626ee1c9cab1086ffff544973b48d9dae1dabc99d1c607544f8260a8035c065648"
SESSION_INFO = "601Jhi8BNQv2xrHF8Dgglw#z1fSXfFdUCf5ESdWtRax0w"
REFRESH = "129.z1fSXfFdUCf5ESdWtRax0w"
ACCOUNT = "c1f4d0d1-a2b9-47ff-a7b7-fca4db0009e1"


def _jwt(exp: int, iat: int | None = None, jti: str = "129") -> str:
    """A token with the real claim shape; signature is not checked by the code."""
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
    claims = {"iss": "https://…/ozone-idp-im-kba.json", "sub": "11214", "exp": exp,
              "iat": iat or exp - 5 * 3600, "jti": jti, "email": "ecom@brikoven.com",
              "user_pool": "USER_POOL_BRAND", "session_id": "z1fSXfFdUCf5ESdWtRax0w",
              "siat": 1789970129}
    pl = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return f"{hdr.decode()}.{pl.decode()}.sig"


class FakeHTTP:
    """Records calls; answers from a route table keyed by path."""

    def __init__(self, routes: dict):
        self.routes, self.calls = routes, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None, **kw):
        path = url.replace(ep.IDP, "")
        self.calls.append((path, json))
        status, body = self.routes[path]
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))


def _patch(monkeypatch, routes):
    fake = FakeHTTP(routes)
    monkeypatch.setattr(bp.httpx, "AsyncClient", lambda timeout=None: fake)
    return fake


# ── start_login ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_login_sends_email_and_client_id_and_keeps_the_pair(monkeypatch):
    fake = _patch(monkeypatch, {
        ep.SEND_VERIFICATION_CODE: (200, {"user_id": USER_HASH, "session_info": SESSION_INFO}),
    })
    ch = await bp.start_login(Credentials(email="ecom@brikoven.com", extra={"account_id": ACCOUNT}))
    path, body = fake.calls[0]
    assert path == ep.SEND_VERIFICATION_CODE
    assert body == {"email": "ecom@brikoven.com", "client_id": ep.CLIENT_ID}
    assert ch.secret_kind == SecretKind.OTP
    assert ch.context == {"user_id": USER_HASH, "session_info": SESSION_INFO}
    assert ch.credentials.extra["account_id"] == ACCOUNT


@pytest.mark.asyncio
async def test_start_login_fails_fast_without_the_pair(monkeypatch):
    _patch(monkeypatch, {ep.SEND_VERIFICATION_CODE: (200, {"status": "ok"})})
    with pytest.raises(LoginFailed):
        await bp.start_login(Credentials(email="nobody@brikoven.com"))


# ── complete_login ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_login_builds_session_from_the_real_response(monkeypatch):
    exp = int(time.time()) + 5 * 3600
    fake = _patch(monkeypatch, {
        ep.SEND_VERIFICATION_CODE: (200, {"user_id": USER_HASH, "session_info": SESSION_INFO}),
        ep.SIGN_IN_WITH_OTP: (200, {"access_token": _jwt(exp), "refresh_token": REFRESH}),
    })
    ch = await bp.start_login(Credentials(email="ecom@brikoven.com", extra={"account_id": ACCOUNT}))
    s = await bp.complete_login(ch, "Your OTP is 196468 — expires in 10 mins")

    path, body = fake.calls[1]
    assert path == ep.SIGN_IN_WITH_OTP
    assert body == {"otp": "196468", "user_id": USER_HASH,
                    "session_info": SESSION_INFO, "client_id": ep.CLIENT_ID}

    assert s.platform == "instamart" and s.email == "ecom@brikoven.com"
    assert s.raw["refresh_token"] == REFRESH
    assert s.raw["user_id"] == "11214"                 # JWT sub — what refresh sends
    assert s.raw["session_id"] == "z1fSXfFdUCf5ESdWtRax0w"
    assert s.raw["account_id"] == ACCOUNT
    assert s.headers["authorization"].startswith("Bearer eyJ")
    assert s.headers["x-client-account-id"] == ACCOUNT
    assert s.headers["x-client-id"] == "IM_ADS_EXTERNAL_DASHBOARD"
    assert s.expires_at is not None and 4.9 < (s.expires_at - bp.now_ist()).total_seconds() / 3600 < 5.1


@pytest.mark.asyncio
async def test_complete_login_rejects_bad_otp_length(monkeypatch):
    _patch(monkeypatch, {})
    from platform_auth.types import LoginChallenge
    ch = LoginChallenge(platform="instamart", email="x", secret_kind=SecretKind.OTP,
                        context={"user_id": USER_HASH, "session_info": SESSION_INFO})
    with pytest.raises(LoginFailed):
        await bp.complete_login(ch, "1234")


@pytest.mark.asyncio
async def test_complete_login_wrong_otp(monkeypatch):
    _patch(monkeypatch, {ep.SIGN_IN_WITH_OTP: (401, {"message": "invalid otp"})})
    from platform_auth.types import LoginChallenge
    ch = LoginChallenge(platform="instamart", email="x", secret_kind=SecretKind.OTP,
                        context={"user_id": USER_HASH, "session_info": SESSION_INFO})
    with pytest.raises(LoginFailed):
        await bp.complete_login(ch, "000000")


# ── refresh ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_sends_sub_and_refresh_token_and_uses_expires_at(monkeypatch):
    old_exp = int(time.time()) + 60
    new_exp = int(time.time()) + 5 * 3600
    fake = _patch(monkeypatch, {
        ep.TOKEN_REFRESH: (200, {"access_token": _jwt(new_exp, jti="582"),
                                 "refresh_token": REFRESH, "expires_at": new_exp}),
    })
    s = bp._build("ecom@brikoven.com", _jwt(old_exp), REFRESH, ACCOUNT)
    r = await bp.refresh(s)
    path, body = fake.calls[0]
    assert path == ep.TOKEN_REFRESH
    assert body == {"user_id": "11214", "refresh_token": REFRESH, "client_id": ep.CLIENT_ID}
    assert r is not None
    assert r.raw["refresh_token"] == REFRESH            # does not rotate
    assert r.raw["account_id"] == ACCOUNT               # carried forward
    assert r.headers["authorization"] != s.headers["authorization"]
    assert (r.expires_at - bp.now_ist()).total_seconds() > 4.9 * 3600


@pytest.mark.asyncio
async def test_refresh_returns_none_when_refused(monkeypatch):
    _patch(monkeypatch, {ep.TOKEN_REFRESH: (401, {"message": "expired"})})
    s = bp._build("ecom@brikoven.com", _jwt(int(time.time()) + 60), REFRESH, ACCOUNT)
    assert await bp.refresh(s) is None


# ── probe (clock only) ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_probe_is_true_with_time_left_and_false_near_expiry(monkeypatch):
    fake = _patch(monkeypatch, {})          # any network call would KeyError
    live = bp._build("e", _jwt(int(time.time()) + 3 * 3600), REFRESH, ACCOUNT)
    dying = bp._build("e", _jwt(int(time.time()) + 5 * 60), REFRESH, ACCOUNT)
    dead = bp._build("e", _jwt(int(time.time()) - 60), REFRESH, ACCOUNT)
    assert await bp.probe(live) is True
    assert await bp.probe(dying) is False   # inside the 15-min margin
    assert await bp.probe(dead) is False
    assert fake.calls == []                 # probe never touched the network


@pytest.mark.asyncio
async def test_probe_false_without_token():
    s = AuthSession(platform="instamart", email="e", raw={})
    assert await bp.probe(s) is False


# ── registry ─────────────────────────────────────────────────────────────────

def test_registry_entry():
    from platform_auth.registry import get
    a = get("instamart")
    assert a.wired and a.refreshable and not a.needs_password
    assert a.secret_kind == SecretKind.OTP
    assert a.refresh is bp.refresh and a.probe is bp.probe
