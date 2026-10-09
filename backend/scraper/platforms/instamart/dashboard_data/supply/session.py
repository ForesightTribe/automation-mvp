"""Get a live `abacus-token` for the Supply Portal, cached in the database.

Confirmed live 2026-09-25 (see `endpoints.py`'s module docstring for the full
investigation): the Brand Portal login (`seller/session.py`'s `PortalSession`)
already carries everything the Supply Portal needs. Navigating that SAME
logged-in page to `/im-vendor/po-dashboard` makes the vendor SPA mint its own
`abacus-token` and use it to call `picker.swiggy.com` — no separate login,
no OTP. The token itself:

* lives ONLY in the SPA's in-memory request state — never localStorage,
  sessionStorage, nor a readable cookie — so it has to be sniffed off a
  request the page makes itself, not read out of storage.
* is a plain bearer JWT good for 5 hours (`exp - iat` on a captured token),
  and — unlike the Brand Portal's signed calls — works from a PLAIN httpx
  call with the browser closed. `picker.swiggy.com` does not enforce the
  transport-fingerprint gate `brand-portal-service-http.swiggy.com` does.

So the design: spend one Playwright trip to capture a token, then run every
data call afterward as fast, unthrottled httpx — the opposite performance
profile from the ads scrape, which is throttled almost every call. The token
is cached (its own `exp` claim decides freshness) so a same-day re-run costs
nothing extra — encrypted in `platform_sessions` under `_TOKEN_SLUG`, the same
store and shape as the Brand Portal's own browser state
(seller/session.py's `_SESSION_SLUG`), not as a file in the source tree.
"""
import base64
import datetime as dt
import json
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger import logger
from platform_auth import store
from platform_auth.types import AuthSession
from scraper.platforms.instamart.dashboard_data.seller.session import PortalSession
from scraper.platforms.instamart.dashboard_data.supply import endpoints as ep


# Its own platform_sessions row — NOT a registered login (platform_auth/registry.py):
# nothing refreshes or probes it; it is a derived ~5-hour API token, re-minted
# from the Brand Portal session whenever it runs out.
_TOKEN_SLUG = "instamart_supply_token"

# A minute of headroom, same convention as seller/session.py's token check.
_HEADROOM_S = 60


class SupplyAuthError(RuntimeError):
    """Could not obtain a usable abacus-token."""


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


async def _load_cached(db: AsyncSession, tenant_id: str) -> dict | None:
    """The stored token, if it still has headroom."""
    session = await store.load(db, tenant_id, _TOKEN_SLUG)
    data = session.raw if session else {}
    if data.get("token") and data.get("exp", 0) - time.time() > _HEADROOM_S:
        return data
    return None


async def _save_cache(db: AsyncSession, tenant_id: str, email: str, token: str,
                      brand_company_id: str) -> None:
    exp = _claims(token).get("exp", 0)
    # `update`, not `save`: re-minting this token is not a login, so it must not
    # stamp last_login_at or feed the logins-per-day count (IM-03).
    await store.update(db, tenant_id, AuthSession(
        platform=_TOKEN_SLUG, email=email,
        raw={"token": token, "brand_company_id": brand_company_id, "exp": exp},
        expires_at=dt.datetime.fromtimestamp(exp) if exp else None,
    ))


async def get_token(db: AsyncSession, tenant_id: str, email: str, account_id: str,
                    *, headless: bool = True, force: bool = False) -> tuple[str, str]:
    """Returns (abacus_token, brand_company_id). Reuses a cached token that
    still has headroom unless `force` asks for a fresh one.

    `db` holds both the cached token and PortalSession's own browser state.
    """
    if not force:
        cached = await _load_cached(db, tenant_id)
        if cached:
            logger.debug("Instamart Supply Portal: reusing the cached abacus-token")
            return cached["token"], cached["brand_company_id"]

    logger.debug("Instamart Supply Portal: minting a fresh abacus-token via the Brand Portal session")
    captured: dict = {}

    async with PortalSession(db, tenant_id, email, account_id, headless=headless) as portal:
        page = portal._page

        def on_request(req):
            if ep.DATA in req.url and "abacus-token" in req.headers and "token" not in captured:
                captured["token"] = req.headers["abacus-token"]
                try:
                    body = json.loads(req.post_data or "{}")
                    captured["brand_company_id"] = (
                        body.get("filters", {}).get("brand_company_id")
                    )
                except json.JSONDecodeError:
                    pass

        page.on("request", on_request)
        await page.goto(ep.PORTAL + ep.VENDOR_PATH, wait_until="domcontentloaded",
                        timeout=60_000)
        # The vendor SPA fires its own purchaseMetrics/searchPurchaseOrder
        # calls on load — give it time rather than triggering anything
        # ourselves (clicking around risks the app's own "session expired"
        # UI check, observed live and harmless but noisy).
        await page.wait_for_timeout(10_000)

    if "token" not in captured:
        raise SupplyAuthError(
            "No abacus-token seen after navigating to the Supply Portal — the "
            "vendor SPA may not have loaded, or it stopped minting one this way."
        )
    if not captured.get("brand_company_id"):
        raise SupplyAuthError(
            "Got an abacus-token but no brand_company_id from the page's own "
            "calls — every data call needs it."
        )

    await _save_cache(db, tenant_id, email, captured["token"], captured["brand_company_id"])
    return captured["token"], captured["brand_company_id"]
