"""Zepto Brand Console (brands.zepto.co.in) — browserless password + OTP login.

Two calls, no Chromium anywhere:

    1. POST /api/v1/auth/sign-in            {email, password} -> mfaId, emails a 4-digit OTP
    2. POST /vendor/api/v1/auth/validate-mfa-otp/  {otp, mfaId, applicationId} -> jwtToken

Three things make Zepto different from both Blinkit dashboards, and each one
shapes the code below:

**It needs a password.** Blinkit's logins are passwordless — possession of the
mailbox is the whole credential. Zepto wants email + password *and* an emailed
OTP, which is why `Authenticator.needs_password` exists and why
`platform_credentials.encrypted_password` finally gets used.

**There is no refresh.** `refreshToken` is null in every response and the API
exposes no rotate/renew endpoint. The JWT expires at **local midnight IST** —
not after a fixed duration. Confirmed across three logins issued at different
times (7.06 h, 6.24 h and 5.25 h of life) that all carried the same `exp`. So
this module has no `refresh`, the registry marks it `refreshable=False`, and a
fresh OTP is needed once a day. That is why `auth.login` is scheduled for Zepto
where Blinkit only ever schedules `auth.refresh`.

**One session per user.** A new login server-side revokes the previous one, in
both directions: our login evicts a human's dashboard, and their login kills our
session mid-run. A dead session therefore reads as 401 "Invalid Token" long
before `expires_at`, which is exactly why `probe` exists and why `ensure()`
must never trust the clock alone.
"""
import base64
import json
from datetime import datetime

import httpx

from app.utils.logger import logger
from app.utils.time import IST, now_ist
from platform_auth.errors import LoginFailed
from platform_auth.marketplaces.zepto import endpoints as ep
from platform_auth.types import AuthSession, Credentials, LoginChallenge, SecretKind

_TIMEOUT = 30
_PLATFORM = "zepto"


def _headers(jwt: str = "") -> dict:
    """Base headers. `authorization` is the RAW jwt — never 'Bearer <jwt>'."""
    h = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": ep.CONSOLE,
        "referer": f"{ep.CONSOLE}/",
        "user-agent": ep.USER_AGENT,
    }
    if jwt:
        h["authorization"] = jwt
    return h


def _decode_jwt(token: str) -> dict:
    """Read the payload claims. Signature is Zepto's business, not ours.

    We only want `exp` (a real expiry beats a guess) and `sessionId` (the handle
    that distinguishes 'expired' from 'evicted by another login'). A malformed
    token must not break a login, so this degrades to {} rather than raising.
    """
    try:
        seg = token.split(".")[1]
        pad = "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg + pad))
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"Zepto: could not decode the JWT payload ({e})")
        return {}


async def start_login(credentials: Credentials) -> LoginChallenge:
    """Submit email + password; Zepto emails a 4-digit OTP and hands back an mfaId."""
    if not credentials.password:
        raise LoginFailed(
            "Zepto needs a password. Set one with: "
            f"cli auth credentials set {_PLATFORM} -t <tenant> "
            f"--email {credentials.email} --password"
        )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        r = await http.post(
            f"{ep.API}{ep.SIGN_IN}",
            params={"applicationId": ep.APP_ID},
            headers=_headers(),
            json={"email": credentials.email, "password": credentials.password},
        )
    if r.status_code != 200:
        raise LoginFailed(f"sign-in returned {r.status_code}: {r.text[:200]}")

    body = r.json()
    mfa_id = body.get("mfaId")
    if not mfa_id:
        # A 200 with no mfaId means the credentials were rejected, or MFA is off
        # for this account. Either way there is no OTP coming, so failing here is
        # better than waiting two minutes for mail that will never arrive.
        raise LoginFailed(
            f"sign-in succeeded but returned no mfaId (mfaEnabled="
            f"{body.get('mfaEnabled')!r}) — check the stored password."
        )

    logger.info(f"Zepto OTP requested for {credentials.email}")
    return LoginChallenge(
        platform=_PLATFORM,
        email=credentials.email,
        secret_kind=SecretKind.OTP,
        credentials=credentials,
        context={"mfa_id": mfa_id},
    )


async def complete_login(challenge: LoginChallenge, secret: str) -> AuthSession:
    """Exchange the OTP for the JWT that is the whole credential."""
    otp = "".join(ch for ch in secret if ch.isdigit())[: ep.OTP_DIGITS]
    if len(otp) != ep.OTP_DIGITS:
        raise LoginFailed(f"Expected a {ep.OTP_DIGITS}-digit OTP, got {secret[:40]!r}")

    mfa_id = challenge.context.get("mfa_id")
    if not mfa_id:
        raise LoginFailed("No mfaId on the challenge — start_login did not run.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        r = await http.post(
            f"{ep.API}{ep.VALIDATE_MFA_OTP}",
            headers=_headers(),
            json={"otp": otp, "mfaId": mfa_id, "applicationId": ep.APP_ID},
        )
    if r.status_code != 200:
        raise LoginFailed(f"validate-mfa-otp returned {r.status_code}: {r.text[:200]}")

    body = r.json()
    jwt = body.get("jwtToken")
    if not jwt:
        raise LoginFailed(f"OTP rejected or expired: {r.text[:200]}")

    return _build(challenge.email, jwt, body)


def _build(email: str, jwt: str, body: dict) -> AuthSession:
    claims = _decode_jwt(jwt)
    exp = claims.get("exp")
    # Naive IST wall-clock, matching every other timestamp in the app.
    expires_at = (
        datetime.fromtimestamp(exp, IST).replace(tzinfo=None) if exp else None
    )
    tags = body.get("tags") or {}
    brand_ids = tags.get("brandIds") or []

    if expires_at:
        hours = (expires_at - now_ist()).total_seconds() / 3600
        logger.info(
            f"Zepto session for {email}: expires {expires_at:%Y-%m-%d %H:%M:%S} IST "
            f"({hours:.1f}h) — Zepto expires at local midnight, so a short life "
            "late in the day is normal, not a fault."
        )
    if not brand_ids:
        # Every ads call is scoped by brand_id, so a session without one is live
        # but useless. Better to say so at login than to fail obscurely later.
        logger.warning(
            f"Zepto login for {email} returned no brandIds — the account may lack "
            "ads access."
        )

    return AuthSession(
        platform=_PLATFORM,
        email=email,
        # The native credential. Unlike Blinkit there is nothing to project into a
        # browser: the JWT travels in a header, so `storage_state` stays empty.
        raw={
            "jwt": jwt,
            "user_id": body.get("userId"),
            "session_id": claims.get("sessionId"),
            "brand_ids": brand_ids,
            "manufacturer_ids": tags.get("manufacturerId") or [],
            "role_name": claims.get("roleName") or body.get("roleName"),
        },
        headers=_headers(jwt),
        expires_at=expires_at,
    )


async def probe(session: AuthSession) -> bool:
    """Is the session ACTUALLY alive?

    Load-bearing for Zepto in a way it is not for Blinkit: single-session
    eviction means a session can die minutes after it was issued, with hours left
    on `expires_at`. The clock cannot answer this question; only a call can.
    """
    jwt = session.raw.get("jwt")
    if not jwt:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            r = await http.get(
                f"{ep.API}{ep.GET_USER_BY_TOKEN}",
                params={"parentApplicationId": ep.PARENT_APP_ID},
                headers=_headers(jwt),
            )
        if r.status_code == 401:
            logger.info(
                f"Zepto session {session.raw.get('session_id')} is dead "
                "(401) — expired at midnight, or evicted by another login."
            )
        return r.status_code == 200
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"Zepto probe error: {e}")
        return False
