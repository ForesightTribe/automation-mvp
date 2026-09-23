"""The Brand Portal transport: a logged-in Playwright page that carries our
own signed requests.

WHY A BROWSER AT ALL
====================
Signing needs no browser (signer.py reproduces the portal's signatures exactly).
Sending does. A plain httpx call carrying a VALID signature, the full browser
header set and a live token still returns
    403 {"... PermissionDenied ... Please reload the browser"}
while the identical headers/body issued from inside the logged-in page return
200. The edge gates on something transport-level (TLS / HTTP2 fingerprint), not
on the signature. So the page is a pipe: Python decides what to ask for and
computes the signature, then `signed_post` pushes it through `fetch`. We never
click a dashboard control, so there are no UI selectors to rot — only the login
form, which is one input and one button.

WHY WE LOG IN HERE RATHER THAN REUSE platform_auth's TOKEN
==========================================================
`platform_auth` mints a token over plain REST (sendVerificationCode /
signInWithOTP). That token is perfectly good for reading data, and the private
scrape still relies on that module for everything else. But the SPA will not
sign with it: injecting only localStorage logs the shell in while every data
call goes out unsigned (403). The cookies a genuine click-through login sets are
what make the app's own state complete. So this module does the real login once
and keeps the resulting storage state; the OTP is read from the shared mailbox
by the same `platform_auth.inbox.imap` reader the API login uses, so there is
still nothing manual.

The saved state is reused until it stops working, then we log in again. State
lives beside the module (one file per tenant) — it is a browser profile, not a
credential store, and `platform_sessions` stays the home of the API session.
"""
import asyncio
import json
import time
from pathlib import Path

from playwright.async_api import async_playwright

from app.utils.logger import logger
from platform_auth.inbox import imap
from platform_auth.types import LoginChallenge, SecretKind
from app.utils.time import now_ist
from scraper.platforms.instamart.dashboard_data.seller import endpoints as ep
from scraper.platforms.instamart.dashboard_data.seller.signer import get_signer

_PLATFORM = "instamart"


class PortalError(RuntimeError):
    """The portal refused a call, or the login could not be completed."""


def _state_path(tenant_id: str) -> Path:
    return ep.SESSION_STATE_DIR / f"portal_state_{tenant_id}.json"


def _claims(token: str) -> dict:
    import base64
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


class PortalSession:
    """A logged-in page, plus `signed_post` to run data calls through it.

    Use as an async context manager so the browser always closes:

        async with PortalSession(tenant_id, email, account_id) as portal:
            body = await portal.signed_post(ep.SALES_REPORTS, {...})
    """

    def __init__(self, tenant_id: str, email: str, account_id: str,
                 headless: bool = True) -> None:
        self.tenant_id = tenant_id
        self.email = email
        self.account_id = account_id
        self.headless = headless
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._token: str | None = None
        self._session_id: str | None = None
        self._token_exp = 0.0
        self._last_call = 0.0

    # -- lifecycle -----------------------------------------------------------
    async def __aenter__(self) -> "PortalSession":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        await self._open_context(reuse=True)
        healthy = await self._is_logged_in()
        if healthy:
            try:
                await self._read_token()
                healthy = self._token_is_live()
                if not healthy:
                    logger.info("Instamart portal: the saved session's token has expired")
            except PortalError:
                healthy = False
        if not healthy:
            logger.info("Instamart portal: saved state is not usable — logging in")
            await self._open_context(reuse=False)
            await self._login()
            await self._read_token()
        logger.info(
            f"Instamart portal ready (session {self._session_id}, "
            f"account {self.account_id})"
        )
        return self

    async def __aexit__(self, *exc) -> None:
        for closer in (self._browser, self._pw):
            try:
                await (closer.close() if closer is self._browser else closer.stop())
            except Exception:  # noqa: BLE001 — teardown must not mask the real error
                pass

    async def _open_context(self, reuse: bool) -> None:
        if self._ctx is not None:
            try:
                await self._ctx.close()
            except Exception:  # noqa: BLE001
                pass
        state = _state_path(self.tenant_id)
        kwargs = {"viewport": {"width": 1440, "height": 900}}
        if reuse and state.exists():
            kwargs["storage_state"] = str(state)
        self._ctx = await self._browser.new_context(**kwargs)
        # The signer carries a `webdriver` tripwire; it never fires for signing,
        # but the login page is a normal anti-bot surface, so stay quiet.
        await self._ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        self._page = await self._ctx.new_page()

    async def _save_state(self) -> None:
        ep.SESSION_STATE_DIR.mkdir(parents=True, exist_ok=True)
        await self._ctx.storage_state(path=str(_state_path(self.tenant_id)))

    # -- login ---------------------------------------------------------------
    async def _goto_transport(self) -> None:
        await self._page.goto(ep.PORTAL + ep.TRANSPORT_PATH,
                              wait_until="domcontentloaded",
                              timeout=ep.NAV_TIMEOUT_MS)
        await self._page.wait_for_timeout(ep.SETTLE_MS)

    async def _is_logged_in(self) -> bool:
        """True when an in-app route loads without bouncing to /login."""
        try:
            await self._goto_transport()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Instamart portal: navigation failed ({str(e)[:80]})")
            return False
        return "/login" not in self._page.url

    async def _click_any(self, labels: list[str]) -> bool:
        for label in labels:
            loc = self._page.get_by_role("button", name=label, exact=False)
            try:
                if await loc.count() and await loc.first.is_enabled():
                    await loc.first.click()
                    return True
            except Exception:  # noqa: BLE001 — try the next label
                continue
        return False

    async def _login(self) -> None:
        page = self._page
        await page.goto(ep.PORTAL + ep.LOGIN_PATH, wait_until="domcontentloaded",
                        timeout=ep.NAV_TIMEOUT_MS)
        await page.wait_for_timeout(3000)

        box = page.locator(ep.EMAIL_INPUT)
        if not await box.count():
            box = page.locator("input[type=text]").first
        await box.fill(self.email)

        requested_at = now_ist()
        if not await self._click_any(ep.SEND_OTP_LABELS):
            await box.press("Enter")
        await page.wait_for_timeout(3000)

        challenge = LoginChallenge(platform=_PLATFORM, email=self.email,
                                   secret_kind=SecretKind.OTP,
                                   requested_at=requested_at)
        otp = await imap.get_secret(challenge)

        boxes = page.locator(ep.OTP_BOX)
        if await boxes.count() >= len(otp):
            # These are React inputs that advance focus on real keystrokes;
            # fill() sets the DOM value but leaves the component's state empty,
            # so Login stays a no-op. Type it.
            await boxes.nth(0).click()
            await page.keyboard.type(otp, delay=ep.OTP_TYPE_DELAY_MS)
        else:
            await page.locator("input").last.fill(otp)

        await page.wait_for_timeout(1200)
        await self._click_any(ep.SUBMIT_LABELS)
        await page.wait_for_timeout(ep.SETTLE_MS)

        if "/login" in page.url:
            raise PortalError(
                f"Instamart login did not complete — still on {page.url}. "
                f"The OTP was read but rejected, or the form changed."
            )
        await self._save_state()
        logger.info("Instamart portal: logged in and state saved")
        await self._goto_transport()

    # -- the token the page is actually using --------------------------------
    async def _read_token(self) -> None:
        """Read the token out of the LIVE page, never the saved state file.

        The app refreshes its own access token as it runs, so the file we saved
        at login goes stale within hours. Signing with a stale token fails in
        confusing ways — the page's own fetch wrapper reports "TypeError: Failed
        to fetch" rather than a clean 401 — so always take what the page is
        holding right now.
        """
        raw = await self._page.evaluate(
            "() => localStorage.getItem('__IM_ADS_ACCESS_TOKEN__')"
        )
        if not raw:
            raise PortalError(
                "No __IM_ADS_ACCESS_TOKEN__ in the page — not logged in, or the "
                "app stores its token under a different key now."
            )
        # The app JSON-encodes each value it puts in localStorage.
        self._token = json.loads(raw) if raw.startswith('"') else raw
        claims = _claims(self._token)
        self._session_id = claims.get("session_id")
        if not self._session_id:
            raise PortalError("The portal token carries no session_id claim.")
        self._token_exp = float(claims.get("exp") or 0)

    def _token_is_live(self) -> bool:
        """With a minute of headroom, so a call cannot start on a dying token."""
        return self._token_exp - time.time() > 60

    @property
    def token(self) -> str:
        if not self._token:
            raise PortalError("Session not started.")
        return self._token

    def brand_account_id(self) -> str | None:
        """The brand-account id the report filter needs.

        This is a THIRD id, distinct from the advertiser account
        (`x-client-account-id`) and from the 40-hex brand id the filters
        endpoint returns. Nothing in the JWT or any API response carries it —
        the app keeps the brand the user picked in localStorage, so we read it
        from the session the browser built. Falls back to whatever the caller
        configured when the picker has never been touched.
        """
        state = json.loads(_state_path(self.tenant_id).read_text())
        store = {
            item["name"]: item["value"]
            for origin in state.get("origins", [])
            for item in origin.get("localStorage", [])
        }
        raw = store.get("__IM_ADS_SELECTED_BRAND_KEYS__")
        if not raw:
            return None
        try:
            picked = json.loads(raw)["state"]["selectedBrands"][self.account_id]
            return picked["value"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def user_block(self) -> dict:
        """The `user` object the data endpoints expect, straight from the JWT."""
        c = _claims(self.token)
        return {"user_id": c["sub"], "email": c.get("email", self.email),
                "user_pool": c.get("user_pool", ep.USER_POOL)}

    # -- signed calls --------------------------------------------------------
    def _headers(self, request_id: str, timestamp_ms: int) -> dict:
        return {
            "authorization": f"Bearer {self.token}",
            "x-client-account-id": self.account_id,
            "x-client-id": ep.DATA_CLIENT_ID,
            "app_version": ep.APP_VERSION,
            "x-client-request-id": request_id,
            "x-timestamp": str(timestamp_ms),
            "x-signature": get_signer().sign(timestamp_ms, request_id, self._session_id),
            "content-type": "application/json",
        }

    async def signed_post(self, path: str, body: dict) -> dict:
        """POST `body` to a data endpoint, signed by us, sent by the page."""
        import uuid

        # The app may have rotated its token since the last call.
        await self._read_token()

        # Keep a floor between signed calls; the edge throttles bursts.
        gap = ep.SIGNED_CALL_GAP_S - (time.monotonic() - self._last_call)
        if gap > 0:
            await asyncio.sleep(gap)

        last = ""
        attempts = len(ep.SIGNED_RETRY_WAITS_S) + 1
        for attempt in range(1, attempts + 1):
            # Fresh id and timestamp per attempt: both are inside the signature,
            # and a replayed pair is exactly what the edge rejects.
            request_id = str(uuid.uuid4())
            timestamp_ms = int(time.time() * 1000)
            headers = self._headers(request_id, timestamp_ms)
            result = await self._page.evaluate(
                """async ({url, headers, body}) => {
                       const r = await fetch(url, {
                           method: 'POST', headers,
                           body: JSON.stringify(body),
                       });
                       return {status: r.status, text: await r.text()};
                   }""",
                {"url": ep.DATA + path, "headers": headers, "body": body},
            )
            self._last_call = time.monotonic()
            if result["status"] == 200:
                try:
                    return json.loads(result["text"])
                except json.JSONDecodeError as e:
                    raise PortalError(f"{path} returned unparseable JSON: {e}") from e

            last = f"{result['status']}: {result['text'][:200]}"
            if result["status"] == 403 and attempt <= len(ep.SIGNED_RETRY_WAITS_S):
                wait = ep.SIGNED_RETRY_WAITS_S[attempt - 1]
                logger.warning(
                    f"{path} -> 403 (throttled); waiting {wait}s and retrying "
                    f"({attempt}/{len(ep.SIGNED_RETRY_WAITS_S)})"
                )
                await asyncio.sleep(wait)
                # Deliberately NOT re-navigating: a reload races the next
                # evaluate and surfaces as "TypeError: Failed to fetch". The
                # page context is fine — the edge is simply refusing us.
                continue
            break
        raise PortalError(f"{path} returned {last}")
