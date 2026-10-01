"""Blinkit seller-hub (seller.blinkit.com) — sales scrape.

Unlike scraper/platforms/blinkit/dashboard_data/seller/scraper.py (the OLD
partnersbiz.com dashboard), this CANNOT be a plain httpx client. This domain's
Cloudflare bot management blocks a bare request even with a live session's
exact cookies/headers replayed — proven twice in
platform_auth/marketplaces/blinkit/seller_new.py (Phase B, 2026-09-30). A raw
in-page fetch() was also tried and failed with "Missing required headers for
AuthLevelRequired" — the SPA's own request layer adds something a hand-built
fetch doesn't. So this drives the real page and listens for the SPA's own
responses, the only approach proven to work against this domain.

The credential is the ON-DISK PERSISTENT PROFILE (seller_new.profile_dir), not
a token — `ensure()`'s storage_state is explicitly NOT a complete credential
for this domain (see seller_new.py's AuthSession docstring), so this module
never touches it. It only needs the session's EMAIL, to find the same profile
directory seller_new.py already logged into.
"""
import asyncio
import json

from playwright.async_api import async_playwright

from platform_auth.marketplaces.blinkit import endpoints as auth_ep
from platform_auth.marketplaces.blinkit.seller_new import profile_dir
from scraper.platforms.blinkit.dashboard_data.seller_hub import endpoints as ep
from app.utils.logger import logger

_NAV_TIMEOUT_MS = 30_000
_LAUNCH_ARGS = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
_VIEWPORT = {"width": 1280, "height": 900}


async def scrape_sales(email: str) -> dict:
    """One page visit to Sales Performance, captures the SPA's own calls to
    the metrics (day-grain, all products) and products/performance (item-
    grain, window total) endpoints. Returns the raw API payloads; parsing
    happens in parser.py.

    Only the dashboard's DEFAULT window ("Last 7 days") is captured — the
    UI's time-range dropdown was not reliably clickable headless in testing,
    so a scheduled daily run naturally builds history one default-window
    scrape at a time rather than trying to sweep every preset each run.
    """
    captured: dict[str, dict] = {}
    window_label: list[str] = []  # mutable box; the dashboard's own time_range_filter

    def on_request(req):
        if ep.SALES_BY_PRODUCT_PATH not in req.url or not req.post_data:
            return
        try:
            body = json.loads(req.post_data)
            label = (body.get("filters") or {}).get("time_range_filter")
            if label:
                window_label.append(label)
        except Exception:
            pass

    async def on_response(resp):
        url = resp.url
        if ep.SALES_METRICS_PATH not in url and ep.SALES_BY_PRODUCT_PATH not in url:
            return
        try:
            body = await resp.json()
        except Exception:
            return
        captured[url] = body

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            profile_dir(email),
            headless=True,
            args=_LAUNCH_ARGS,
            viewport=_VIEWPORT,
            user_agent=auth_ep.USER_AGENT,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            page.on("response", lambda r: asyncio.create_task(on_response(r)))
            page.on("request", on_request)

            await page.goto(
                f"{ep.BASE_URL}{ep.SALES_PERFORMANCE_PAGE}",
                wait_until="networkidle",
                timeout=_NAV_TIMEOUT_MS,
            )
            if "/dashboard" not in page.url:
                raise RuntimeError(
                    f"Not on a dashboard route — session may be dead. Landed on {page.url}. "
                    "Check `cli auth probe blinkit_seller_new -t <uuid>` before re-logging in."
                )
            await page.wait_for_timeout(2500)
        finally:
            await context.close()

    metrics = next((v for k, v in captured.items() if ep.SALES_METRICS_PATH in k), None)
    by_product = next((v for k, v in captured.items() if ep.SALES_BY_PRODUCT_PATH in k), None)
    if metrics is None or by_product is None:
        missing = [
            name for name, v in (("metrics", metrics), ("by_product", by_product)) if v is None
        ]
        raise RuntimeError(
            f"Sales Performance page loaded but didn't return: {', '.join(missing)}. "
            "The page's API shape may have changed."
        )

    daily = (metrics.get("data") or {}).get("sales_performance_histogram_metrics") or []
    products = (by_product.get("data") or {}).get("product_sales_performance") or []
    label = window_label[-1] if window_label else "Last 7 days"  # dashboard's own default
    logger.info(
        f"Seller-hub sales scraped — window:{label!r} daily buckets:{len(daily)} products:{len(products)}"
    )

    return {"histogram": daily, "products": products, "window_label": label}
