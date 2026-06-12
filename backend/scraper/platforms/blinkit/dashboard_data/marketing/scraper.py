import asyncio
import json
from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))
from playwright.async_api import async_playwright
from scraper.platforms.blinkit.dashboard_data.marketing import endpoints as ep
from scraper.utils.browser import create_browser_context, write_blocker
from app.utils.logger import logger


async def scrape(storage_state: dict) -> dict:
    async with async_playwright() as p:
        browser, context = await create_browser_context(p, headless=True, storage_state=storage_state)

        idb_data = storage_state.get("indexedDB", [])
        if idb_data:
            await _inject_firebase_idb(context, idb_data)
        else:
            logger.warning("No IndexedDB data in session — scrape may fail. Re-login recommended.")

        await context.route("**/*", write_blocker)

        try:
            page = await context.new_page()
            campaigns, sov, summary = await _scrape_campaigns_page(page)
            collections = await _scrape_brand_collections_page(page)
            plans = await _scrape_visibility_plans_page(page)
            return {
                "campaigns": campaigns,
                "sponsored_sov": sov,
                "performance_summary": summary,
                "brand_collections": collections,
                "visibility_plans": plans,
            }
        finally:
            await browser.close()


async def _inject_firebase_idb(context, idb_data: list) -> None:
    # Pre-populate IndexedDB before any page JS runs so Firebase SDK finds the refresh token.
    idb_json = json.dumps(idb_data)
    await context.add_init_script(f"""(function() {{
        var IDB_DATA = {idb_json};
        if (!IDB_DATA || !IDB_DATA.length) return;
        var req = indexedDB.open('firebaseLocalStorageDb', 1);
        req.onupgradeneeded = function(e) {{
            var db = e.target.result;
            if (!db.objectStoreNames.contains('firebaseLocalStorage'))
                db.createObjectStore('firebaseLocalStorage', {{keyPath: 'fbase_key'}});
        }};
        req.onsuccess = function(e) {{
            var db = e.target.result;
            var tx = db.transaction('firebaseLocalStorage', 'readwrite');
            var store = tx.objectStore('firebaseLocalStorage');
            IDB_DATA.forEach(function(item) {{ store.put(item); }});
        }};
    }})();""")
    logger.info(f"IndexedDB injection: {len(idb_data)} Firebase items")


def _date_range() -> tuple[str, str]:
    today = datetime.now(_IST)
    from_date = today - timedelta(days=90)
    return (
        f"{from_date.month}/{from_date.day}/{from_date.year}",
        f"{today.month}/{today.day}/{today.year}",
    )


async def _scroll_to_bottom(page) -> None:
    await page.evaluate("""async () => {
        await new Promise((resolve) => {
            let lastHeight = 0;
            const step = setInterval(() => {
                window.scrollBy(0, 600);
                const h = document.documentElement.scrollHeight;
                if (h === lastHeight) { clearInterval(step); resolve(); }
                lastHeight = h;
            }, 300);
        });
    }""")


async def _scrape_campaigns_page(page) -> tuple[list, list, dict]:
    logger.info("Scraping campaigns page...")
    captured = {"campaigns": None, "sov": None, "summary": None}

    async def on_response(response):
        url = response.url
        try:
            if ep.CAMPAIGNS_API in url and captured["campaigns"] is None:
                data = await response.json()
                if data.get("status"):
                    captured["campaigns"] = data["data"]["campaigns"]
                    logger.info(f"Captured {len(captured['campaigns'])} campaigns")
            elif ep.SPONSORED_SOV_API in url and captured["sov"] is None:
                data = await response.json()
                if data.get("status"):
                    captured["sov"] = data["data"]["sponsored_sov"]
                    logger.info(f"Captured {len(captured['sov'])} SOV keywords")
            elif ep.PERFORMANCE_SUMMARY_API in url and captured["summary"] is None:
                data = await response.json()
                if data.get("status"):
                    captured["summary"] = data["data"]
                    logger.info("Captured performance summary")
        except Exception as e:
            logger.warning(f"Response parse error for {url}: {e}")

    page.on("response", on_response)

    await page.goto(f"{ep.BASE_URL}{ep.CAMPAIGNS_PAGE}", wait_until="networkidle", timeout=60_000)

    if "/diy/" not in page.url:
        page.remove_listener("response", on_response)
        raise RuntimeError(f"Session expired — redirected to {page.url}")

    await _scroll_to_bottom(page)
    await asyncio.sleep(2)
    page.remove_listener("response", on_response)

    return (
        captured["campaigns"] or [],
        captured["sov"] or [],
        captured["summary"] or {},
    )


async def _scrape_brand_collections_page(page) -> list:
    logger.info("Scraping brand collections page...")
    captured = {"collections": None}

    async def on_response(response):
        if ep.BRAND_COLLECTIONS_API in response.url and captured["collections"] is None:
            try:
                data = await response.json()
                if data.get("status"):
                    captured["collections"] = data["data"]["collections"]
                    logger.info(f"Captured {len(captured['collections'])} brand collections")
            except Exception as e:
                logger.warning(f"Brand collections response parse error: {e}")

    page.on("response", on_response)

    await page.goto(f"{ep.BASE_URL}{ep.BRAND_COLLECTIONS_PAGE}", wait_until="networkidle", timeout=60_000)

    if "/diy/" not in page.url:
        page.remove_listener("response", on_response)
        raise RuntimeError(f"Session expired — redirected to {page.url}")

    await _scroll_to_bottom(page)
    await asyncio.sleep(2)
    page.remove_listener("response", on_response)

    return captured["collections"] or []


async def _scrape_visibility_plans_page(page) -> list:
    logger.info("Scraping visibility plans page...")
    captured = {"plans": None}

    async def on_response(response):
        if ep.VISIBILITY_PLANS_API in response.url and captured["plans"] is None:
            try:
                data = await response.json()
                if data.get("status"):
                    captured["plans"] = data["data"]
                    logger.info(f"Captured {len(captured['plans'])} visibility plans")
            except Exception as e:
                logger.warning(f"Visibility plans response parse error: {e}")

    page.on("response", on_response)

    await page.goto(f"{ep.BASE_URL}{ep.VISIBILITY_PLANS_PAGE}", wait_until="networkidle", timeout=60_000)

    if "/diy/" not in page.url:
        page.remove_listener("response", on_response)
        raise RuntimeError(f"Session expired — redirected to {page.url}")

    await _scroll_to_bottom(page)
    await asyncio.sleep(2)
    page.remove_listener("response", on_response)

    return captured["plans"] or []
