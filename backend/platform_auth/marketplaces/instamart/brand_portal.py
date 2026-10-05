"""Instamart Brand Portal (partner.instamart.in) — browserless OTP login.

A sibling of blinkit/seller.py, and shaped like it: a plain REST identity
service, three calls, no Chromium anywhere.

    1. POST /v1/accounts/sendVerificationCode  {email, client_id}
                                               -> {user_id, session_info}; emails a 6-digit OTP
    2. POST /v1/accounts/signInWithOTP         {otp, user_id, session_info, client_id}
                                               -> {access_token (JWT, 5 h), refresh_token}
    3. POST /v1/token/refresh                  {user_id: <JWT sub>, refresh_token, client_id}
                                               -> {access_token, refresh_token, expires_at}

Three things shape the code below:

**No password.** Possession of the mailbox is the whole credential, so
`needs_password=False` and `credentials.password` is ignored — exactly Blinkit.

**It refreshes.** The access token lives 5 hours and `/v1/token/refresh` reissues
it without a new OTP; the refresh token itself does not rotate. So this module
has a `refresh`, the registry marks it `refreshable=True`, and what gets
scheduled is `auth.refresh` (Blinkit-style), never a daily login (Zepto-style).
The refresh token's own lifetime is not yet measured; until it is, assume a
re-login will eventually be needed and keep the mail rule live.

**The account id is part of the credential.** Every data call carries
`x-client-account-id`; the bearer token alone is refused. That id is not in the
JWT and no identity call returns it, so it is stored per tenant in
`platform_credentials.extra["account_id"]` (Blinkit resolves its entity at login;
here there is nothing to resolve from, so it is configured once). A session
built without it is live but useless for data — the login logs that loudly
rather than failing, the same choice Zepto makes for a missing brand id.

`probe` deliberately does NOT hit a data endpoint: those need a per-request
signature this package cannot produce (see endpoints.py). Nor does it refresh —
a refresh inside probe would mint a token that `ensure()` then discards, handing
the caller the stale one. So probe is the CLOCK: the access token is good while
its `exp` is comfortably ahead. When it is not, `ensure()` climbs to `refresh`,
which is the network step and stores what it mints. A session revoked with time
still on the token slips past probe and surfaces as a 401/403 on the first data
call, where the scraper's own re-login path handles it — the same trade
Blinkit's marketing login makes.
"""
import base64
import json
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.utils.logger import logger
from app.utils.time import IST, now_ist
from platform_auth.errors import LoginFailed
from platform_auth.marketplaces.instamart import endpoints as ep
from platform_auth.types import AuthSession, Credentials, LoginChallenge, SecretKind

_TIMEOUT = 30
_PLATFORM = "instamart"
# probe() reports a token as dead this long BEFORE its exp, so a scrape that
# starts near the boundary gets a refresh up front instead of a 401 mid-run.
_PROBE_MARGIN = timedelta(minutes=15)


def _idp_headers() -> dict:
    """The identity service wants nothing beyond JSON and a browser-like origin."""
    return {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": ep.PORTAL,
        "referer": ep.PORTAL + "/",
    }


def data_headers(access_token: str, account_id: str | None = None) -> dict:
    """The static part of a data call's headers — what `AuthSession.headers`
    carries. The per-request part (request id, timestamp, signature) is added
    by whoever makes the call."""
    h = {
        "authorization": f"Bearer {access_token}",
        "x-client-id": ep.DATA_CLIENT_ID,
        "app_version": ep.APP_VERSION,
        "accept": "*/*",
        "content-type": "application/json",
        "origin": ep.PORTAL,
        "referer": ep.PORTAL + "/",
    }
    if account_id:
        h["x-client-account-id"] = account_id
    return h


def _decode_jwt(token: str) -> dict:
    """Claims only — no signature check; the issuer's JWKS is public but we are
    not the audience, we just read our own token's `exp` and `sub`."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception as e:                                   # noqa: BLE001
        raise LoginFailed(f"access_token is not a readable JWT: {e}")


# ── Login ─────────────────────────────────────────────────────────────────────

async def start_login(credentials: Credentials) -> LoginChallenge:
    """Request the OTP. Passwordless — `credentials.password` is ignored if set."""
    email = credentials.email
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        r = await http.post(
            f"{ep.IDP}{ep.SEND_VERIFICATION_CODE}",
            headers=_idp_headers(),
            json={"email": email, "client_id": ep.CLIENT_ID},
        )
    if r.status_code != 200:
        raise LoginFailed(f"sendVerificationCode returned {r.status_code}: {r.text[:200]}")

    body = r.json()
    user_id, session_info = body.get("user_id"), body.get("session_info")
    if not (user_id and session_info):
        # A 200 without the pair means no OTP is coming — an unknown address, or
        # the identity service changed shape. Fail now rather than wait two
        # minutes for a mail that will never arrive.
        raise LoginFailed(
            f"sendVerificationCode succeeded but returned no user_id/session_info: "
            f"{r.text[:200]}"
        )

    logger.info(f"Instamart OTP requested for {email}")
    return LoginChallenge(
        platform=_PLATFORM,
        email=email,
        secret_kind=SecretKind.OTP,
        credentials=credentials,
        context={"user_id": user_id, "session_info": session_info},
    )


async def complete_login(challenge: LoginChallenge, secret: str) -> AuthSession:
    """Exchange the OTP for the token pair that is the whole credential."""
    otp = "".join(ch for ch in secret if ch.isdigit())[: ep.OTP_DIGITS]
    if len(otp) != ep.OTP_DIGITS:
        raise LoginFailed(f"Expected a {ep.OTP_DIGITS}-digit OTP, got {secret[:40]!r}")

    user_id = challenge.context.get("user_id")
    session_info = challenge.context.get("session_info")
    if not (user_id and session_info):
        raise LoginFailed("No user_id/session_info on the challenge — start_login did not run.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        r = await http.post(
            f"{ep.IDP}{ep.SIGN_IN_WITH_OTP}",
            headers=_idp_headers(),
            json={
                "otp": otp,
                "user_id": user_id,
                "session_info": session_info,
                "client_id": ep.CLIENT_ID,
            },
        )
    if r.status_code != 200:
        raise LoginFailed(f"signInWithOTP returned {r.status_code}: {r.text[:200]}")

    body = r.json()
    access, refresh = body.get("access_token"), body.get("refresh_token")
    if not (access and refresh):
        raise LoginFailed(f"OTP rejected or expired: {r.text[:200]}")

    account_id = (challenge.credentials.extra if challenge.credentials else {}) \
        .get(ep.ACCOUNT_ID_KEY)
    return _build(challenge.email, access, refresh, account_id)


def _build(
    email: str, access_token: str, refresh_token: str,
    account_id: str | None, expires_epoch: int | None = None,
) -> AuthSession:
    claims = _decode_jwt(access_token)
    exp = expires_epoch or claims.get("exp")
    # Naive IST wall-clock, matching every other timestamp in the app.
    expires_at = (
        datetime.fromtimestamp(exp, IST).replace(tzinfo=None) if exp
        else now_ist() + timedelta(hours=ep.ACCESS_TOKEN_HOURS)
    )
    if expires_at:
        hours = (expires_at - now_ist()).total_seconds() / 3600
        logger.info(
            f"Instamart session for {email}: access token expires "
            f"{expires_at:%Y-%m-%d %H:%M:%S} IST ({hours:.1f}h); refreshable."
        )
    if not account_id:
        # Live but useless for data — every brand-portal call needs the account
        # id. Say so at login rather than fail obscurely on the first scrape.
        logger.warning(
            f"Instamart login for {email} has no account_id configured — set it with: "
            f"cli auth credentials set instamart -t <tenant> --email {email} "
            f"--extra {ep.ACCOUNT_ID_KEY}=<x-client-account-id from the portal>"
        )

    raw: dict[str, Any] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user_id": claims.get("sub"),            # what /v1/token/refresh wants
        "session_id": claims.get("session_id"),
        "session_started_at": claims.get("siat"),
        "user_pool": claims.get("user_pool"),
        ep.ACCOUNT_ID_KEY: account_id,
    }
    return AuthSession(
        platform=_PLATFORM,
        email=email,
        raw=raw,
        # Browser projection. The token travels in a header, not a cookie, so
        # there is nothing the SPA reads from cookies; where it keeps the token
        # client-side (localStorage key names) is NOT yet confirmed. Kept as a
        # best-effort seed for a Playwright page, to be corrected once the
        # private scraper decides whether it needs one at all.
        storage_state={
            "cookies": [],
            "origins": [{
                "origin": ep.PORTAL,
                "localStorage": [
                    {"name": "access_token", "value": access_token},
                    {"name": "refresh_token", "value": refresh_token},
                ],
            }],
        },
        headers=data_headers(access_token, account_id),
        expires_at=expires_at,
    )


# ── Refresh / probe ──────────────────────────────────────────────────────────

async def _refresh_call(raw: dict) -> dict | None:
    """One /v1/token/refresh. None on any failure (logged), the JSON body on 200."""
    user_id, refresh_token = raw.get("user_id"), raw.get("refresh_token")
    if not (user_id and refresh_token):
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            r = await http.post(
                f"{ep.IDP}{ep.TOKEN_REFRESH}",
                headers=_idp_headers(),
                json={"user_id": str(user_id), "refresh_token": refresh_token,
                      "client_id": ep.CLIENT_ID},
            )
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"Instamart refresh error: {e}")
        return None
    if r.status_code != 200:
        logger.warning(f"Instamart refresh failed ({r.status_code}): {r.text[:200]}")
        return None
    body = r.json()
    return body if body.get("access_token") else None


async def refresh(session: AuthSession) -> AuthSession | None:
    """Reissue the access token — never needs a new OTP while the refresh token lives."""
    body = await _refresh_call(session.raw)
    if body is None:
        return None
    return _build(
        session.email,
        body["access_token"],
        body.get("refresh_token") or session.raw["refresh_token"],
        session.raw.get(ep.ACCOUNT_ID_KEY),
        expires_epoch=body.get("expires_at"),
    )


async def probe(session: AuthSession) -> bool:
    """Is the access token still usable? Clock only — see the module docstring
    for why this is neither a data call nor a refresh."""
    access = session.raw.get("access_token")
    if not access:
        return False
    try:
        exp = _decode_jwt(access).get("exp")
    except LoginFailed:
        return False
    if not exp:
        return False
    expires_at = datetime.fromtimestamp(exp, IST).replace(tzinfo=None)
    alive = expires_at - now_ist() > _PROBE_MARGIN
    if not alive:
        logger.info(
            f"Instamart session {session.raw.get('session_id')}: access token "
            f"expired/expiring ({expires_at:%H:%M:%S} IST) — refresh needed."
        )
    return alive
