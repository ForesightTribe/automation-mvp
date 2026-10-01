"""Blinkit seller-hub (seller.blinkit.com) — sales scrape.

Unlike scraper/platforms/blinkit/dashboard_data/seller/scraper.py (the OLD
partnersbiz.com dashboard), this CANNOT be a plain httpx client from OUTSIDE
the browser. This domain's Cloudflare bot management blocks a bare request
even with a live session's exact cookies/headers replayed — proven twice in
platform_auth/marketplaces/blinkit/seller_new.py (Phase B, 2026-09-30). So a
real browser has to open the page first, every time.

BUT once inside that authenticated page, an in-page fetch() to the sales
endpoints DOES work — corrected 2026-10-01 after two earlier false starts.
The first in-page fetch() attempt (against a DIFFERENT set of endpoints,
during auth development: app/config, app/feed, notifications, faq) failed
with "Missing required headers for AuthLevelRequired", and that finding was
wrongly generalized to "fetch never works on this domain." Re-tested
specifically against sales/performance/metrics with the real SPA's headers
captured live: four headers a hand-built fetch doesn't normally send are
missing — `access_token` (as a HEADER, not just the cookie), `app_client`,
`x-api-key`, `x-gr-seller-id`. Add those four (the first and last are read
live from cookies each run; the middle two are static values baked into the
SPA's own JS bundle) and the identical fetch returns 200 with real data.

Verified live (Sereko, 2026-10-01): a 29-city sweep via this fetch path hit
29/29 successes in ~6 seconds total, vs. the UI-click-driven version's
25/29 in ~5-6 minutes (DOM text matching, dropdown scroll/close races, and a
rate-limit wall that only showed up on the slow click path, never on fast
back-to-back fetches). So city/category breakdowns now go through fetch()
too, same as the base sales/by-product calls always effectively have — the
original UI-click code for Cities/Business-categories has been removed.

The credential is the ON-DISK PERSISTENT PROFILE (seller_new.profile_dir), not
a token — `ensure()`'s storage_state is explicitly NOT a complete credential
for this domain (see seller_new.py's AuthSession docstring), so this module
never touches it. It only needs the session's EMAIL, to find the same profile
directory seller_new.py already logged into, and reads the live access_token/
seller_id straight off that profile's own cookies once the page is open.
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
# Static value from the SPA's own JS bundle, captured live alongside a real
# request (2026-10-01) — not session- or account-specific, unlike
# access_token/x-gr-seller-id below, which ARE and must come from cookies.
_X_API_KEY = "0d0b54c3-8d3a-48fc-a433-1648b22e7e8d"


async def scrape_sales(email: str, with_city: bool = True, with_category: bool = True) -> dict:
    """One page visit to Sales Performance, captures the SPA's own calls to
    the metrics (day-grain, all products) and products/performance (item-
    grain, window total) endpoints. Returns the raw API payloads; parsing
    happens in parser.py.

    Only the dashboard's DEFAULT window ("Last 7 days") is captured — the
    UI's time-range dropdown was not reliably clickable headless in testing,
    so a scheduled daily run naturally builds history one default-window
    scrape at a time rather than trying to sweep every preset each run.

    `with_city`/`with_category` additionally fetch every city's / business
    category's own day-grain histogram (`by_city`/`by_category` in the return
    value) via direct in-page fetch() calls — see module docstring for why
    that's fast and reliable now, not UI-driven.
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
        if (
            ep.SALES_METRICS_PATH not in url
            and ep.SALES_BY_PRODUCT_PATH not in url
            and ep.SALES_FILTERS_PATH not in url
        ):
            return
        try:
            body = await resp.json()
        except Exception:
            return
        captured[url] = body

    by_city: dict[str, list] = {}
    by_category: dict[str, list] = {}

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

            # Snapshot the baseline (unfiltered) responses now — the fetch
            # calls below hit the SAME endpoint URLs with a filter added, and
            # the listener above captures by URL alone, so reading `captured`
            # back after those calls would return the LAST filtered result
            # instead of the real unfiltered one (caught live, pre-fetch-
            # rewrite: national total read back as Rs 16,845 instead of
            # Rs 1,17,568 — same risk applies here, so snapshot first).
            metrics = next((v for k, v in captured.items() if ep.SALES_METRICS_PATH in k), None)
            by_product = next((v for k, v in captured.items() if ep.SALES_BY_PRODUCT_PATH in k), None)

            filters_body = next(
                (v for k, v in captured.items() if ep.SALES_FILTERS_PATH in k), None
            )

            if with_city or with_category:
                headers = await _auth_headers(context)

            if with_city:
                cities = []
                if filters_body:
                    for f in (filters_body.get("data") or {}).get("filters") or []:
                        if f.get("key") == "city_filter":
                            cities = [c for c in f.get("values") or [] if isinstance(c, str)]
                            break
                by_city = await _fetch_by_city(page, headers, cities)

            if with_category:
                categories: list[tuple[int, str]] = []
                if filters_body:
                    for f in (filters_body.get("data") or {}).get("filters") or []:
                        if f.get("key") == "business_category_filter":
                            categories = [
                                (c["category_id"], c["category_name"])
                                for c in f.get("values") or []
                                if isinstance(c, dict) and "category_id" in c
                            ]
                            break
                by_category = await _fetch_by_category(page, headers, categories)
        finally:
            await context.close()

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
        f"Seller-hub sales scraped — window:{label!r} daily buckets:{len(daily)} "
        f"products:{len(products)} cities:{len(by_city)} categories:{len(by_category)}"
    )

    return {
        "histogram": daily,
        "products": products,
        "window_label": label,
        "by_city": by_city,
        "by_category": by_category,
    }


async def _auth_headers(context) -> dict:
    """The 4 headers a hand-built fetch() needs beyond the auto-sent cookies
    — see module docstring. access_token/seller_id are read live off this
    run's own cookies, never hardcoded (they rotate per login)."""
    cookies = {c["name"]: c["value"] for c in await context.cookies()}
    access_token = cookies.get("access_token")
    seller_id = cookies.get("seller_id")
    if not access_token or not seller_id:
        raise RuntimeError(
            "Missing access_token/seller_id cookie — session may be dead. "
            "Check `cli auth probe blinkit_seller_new -t <uuid>` before re-logging in."
        )
    return {
        "access_token": access_token,
        "app_client": "seller-dashboard-web",
        "x-api-key": _X_API_KEY,
        "x-gr-seller-id": seller_id,
    }


async def _fetch_json(page, path: str, body: dict, headers: dict) -> dict:
    """POST to a seller-hub endpoint via in-page fetch() — runs inside the
    page so it shares its origin, cookies and TLS/connection fingerprint
    (the thing Cloudflare actually gates on; see module docstring)."""
    result = await page.evaluate(
        """async ({path, body, headers}) => {
            const resp = await fetch(path, {
                method: "POST",
                headers: {"Content-Type": "application/json", ...headers},
                credentials: "include",
                body: JSON.stringify(body),
            });
            const text = await resp.text();
            return {status: resp.status, text};
        }""",
        {"path": path, "body": body, "headers": headers},
    )
    if result["status"] != 200:
        raise RuntimeError(f"{path} returned {result['status']}: {result['text'][:200]}")
    return json.loads(result["text"])


async def _fetch_by_city(page, headers: dict, cities: list[str]) -> dict[str, list]:
    """One fetch() per city to the metrics endpoint with `city_filter:
    [<city>]`. The response carries no city field of its own — verified live
    (Sereko, 2026-10-01): filtering to "Bengaluru" dropped the day totals
    from Rs 1,17,568/264u (all cities) to Rs 24,339/57u, and the 7-day
    histogram summed back to that same filtered total — so each row is
    tagged with whichever city was REQUESTED, same as Zepto's per-city scrape.
    Best-effort: one city's failure is logged and skipped."""
    out: dict[str, list] = {}
    for city in cities:
        try:
            data = await _fetch_json(
                page,
                f"/{ep.SALES_METRICS_PATH}",
                {"filters": {"time_range_filter": "Last 7 days", "city_filter": [city]}},
                headers,
            )
            out[city] = (data.get("data") or {}).get("sales_performance_histogram_metrics") or []
        except Exception as e:                                       # noqa: BLE001
            logger.warning(f"Seller-hub sales-by-city: {city!r} failed, skipping: {e}")
    return out


async def _fetch_by_category(page, headers: dict, categories: list[tuple[int, str]]) -> dict[str, list]:
    """Same as `_fetch_by_city` but `business_category_filter: [<category_id>]`
    — verified live: category_id 4766 ("Beauty - Face Care") gave
    Rs 1,14,968/259u, matching the by-product table's own category breakdown
    for the same category exactly (two independent sources agreeing)."""
    out: dict[str, list] = {}
    for category_id, category_name in categories:
        try:
            data = await _fetch_json(
                page,
                f"/{ep.SALES_METRICS_PATH}",
                {"filters": {"time_range_filter": "Last 7 days", "business_category_filter": [category_id]}},
                headers,
            )
            out[category_name] = (data.get("data") or {}).get("sales_performance_histogram_metrics") or []
        except Exception as e:                                       # noqa: BLE001
            logger.warning(f"Seller-hub sales-by-category: {category_name!r} failed, skipping: {e}")
    return out
