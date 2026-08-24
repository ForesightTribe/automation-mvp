"""
Is the search API usable right now?

Fires ONE search and reports. Costs a few seconds instead of discovering the
answer ten minutes into a 1h45m run.

Note the two endpoints have separate budgets: get_page can be perfectly healthy
while search is blocked, which is exactly what the discovery sweep caused.

Run from backend/:
    python -m scripts.zepto_check_rate_limit
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright

_BASE = "https://www.zepto.com"
_BFF = "https://bff-gateway.zepto.com"
_GP = "/lms/api/v2/get_page"
_SEARCH = "/user-search-service/api/v3/search"
_DROP = {"host", "content-length", "connection", "accept-encoding",
         ":method", ":path", ":authority", ":scheme"}

# Any real Bengaluru store will do; this one is stable.
STORE = "b1403534-cd6b-49d0-a7cd-ce20e6497768"   # BLR-RICHMOND TOWN
LAT, LNG = 12.9765944, 77.5992708


async def capture(page, part, nav, settle=8000):
    cap = {"h": None, "body": None}

    async def on_req(req):
        if part in req.url and cap["h"] is None:
            cap["h"] = dict(req.headers)
            try:
                cap["body"] = req.post_data
            except Exception:
                pass

    page.on("request", on_req)
    try:
        await nav()
        w = 0
        while cap["h"] is None and w < settle:
            await page.wait_for_timeout(250)
            w += 250
    except Exception:
        pass
    finally:
        page.remove_listener("request", on_req)
    if not cap["h"]:
        return {}, None
    return {k: v for k, v in cap["h"].items() if k.lower() not in _DROP}, cap["body"]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"))
        page = await ctx.new_page()

        gp, _ = await capture(page, _GP,
                              lambda: page.goto(_BASE, timeout=30000,
                                                wait_until="domcontentloaded"))
        print(f"get_page headers : {len(gp)}")

        # get_page health
        url = (f"{_BFF}{_GP}?latitude={LAT}&longitude={LNG}"
               f"&page_type=HOME&version=v2&show_new_eta_banner=true"
               f"&page_size=3&enforce_platform_type=WEB")
        try:
            r = await ctx.request.get(url, headers=gp, timeout=15000)
            ok_gp = r.status == 200 and bool(
                ((await r.json()).get("storeServiceableResponse") or {}).get("storeId"))
            print(f"get_page          : HTTP {r.status}  {'OK' if ok_gp else 'PROBLEM'}")
        except Exception as e:
            print(f"get_page          : ERROR {str(e)[:60]}")

        await page.wait_for_timeout(1500)
        se, raw = await capture(page, _SEARCH,
                                lambda: page.goto(f"{_BASE}/search?query=bread",
                                                  timeout=30000,
                                                  wait_until="domcontentloaded"),
                                settle=9000)
        print(f"search headers   : {len(se)}")
        if not se:
            print("\nVERDICT: could not capture search headers — try again shortly.")
            await b.close()
            return

        body = json.loads(raw) if raw else {"query": "bread", "pageNumber": 0,
                                            "mode": "SHOW_ALL_RESULTS"}
        body["query"] = "bread"
        body["pageNumber"] = 0
        h = dict(se)
        h["store_id"] = h["storeid"] = h["store_ids"] = STORE
        h["store_etas"] = json.dumps({STORE: -1})

        print()
        print("Firing ONE search...")
        try:
            r = await ctx.request.post(f"{_BFF}{_SEARCH}", headers=h,
                                       data=json.dumps(body), timeout=20000)
            n = 0
            if r.status == 200:
                d = await r.json()
                for w in d.get("layout", []):
                    if w.get("widgetId") == "PRODUCT_GRID":
                        n += len(w.get("data", {}).get("resolver", {})
                                 .get("data", {}).get("items") or [])
            print(f"  HTTP {r.status}   products returned: {n}")
            print()
            if r.status == 200 and n > 0:
                print("VERDICT: SEARCH IS WORKING — safe to start the run.")
            elif r.status == 200:
                print("VERDICT: HTTP 200 but ZERO products = still rate limited.")
                print("         Wait longer. A healthy search returns ~30.")
            else:
                print(f"VERDICT: HTTP {r.status} — still blocked. Wait longer.")
        except Exception as e:
            print(f"  ERROR {str(e)[:80]}")
            print("\nVERDICT: request failed — still blocked.")

        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
