"""Blinkit marketing dashboard (brands.blinkit.com) — browserless magic-link login.

The whole flow is three HTTP calls; no Chromium is launched to log in:

    1. POST /adservice/v1/users/request-magic-link   (Blinkit sends the mail)
    2. Firebase accounts:signInWithEmailLink         (oobCode -> id/refresh token)
    3. synthesize a storage_state from those tokens

Step 3 is what lets the existing browser-based scrapers keep working untouched:
they still receive the three-layer state they expect (cookies + localStorage +
Firebase IndexedDB), we just mint it from REST instead of scraping it out of a
real browser session. Cookies are deliberately empty — Chromium earns its own
Cloudflare cookies on first navigation (verified 2026-08-04: a synthesized
session with no cookies scraped 52 campaigns).
"""
import json
import re
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.utils.logger import logger
from app.utils.time import now_ist
from platform_auth.errors import LoginFailed
from platform_auth.marketplaces.blinkit import endpoints as ep
from platform_auth.types import AuthSession, Credentials, LoginChallenge, SecretKind

_TIMEOUT = 30
# Which mail to look for lives in platform_auth/mail_rules.py, not here.


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "User-Agent": ep.USER_AGENT,
        "Origin": ep.MARKETING_BASE,
        "Referer": f"{ep.MARKETING_BASE}/",
    }


async def _fetch_api_key(http: httpx.AsyncClient) -> str:
    """Read the live Firebase Web API key from the app's own runtime config."""
    try:
        r = await http.get(f"{ep.MARKETING_BASE}{ep.MARKETING_CONFIG_JS}")
        m = re.search(r'"apiKey"\s*:\s*"(AIza[0-9A-Za-z_\-]{35})"', r.text)
        if m:
            return m.group(1)
        logger.warning("apiKey not found in config.js — using the pinned fallback")
    except Exception as e:
        logger.warning(f"config.js fetch failed ({e}) — using the pinned fallback")
    return ep.MARKETING_FIREBASE_API_KEY_FALLBACK


async def start_login(credentials: Credentials) -> LoginChallenge:
    """Ask Blinkit to email a magic link. Nothing is authenticated yet.

    Passwordless — `credentials.password` is ignored if set.
    """
    email = credentials.email
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        api_key = await _fetch_api_key(http)
        r = await http.post(
            f"{ep.MARKETING_BASE}{ep.MARKETING_REQUEST_MAGIC_LINK}",
            headers={**_headers(), "X-User-Email": email},
            json={},
        )
        if r.status_code != 200:
            raise LoginFailed(
                f"request-magic-link returned {r.status_code}: {r.text[:200]}"
            )
    logger.info(f"Magic link requested for {email}")
    return LoginChallenge(
        platform="blinkit",
        email=email,
        secret_kind=SecretKind.MAGIC_LINK,
        credentials=credentials,
        context={"api_key": api_key},
    )


async def _resolve_link(http: httpx.AsyncClient, link: str) -> str:
    """Unwrap click-tracking redirects to reach the real Firebase action URL.

    Blinkit sends through SendGrid, so what lands in the inbox is a
    ct.sendgrid.net wrapper. We follow redirects manually and stop the moment an
    oobCode appears — never loading /auth/action itself, because that page's JS
    is what consumes the single-use code.
    """
    for _ in range(8):
        code = _oob_from(link)
        if code:
            return link
        r = await http.get(link, follow_redirects=False, headers={"User-Agent": ep.USER_AGENT})
        loc = r.headers.get("location")
        if not loc:
            break
        link = loc
    raise LoginFailed(f"Could not find an oobCode in the login link: {link[:160]}")


def _oob_from(url: str) -> str | None:
    q = parse_qs(urlparse(url).query)
    if "oobCode" in q:
        return q["oobCode"][0]
    m = re.search(r"oobCode=([^&\s\"']+)", unquote(url))
    return m.group(1) if m else None


async def complete_login(challenge: LoginChallenge, secret: str) -> AuthSession:
    """Exchange the magic link for Firebase tokens and build a session."""
    api_key = challenge.context.get("api_key", ep.MARKETING_FIREBASE_API_KEY_FALLBACK)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        link = await _resolve_link(http, secret.strip().strip("<>\"'"))
        oob = _oob_from(link)

        r = await http.post(
            ep.FIREBASE_SIGNIN_EMAIL_LINK,
            params={"key": api_key},
            json={"email": challenge.email, "oobCode": oob},
        )
        if r.status_code != 200:
            detail = r.json().get("error", {}).get("message", r.text[:200])
            # EXPIRED_OOB_CODE / INVALID_OOB_CODE are the common ones — usually a
            # mail scanner or a human opened the link first (it is single-use).
            raise LoginFailed(f"signInWithEmailLink failed: {detail}")
        tok = r.json()

    return _session_from_tokens(challenge.email, api_key, tok)


def _session_from_tokens(email: str, api_key: str, tok: dict) -> AuthSession:
    """Build the three-layer storage_state Firebase and the app expect."""
    now_ms = int(time.time() * 1000)
    expires_in = int(tok.get("expiresIn", 3600))
    id_token = tok["idToken"]
    uid = tok.get("localId") or tok.get("user_id", "")

    idb = {
        "fbase_key": f"firebase:authUser:{api_key}:[DEFAULT]",
        "value": {
            "uid": uid,
            "email": email,
            "emailVerified": True,
            "isAnonymous": False,
            "providerData": [
                {
                    "providerId": "password",
                    "uid": email,
                    "displayName": None,
                    "email": email,
                    "phoneNumber": None,
                    "photoURL": None,
                }
            ],
            "stsTokenManager": {
                "refreshToken": tok["refreshToken"],
                "accessToken": id_token,
                "expirationTime": now_ms + expires_in * 1000,
            },
            "createdAt": str(now_ms),
            "lastLoginAt": str(now_ms),
            "apiKey": api_key,
            "appName": "[DEFAULT]",
        },
    }

    # `lastLoginTime` + `persistence` drive the app's own force-logout check
    # (getFirebaseUserTokenForRequest). Stamping them fresh here is what buys the
    # 7-day window instead of inheriting a frozen timestamp from an old capture.
    local_storage = [
        {
            "name": "state",
            "value": json.dumps(
                {
                    "login": {"token": id_token, "email": email},
                    "advertiser": {"complianceActionTaken": False},
                }
            ),
        },
        {"name": "lastLoginTime", "value": str(now_ms)},
        {"name": "persistence", "value": "true"},
        {"name": "sessionId", "value": str(uuid.uuid4())},
    ]

    return AuthSession(
        platform="blinkit",
        email=email,
        raw={
            "api_key": api_key,
            "uid": uid,
            "id_token": id_token,
            "refresh_token": tok["refreshToken"],
        },
        storage_state={
            "cookies": [],
            "origins": [{"origin": ep.MARKETING_BASE, "localStorage": local_storage}],
            "indexedDB": [idb],
        },
        headers={"firebase_user_token": id_token},
        expires_at=now_ist() + timedelta(days=ep.MARKETING_SESSION_DAYS_PERSISTENT),
    )


async def refresh(session: AuthSession) -> AuthSession | None:
    """Mint a fresh ID token from the stored refresh token — no email needed.

    Also re-stamps `lastLoginTime`, which is the part that actually matters: the
    Firebase refresh token long outlives the app's 7-day client-side gate, so
    without this a session dies while its credential is still perfectly valid.
    """
    api_key = session.raw.get("api_key")
    refresh_token = session.raw.get("refresh_token") or _legacy_refresh_token(session)
    if not (api_key and refresh_token):
        return None

    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        r = await http.post(
            ep.FIREBASE_REFRESH_TOKEN,
            params={"key": api_key},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if r.status_code != 200:
        logger.warning(f"Firebase refresh failed ({r.status_code}): {r.text[:200]}")
        return None

    d = r.json()
    return _session_from_tokens(
        session.email,
        api_key,
        {
            "idToken": d["id_token"],
            "refreshToken": d["refresh_token"],
            "expiresIn": d.get("expires_in", 3600),
            "localId": d.get("user_id", session.raw.get("uid", "")),
        },
    )


def _legacy_refresh_token(session: AuthSession) -> str | None:
    """Recover credentials from a pre-platform_auth row (bare storage_state)."""
    for item in session.storage_state.get("indexedDB", []) or []:
        key = item.get("fbase_key", "")
        if key.startswith("firebase:authUser:") and key.endswith(":[DEFAULT]"):
            if not session.raw.get("api_key"):
                session.raw["api_key"] = key[len("firebase:authUser:"): -len(":[DEFAULT]")]
            return (item.get("value", {}).get("stsTokenManager", {}) or {}).get("refreshToken")
    return None


async def probe(session: AuthSession) -> bool:
    """Is this session still usable? A refresh round-trip is the cheap proof.

    Costs one Google API call and no browser — versus the old check, which was
    "launch Chromium, navigate, see if we get redirected".
    """
    return await refresh(session) is not None
