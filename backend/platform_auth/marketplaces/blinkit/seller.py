"""Blinkit seller dashboard (partnersbiz.com) — browserless OTP login.

Not Firebase; a plain REST auth service. Four calls, no Chromium anywhere:

    1. POST /auth/api/v1/email/send_otp        (email carries a 6-digit code)
    2. POST /auth/api/v1/email/verify_otp      -> access_token + refresh_token
    3. GET  /v1/get-user-entities/             -> the "account selection" screen
    4. POST /auth/api/v1/tokens/rotate         -> sliding window, no new OTP ever

Step 3 is the one that isn't obvious. The old Playwright login clicked a company
card on an account-selection screen; that selection is *pure client state*
(localStorage "myEntity"), injected into every data call as X-Entity-Id /
X-Entity-Type by the app's axios interceptor. Verified 2026-08-04: /v1/* returns
403 "ERROR_CODE:11 Unauthorised" without those headers and 200 with them, so the
token alone is not a complete credential — the entity is part of it.
"""
import json
from datetime import timedelta

import httpx

from app.utils.logger import logger
from app.utils.time import now_ist
from platform_auth.errors import LoginFailed
from platform_auth.marketplaces.blinkit import endpoints as ep
from platform_auth.types import AuthSession, Credentials, LoginChallenge, SecretKind

_TIMEOUT = 30
# The rotate window observed on the token pair. Rotation resets it, so a session
# that is exercised at least this often never needs another OTP.
_SESSION_DAYS = 7
# Which mail to look for lives in platform_auth/mail_rules.py, not here.


def _auth_headers(access_token: str = "") -> dict:
    """Headers for the /auth/api/* service (note: 'partnersbiz-web')."""
    return {
        "accept": "application/json, text/plain, */*",
        "app_client": ep.SELLER_APP_CLIENT_AUTH,
        "service": ep.SELLER_SERVICE,
        "x-api-key": ep.SELLER_API_KEY,
        "access_token": access_token,
        "content-type": "application/x-www-form-urlencoded",
        "origin": ep.SELLER_BASE,
        "referer": f"{ep.SELLER_BASE}/",
        "user-agent": ep.USER_AGENT,
    }


def data_headers(access_token: str, entity: dict | None = None) -> dict:
    """Headers for the /v1/* data service (note: 'partnerbiz-web', Blinkit's typo).

    This is exactly the header set the seller scraper currently launches Chromium
    to harvest — so it can be handed one directly instead.
    """
    h = {
        "accept": "application/json, text/plain, */*",
        "access_token": access_token,
        "Access_token": access_token,
        "Token": access_token,
        "App_client": ep.SELLER_APP_CLIENT_DATA,
        "service": ep.SELLER_SERVICE,
        "x-api-key": ep.SELLER_API_KEY,
        "origin": ep.SELLER_BASE,
        "referer": f"{ep.SELLER_BASE}/",
        "user-agent": ep.USER_AGENT,
    }
    if entity:
        h[ep.SELLER_ENTITY_ID_HEADER] = str(entity["id"])
        h[ep.SELLER_ENTITY_TYPE_HEADER] = entity["type"]
    return h


async def start_login(credentials: Credentials) -> LoginChallenge:
    """Request the OTP. Passwordless — `credentials.password` is ignored if set."""
    email = credentials.email
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        r = await http.post(
            f"{ep.SELLER_BASE}{ep.SELLER_SEND_OTP}",
            headers=_auth_headers(),
            data={"email_id": email},
        )
        if r.status_code != 200 or not r.json().get("success"):
            raise LoginFailed(f"send_otp returned {r.status_code}: {r.text[:200]}")
    logger.info(f"Seller OTP requested for {email}")
    return LoginChallenge(
        platform="blinkit_seller",
        email=email,
        secret_kind=SecretKind.OTP,
        credentials=credentials,
    )


async def complete_login(challenge: LoginChallenge, secret: str) -> AuthSession:
    otp = "".join(ch for ch in secret if ch.isdigit())[:6]
    if len(otp) != 6:
        raise LoginFailed(f"Expected a 6-digit OTP, got {secret[:40]!r}")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        r = await http.post(
            f"{ep.SELLER_BASE}{ep.SELLER_VERIFY_OTP}",
            headers=_auth_headers(),
            data={"email_id": challenge.email, "verify_code": otp},
        )
        if r.status_code != 200 or not r.json().get("success"):
            raise LoginFailed(f"verify_otp returned {r.status_code}: {r.text[:200]}")
        tok = r.json()
        entity = await _resolve_entity(http, tok["access_token"])

    return _build(challenge.email, tok["access_token"], tok["refresh_token"], entity)


async def _resolve_entity(http: httpx.AsyncClient, access_token: str) -> dict:
    """Pick the account — the old login's 'account selection screen'.

    Prefers an enabled BLINKIT entity; several can be linked to one address.
    """
    r = await http.get(
        f"{ep.SELLER_BASE}{ep.SELLER_USER_ENTITIES}",
        headers=data_headers(access_token),
    )
    if r.status_code != 200:
        raise LoginFailed(f"get-user-entities returned {r.status_code}: {r.text[:200]}")
    entities = r.json()["data"]["data"]["entities"]
    if not entities:
        raise LoginFailed("Login succeeded but the account has no linked entities.")
    preferred = [e for e in entities if e.get("tenant") == "BLINKIT" and not e.get("disabled")]
    chosen = (preferred or entities)[0]
    if len(entities) > 1:
        logger.warning(
            f"{len(entities)} entities linked; using {chosen['id']} ({chosen.get('name')}). "
            "If that is the wrong account, entity selection needs to become explicit."
        )
    logger.info(f"Seller entity: {chosen.get('name')} (id={chosen['id']}, {chosen['type']})")
    return chosen


def _build(email: str, access_token: str, refresh_token: str, entity: dict) -> AuthSession:
    expires = now_ist() + timedelta(days=_SESSION_DAYS)
    return AuthSession(
        platform="blinkit_seller",
        email=email,
        raw={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "entity": entity,
        },
        # Browser projection, for anything still driving the SPA: the app reads
        # the token from a cookie and the entity from localStorage.
        storage_state={
            "cookies": [
                {
                    "name": name,
                    "value": value,
                    "domain": "partnersbiz.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "Lax",
                }
                for name, value in (
                    ("access_token", access_token),
                    ("refresh_token", refresh_token),
                )
            ],
            "origins": [
                {
                    "origin": ep.SELLER_BASE,
                    "localStorage": [
                        {"name": "myEntity", "value": json.dumps(entity)},
                        {"name": "access_token_expiry", "value": expires.isoformat()},
                    ],
                }
            ],
        },
        headers=data_headers(access_token, entity),
        expires_at=expires,
    )


async def refresh(session: AuthSession) -> AuthSession | None:
    """Slide the window with a token rotation — never needs a new OTP."""
    access_token = session.raw.get("access_token")
    refresh_token = session.raw.get("refresh_token")
    entity = session.raw.get("entity")
    if not (access_token and refresh_token):
        return None

    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        r = await http.post(
            f"{ep.SELLER_BASE}{ep.SELLER_ROTATE}",
            headers={**_auth_headers(access_token), "app_client": ep.SELLER_APP_CLIENT_DATA},
            data={"refresh_token": refresh_token},
        )
        if r.status_code != 200:
            logger.warning(f"Seller rotate failed ({r.status_code}): {r.text[:200]}")
            return None
        d = r.json()
        new_access = d.get("access_token")
        if not new_access:
            return None
        # Entities are cheap and can change (a company gets added/disabled), so
        # re-resolve rather than trusting a cached one indefinitely.
        try:
            entity = await _resolve_entity(http, new_access)
        except LoginFailed:
            pass

    return _build(session.email, new_access, d.get("refresh_token", refresh_token), entity)


async def probe(session: AuthSession) -> bool:
    """Cheapest authenticated read that proves the token still works."""
    access_token = session.raw.get("access_token")
    if not access_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            r = await http.get(
                f"{ep.SELLER_BASE}{ep.SELLER_USER_ENTITIES}",
                headers=data_headers(access_token),
            )
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"Seller probe error: {e}")
        return False
