"""Blinkit seller dashboard, NEW domain (seller.blinkit.com) — browser-backed OTP login.

For accounts Blinkit has already migrated off partnersbiz.com (see the note on
`SELLER_BASE` in endpoints.py) — e.g. Sereko's kriti.agarwal@foresighttribe.com,
confirmed migrated 2026-09-29. `seller.py` cannot serve these: `send_otp` there
returns `{"action":"signup"}` and `verify_otp` 500s, because that account's
identity now lives on this domain instead.

**There is no REST shortcut here, unlike every other module in this package.**
seller.blinkit.com sits behind Cloudflare bot management that fingerprints the
connection itself, not just the request headers — verified twice:
  - 2026-09-29: the bare login page 403s over plain httpx before any API call.
  - 2026-09-30 (Phase B): with a live logged-in session, the FIVE real calls
    the dashboard itself makes (app/config, app/feed, notifications, faq×2)
    were captured with their exact browser headers, INCLUDING the real Cookie
    header — and every one still 403'd instantly when replayed via httpx.
    Identical headers and valid cookies are not enough; only a real browser
    connection gets through. So every operation below drives Chromium.

Login, through the browser:

    1. Click "Login", fill email, click "Send OTP" -> POST .../send_otp
       (in-app; the exact path isn't captured, only observed via the response
       listener). Rate-limited by Blinkit itself, account/IP-wide — confirmed
       2026-09-29 by a manual (non-automated) attempt hitting the same
       "exceeded maximum OTP retries" block, so it is not an automation
       fingerprint issue and there is nothing this module can do about it
       except wait.
    2. Fill the 6 OTP digit boxes. **This modal has no visible submit button —
       it auto-submits on the 6th digit**, firing verify_otp immediately. The
       response listener must be armed BEFORE the last digit is filled, not
       clicked afterward — a button-click approach silently misses the
       response and times out (this broke the first working login attempt on
       2026-09-30 before the fix below).
    3. verify_otp returns access_token/refresh_token, and cookies land:
       access_token, refresh_token, user_id, seller_id, device_id.

**The real credential is the on-disk browser profile, not the token pair.** A
persistent Playwright profile (kept under `_seller_new_profiles/<email>/`,
gitignored) is what lets Cloudflare treat repeat runs as the same returning
device rather than a new bot login every time. `AuthSession.raw` carries the
token pair for bookkeeping, but reopening the SAME profile is what actually
keeps this working without burning a fresh OTP on every call — see `probe`.

**No known refresh endpoint.** Unlike partnersbiz.com's `/tokens/rotate`, no
equivalent has been observed on this domain. `refresh` is not implemented and
the registry marks this `refreshable=False`; `ensure()` falls back to a full
browser login (a new OTP) whenever the profile's own session goes stale.
Revisit if a rotate/refresh call is ever seen in the dashboard's own traffic.

**`probe` is the ONLY cheap-ish path, and it still costs a browser launch.**
Phase B ruled out a plain httpx liveness check entirely: Cloudflare 403s it
regardless of cookie validity. So `probe` reopens the persistent profile
headless and checks whether it lands on a dashboard route without hitting the
login form. Real, but not free — there is no cheaper option on this domain.
"""
import re
from datetime import timedelta
from pathlib import Path

from playwright.async_api import async_playwright

from app.utils.logger import logger
from app.utils.time import now_ist
from platform_auth.errors import LoginFailed
from platform_auth.marketplaces.blinkit import endpoints as ep
from platform_auth.types import AuthSession, Credentials, LoginChallenge, SecretKind

_PLATFORM = "blinkit_seller_new"
_NAV_TIMEOUT_MS = 45_000
_RESPONSE_TIMEOUT_MS = 15_000
# Unconfirmed — no refresh endpoint exists, so this is only a soft hint for
# anything that reads expires_at; probe() is what actually decides liveness.
_SESSION_DAYS_GUESS = 1

_PROFILE_ROOT = Path(__file__).parent / "_seller_new_profiles"

_LAUNCH_ARGS = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
_VIEWPORT = {"width": 1280, "height": 900}


def _profile_dir(email: str) -> str:
    """One persistent Chrome profile per email, so a shared mailbox across
    tenants (if that ever happens) never collides on device identity."""
    safe = re.sub(r"[^a-zA-Z0-9_.@-]", "_", email)
    d = _PROFILE_ROOT / safe
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


async def start_login(credentials: Credentials) -> LoginChallenge:
    """Open the persistent profile and trigger a fresh OTP.

    Keeps the browser context ALIVE in `challenge.context` — `complete_login`
    resumes in the SAME browser session, not a fresh one, because a new
    context would have to clear Cloudflare's challenge all over again.

    If the profile happens to already be authenticated (e.g. a prior manual
    test left it logged in), cookies are cleared first so the login form
    reliably reappears — `login()`'s caller always expects an OTP challenge
    back, and there is no hook in service.py to skip waiting for one. Skipping
    a real login when the profile is already good is `probe`'s job, not this
    one's.
    """
    email = credentials.email
    p = await async_playwright().start()
    context = await p.chromium.launch_persistent_context(
        _profile_dir(email),
        headless=True,
        args=_LAUNCH_ARGS,
        viewport=_VIEWPORT,
        user_agent=ep.USER_AGENT,
    )
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(f"{ep.SELLER_BASE_NEW}/", wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)

    if "/dashboard" in page.url:
        await context.clear_cookies()
        await page.goto(f"{ep.SELLER_BASE_NEW}/", wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)

    try:
        await page.get_by_role("button", name="Login").first.click()
        await page.wait_for_timeout(1000)
        await page.fill('input[name="userEmail"]', email)

        async with page.expect_response(
            lambda r: "send_otp" in r.url, timeout=_RESPONSE_TIMEOUT_MS
        ) as resp_info:
            await page.get_by_role("button", name="Send OTP").click()
        resp = await resp_info.value
        if resp.status != 200:
            body = await resp.text()
            raise LoginFailed(f"send_otp returned {resp.status}: {body[:200]}")
    except Exception:
        await context.close()
        await p.stop()
        raise

    logger.info(f"Seller (seller.blinkit.com) OTP requested for {email}")
    return LoginChallenge(
        platform=_PLATFORM,
        email=email,
        secret_kind=SecretKind.OTP,
        credentials=credentials,
        context={"playwright": p, "browser_context": context, "page": page},
    )


async def complete_login(challenge: LoginChallenge, secret: str) -> AuthSession:
    """Fill the OTP into the SAME browser session start_login opened."""
    p = challenge.context.get("playwright")
    context = challenge.context.get("browser_context")
    page = challenge.context.get("page")
    if page is None or context is None:
        raise LoginFailed(
            "No live browser page on the challenge — complete_login must run "
            "in the same process as start_login (a browser context cannot be "
            "handed across a process boundary)."
        )

    try:
        otp = "".join(ch for ch in secret if ch.isdigit())[:6]
        if len(otp) != 6:
            raise LoginFailed(f"Expected a 6-digit OTP, got {secret[:40]!r}")

        inputs = await page.eval_on_selector_all(
            "input",
            "els => els.map((e,i) => ({i, name: e.name, visible: e.offsetParent !== null}))",
        )
        otp_inputs = [i for i in inputs if i["name"] != "userEmail" and i["visible"]]
        if len(otp_inputs) < 6:
            raise LoginFailed(f"Unexpected OTP input count: {len(otp_inputs)}")

        # No visible submit button — the form auto-submits on the last digit,
        # so the listener must be armed BEFORE that fill, not clicked after.
        async with page.expect_response(
            lambda r: "verify_otp" in r.url, timeout=_RESPONSE_TIMEOUT_MS
        ) as vresp_info:
            for idx, digit in enumerate(otp):
                sel_index = otp_inputs[idx]["i"]
                await page.locator("input").nth(sel_index).fill(digit)
        vresp = await vresp_info.value
        if vresp.status != 200:
            body = await vresp.text()
            raise LoginFailed(f"verify_otp returned {vresp.status}: {body[:200]}")

        await page.wait_for_timeout(2000)
        existing_btn = page.get_by_role("button", name=re.compile("existing account", re.I))
        if await existing_btn.count():
            await existing_btn.first.click()
            await page.wait_for_timeout(2000)

        cookies = await context.cookies()
        by_name = {c["name"]: c["value"] for c in cookies}
        if not by_name.get("access_token"):
            raise LoginFailed(f"Landed on {page.url} but no access_token cookie was set.")

        logger.info(f"Seller (seller.blinkit.com): login successful, seller_id={by_name.get('seller_id')}")
        return _build(challenge.email, cookies, by_name)
    finally:
        await context.close()
        await p.stop()


def _build(email: str, cookies: list[dict], by_name: dict) -> AuthSession:
    expires = now_ist() + timedelta(days=_SESSION_DAYS_GUESS)
    return AuthSession(
        platform=_PLATFORM,
        email=email,
        raw={
            "access_token": by_name.get("access_token"),
            "refresh_token": by_name.get("refresh_token"),
            "user_id": by_name.get("user_id"),
            "seller_id": by_name.get("seller_id"),
            "device_id": by_name.get("device_id"),
        },
        # Best-effort projection for anything that inspects cookies directly.
        # It is NOT a complete credential on its own — a fresh browser cannot
        # bootstrap from these cookies alone, because Cloudflare's pass/fail
        # signal lives in the connection, not in anything cookie-shaped
        # (Phase B, 2026-09-30). The actual credential is the profile
        # directory these cookies were harvested from.
        storage_state={"cookies": cookies, "origins": []},
        # No known-good header set works outside a real browser (Phase B), so
        # there is nothing useful to hand a direct-API consumer.
        headers={},
        expires_at=expires,
    )


async def probe(session: AuthSession) -> bool:
    """Reopen the persistent profile and check it is still on a dashboard
    route. The only liveness check this domain allows — see module docstring
    for why a plain httpx call can't answer this instead."""
    email = session.email
    if not email:
        return False
    p = await async_playwright().start()
    try:
        context = await p.chromium.launch_persistent_context(
            _profile_dir(email),
            headless=True,
            args=_LAUNCH_ARGS,
            viewport=_VIEWPORT,
            user_agent=ep.USER_AGENT,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(
                f"{ep.SELLER_BASE_NEW}/dashboard", wait_until="networkidle", timeout=_NAV_TIMEOUT_MS
            )
            alive = "/dashboard" in page.url
            if not alive:
                logger.info(f"Seller (seller.blinkit.com) probe for {email}: profile session is dead.")
            return alive
        finally:
            await context.close()
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"Seller (seller.blinkit.com) probe error: {e}")
        return False
    finally:
        await p.stop()
