"""
Zepto NCR dark store discovery — 5-strategy pipeline (mirrors Blinkit TL approach).

Strategy 1: Pincode scan           → covers ~60% of stores
Strategy 2: Pincode + city name    → catches pincodes that returned nothing alone
Strategy 3: Grid scan              → covers remaining geography
Strategy 4: Autosuggestion scan    → Zepto-specific, catches named commercial areas
Strategy 5: Secondary store check  → collects hub/longtail stores from secondaryStoreIds

Output: zepto_ncr_dark_stores.xlsx
  Sheet 1 — primary_stores
  Sheet 2 — secondary_stores

Run from backend/:
    python scripts/zepto_ncr_dark_stores.py
"""
import asyncio
import sys
import time
from pathlib import Path

import httpx
import openpyxl
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.platforms.zepto.dark_store.endpoints import (
    NCR_BBOX,
    DELHI_NCR_PINCODES,
    AREA_PREFIXES,
)
from scraper.platforms.zepto.dark_store.locator import (
    make_grid,
    autocomplete,
    place_details,
    fetch_store_at,
)

# ── Pincode → city mapping ────────────────────────────────────────────────────

def _pincode_city(pincode: str) -> str:
    p = int(pincode)
    if 110001 <= p <= 110096:
        return "Delhi"
    if 201301 <= p <= 201318:
        return "Noida"
    if (122001 <= p <= 122018) or (122051 <= p <= 122052) or \
       (122101 <= p <= 122108) or p == 122413 or (122503 <= p <= 122508):
        return "Gurgaon"
    if 121001 <= p <= 121013:
        return "Faridabad"
    if (201001 <= p <= 201018) or p in (201102, 201103, 201204):
        return "Ghaziabad"
    return "Delhi"


# ── Session config (paste from your browser) ─────────────────────────────────

_COOKIES = [
    {"name": "_gcl_au",       "value": "1.1.639332164.1781704434",              "domain": ".zepto.com", "path": "/"},
    {"name": "_fbp",          "value": "fb.1.1781704434059.624013285257015660",  "domain": ".zepto.com", "path": "/"},
    {"name": "_ga",           "value": "GA1.1.1421371930.1781704435",            "domain": ".zepto.com", "path": "/"},
    {"name": "aws-waf-token", "value": (
        "b14e78dc-0917-428a-99e6-48c3f5713084:BQoAnNIjNOERAAAA:"
        "Iw3qJxtUzxdtz6m9fuesFwDYRdhNvwojDZiuxFm2LPIXo3ujokIiZMVU5ZzDRBgcsCBMVIs7CwSDcSQjMk"
        "l1d3pK6rYDziRJAfayKgovicCHGROBGqFop/CGyWB4LA9eK4yS4hPNm5SDTDXMENozXHPWXVUlw/bmBPk9"
        "TgAfLhWgKjDVfUWepEI7zn2GPdk8jg+nueRGBZOaHL1D6/FoGyuaWWOn5eiynHTYesMdeaD3we6NsM9F+O"
        "wbg9UnpwHL0CR7c8ojR1HNuLJGHgwCr/hVc5FW1BKUKSN+34eaUHYHzk/GEJKHfHos"
    ), "domain": ".zepto.com", "path": "/"},
]

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "app_sub_platform": "WEB",
    "app_version": "16.20.0",
    "appversion": "16.20.0",
    "auth_from_cookie": "true",
    "auth_revamp_flow": "v2",
    "compatible_components": (
        "EXTERNAL_COUPONS,BUNDLE,MULTI_SELLER_ENABLED,ROLLUPS,SCHEDULED_DELIVERY,HOMEPAGE_V2,"
        "NEW_ETA_BANNER,VERTICAL_FEED_PRODUCT_GRID,AUTOSUGGESTION_PAGE_ENABLED,AUTOSUGGESTION_PIP,"
        "AUTOSUGGESTION_AD_PIP,BOTTOM_NAV_FULL_ICON,COUPON_WIDGET_CART_REVAMP,DELIVERY_UPSELLING_WIDGET,"
        "MARKETPLACE_CATEGORY_GRID,NO_PLATFORM_CHECK_ENABLED_V2,SUPER_SAVER:1,SUPERSTORE_V1,PROMO_CASH:0,"
        "24X7_ENABLED_V1,TABBED_CAROUSEL_V2,HP_V4_FEED,WIDGET_BASED_ETA,PC_REVAMP_1,NO_COST_EMI_V1,"
        "PRE_SEARCH,ITEMISATION_ENABLED,ZEPTO_PASS:5,BACHAT_FOR_ALL,SAMPLING_UPSELL_CAMPAIGN,"
        "DISCOUNTED_ADDONS_ENABLED,UPSELL_COUPON_SS:0,ENABLE_FLOATING_CART_BUTTON,FASHION_REVAMP,"
        "WIDGET_RESTRUCTURE,MULTITAB_V2"
    ),
    "device_id":        "238c5b9c-64e6-4b22-bfd4-29ad21d9e4d0",
    "deviceid":         "238c5b9c-64e6-4b22-bfd4-29ad21d9e4d0",
    "marketplace_type": "SUPER_SAVER",
    "origin":           "https://www.zepto.com",
    "platform":         "WEB",
    "referer":          "https://www.zepto.com/",
    "sec-fetch-dest":   "empty",
    "sec-fetch-mode":   "cors",
    "sec-fetch-site":   "same-site",
    "session_id":       "8fb8f5c8-3f7f-47eb-8b00-9bb02b621f13",
    "sessionid":        "8fb8f5c8-3f7f-47eb-8b00-9bb02b621f13",
    "source":           "DIRECT",
    "store_etas":       "{}",
    "store_id":         "b4dc8d65-ed2e-4142-81b6-373982b13500",
    "store_ids":        "b4dc8d65-ed2e-4142-81b6-373982b13500",
    "storeid":          "b4dc8d65-ed2e-4142-81b6-373982b13500",
    "tenant":           "ZEPTO",
    "user-agent":       "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
    "x-csrf-secret":    "h_hSUmISaZ8",
    "x-xsrf-token":     "BTU6alYQnBgxnHZ8fqO8M:c-gJT0FRTohpKBO8NPbFjumwxg4.oPDHQRADyr9NllPDM7hg486YwRN4nLUs8Wez+5WiAP8",
}


# ── Nominatim reverse geocoding ───────────────────────────────────────────────

async def _reverse_geocode(lat: float, lng: float) -> dict:
    """Nominatim: lat/lng → pincode, area, city. Rate limited to 1 req/sec."""
    await asyncio.sleep(1.1)
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lng, "format": "json"},
                headers={"User-Agent": "zepto-ncr-dark-store-discovery/1.0"},
                timeout=10,
            )
            if r.status_code == 200:
                addr = r.json().get("address", {})
                return {
                    "pincode": addr.get("postcode", ""),
                    "area":    addr.get("suburb") or addr.get("neighbourhood") or addr.get("quarter") or addr.get("village") or "",
                    "city":    addr.get("city") or addr.get("town") or addr.get("state_district") or "",
                    "state":   addr.get("state", ""),
                }
    except Exception:
        pass
    return {"pincode": "", "area": "", "city": "", "state": ""}


# ── Shared helper: record a found store ──────────────────────────────────────

def _record(primary: dict, all_secondaries: set, s: dict, strategy: str,
            pincode: str = "", area: str = "", city: str = ""):
    for sec in s["secondary_store_ids"]:
        all_secondaries.add(sec)

    sid = s["store_id"]
    if sid not in primary:
        primary[sid] = {
            "store_id":            sid,
            "probe_lat":           s["probe_lat"],
            "probe_lng":           s["probe_lng"],
            "pincode":             pincode,
            "area":                area,
            "city":                city,
            "state":               "",
            "secondary_store_ids": "|".join(s["secondary_store_ids"]),
            "found_by":            strategy,
        }
        print(f"  [{strategy}] NEW store {sid}  pincode={pincode or '?'}  area={area or '?'}")
    else:
        # Enrich existing record with any new metadata
        rec = primary[sid]
        if not rec["pincode"] and pincode:
            rec["pincode"] = pincode
        if not rec["area"] and area:
            rec["area"] = area
        if not rec["city"] and city:
            rec["city"] = city
        if strategy not in rec["found_by"]:
            rec["found_by"] += f"+{strategy}"


# ── Strategy 1: Pincode scan ──────────────────────────────────────────────────

async def strategy_pincode(ctx, primary, all_secondaries, sem) -> set[str]:
    """Probe each NCR pincode using '{pincode} {location_name}' autocomplete query."""
    print(f"\n[Strategy 1] Pincode scan — {len(DELHI_NCR_PINCODES)} pincodes")
    failed_pincodes = set()

    async def _probe(pincode, location_name):
        query = f"{pincode} {location_name}"
        async with sem:
            suggestions = await autocomplete(query, ctx, _HEADERS)
        if not suggestions:
            failed_pincodes.add(pincode)
            return
        async with sem:
            det = await place_details(suggestions[0]["place_id"], ctx, _HEADERS)
        if not det:
            failed_pincodes.add(pincode)
            return
        async with sem:
            s = await fetch_store_at(det["lat"], det["lng"], ctx, _HEADERS)
        if not s:
            failed_pincodes.add(pincode)
            return
        _record(primary, all_secondaries, s,
                strategy="pincode",
                pincode=det.get("pincode") or pincode,
                area=location_name,
                city=det.get("city") or _pincode_city(pincode))

    await asyncio.gather(*[_probe(p, loc) for p, loc in DELHI_NCR_PINCODES.items()])
    print(f"[Strategy 1] Done — {len(failed_pincodes)} pincodes returned no store")
    return failed_pincodes


# ── Strategy 2: Pincode + city name (for misses from Strategy 1) ─────────────

async def strategy_pincode_city(ctx, primary, all_secondaries, sem, failed_pincodes: set):
    """Retry failed pincodes as '{pincode} {city}' query."""
    if not failed_pincodes:
        print("\n[Strategy 2] No failed pincodes to retry — skipping")
        return
    print(f"\n[Strategy 2] Pincode + city retry — {len(failed_pincodes)} pincodes")

    async def _probe(pincode):
        city = _pincode_city(pincode)
        location_name = DELHI_NCR_PINCODES.get(pincode, city)
        query = f"{pincode} {city}"
        async with sem:
            suggestions = await autocomplete(query, ctx, _HEADERS)
        if not suggestions:
            return
        async with sem:
            det = await place_details(suggestions[0]["place_id"], ctx, _HEADERS)
        if not det:
            return
        async with sem:
            s = await fetch_store_at(det["lat"], det["lng"], ctx, _HEADERS)
        if not s:
            return
        _record(primary, all_secondaries, s,
                strategy="pincode+city",
                pincode=det.get("pincode") or pincode,
                area=location_name,
                city=det.get("city") or city)

    await asyncio.gather(*[_probe(p) for p in failed_pincodes])
    print(f"[Strategy 2] Done")


# ── Strategy 3: Grid scan ─────────────────────────────────────────────────────

async def strategy_grid(ctx, primary, all_secondaries, sem):
    """1 km grid over full NCR bounding box."""
    coords = make_grid(**NCR_BBOX, step_km=1.0)
    print(f"\n[Strategy 3] Grid scan — {len(coords)} probe points (1 km step)")

    async def _probe(lat, lng):
        async with sem:
            s = await fetch_store_at(lat, lng, ctx, _HEADERS)
        if s:
            _record(primary, all_secondaries, s, strategy="grid")

    await asyncio.gather(*[_probe(lat, lng) for lat, lng in coords])
    print(f"[Strategy 3] Done")


# ── Strategy 4: Autosuggestion scan (Zepto-specific) ─────────────────────────

async def strategy_autosuggestion(ctx, primary, all_secondaries, sem):
    """Area name prefixes → all Zepto suggestions → place_details → store."""
    print(f"\n[Strategy 4] Autosuggestion scan — {len(AREA_PREFIXES)} prefixes")

    async def _probe_prefix(prefix):
        async with sem:
            suggestions = await autocomplete(prefix, ctx, _HEADERS)
        for sugg in suggestions:   # all suggestions, not just first
            async with sem:
                det = await place_details(sugg["place_id"], ctx, _HEADERS)
            if not det:
                continue
            async with sem:
                s = await fetch_store_at(det["lat"], det["lng"], ctx, _HEADERS)
            if s:
                _record(primary, all_secondaries, s,
                        strategy="autosuggestion",
                        pincode=det.get("pincode") or "",
                        area=sugg.get("description", ""),
                        city=det.get("city") or "")

    await asyncio.gather(*[_probe_prefix(p) for p in AREA_PREFIXES])
    print(f"[Strategy 4] Done")


# ── Strategy 5: Secondary store cross-check ───────────────────────────────────

def strategy_secondary(primary: dict, all_secondaries: set) -> list[str]:
    """Find secondary store IDs not discovered as a primary store."""
    secondary_only = sorted(all_secondaries - set(primary.keys()))
    print(f"\n[Strategy 5] Secondary check — {len(all_secondaries)} total secondary IDs, "
          f"{len(secondary_only)} not found as primary")
    return secondary_only


# ── Nominatim enrichment ──────────────────────────────────────────────────────

async def enrich_missing(primary: dict):
    missing = [v for v in primary.values() if not v["pincode"] or not v["area"]]
    if not missing:
        print("\nAll stores already have pincode + area — no Nominatim calls needed")
        return
    print(f"\nEnriching {len(missing)} stores via Nominatim (1 req/sec — takes ~{len(missing)} sec)...")
    for i, store in enumerate(missing, 1):
        geo = await _reverse_geocode(store["probe_lat"], store["probe_lng"])
        if not store["pincode"]:
            store["pincode"] = geo["pincode"]
        if not store["area"]:
            store["area"] = geo["area"]
        if not store["city"]:
            store["city"] = geo["city"]
        if not store["state"]:
            store["state"] = geo["state"]
        if i % 10 == 0:
            print(f"  Nominatim: {i}/{len(missing)} done")


# ── Excel output ──────────────────────────────────────────────────────────────

def save_excel(primary: dict, secondary_only: list[str], out_path: Path):
    wb = openpyxl.Workbook()

    # Sheet 1: primary stores (sorted by city then pincode)
    ws1 = wb.active
    ws1.title = "primary_stores"
    ws1.append([
        "store_id", "city", "state", "pincode", "area",
        "probe_lat", "probe_lng", "secondary_store_ids", "found_by",
    ])
    for s in sorted(primary.values(), key=lambda x: (x["city"], x["pincode"])):
        ws1.append([
            s["store_id"], s["city"], s["state"], s["pincode"], s["area"],
            s["probe_lat"], s["probe_lng"], s["secondary_store_ids"], s["found_by"],
        ])

    # Sheet 2: secondary-only stores
    ws2 = wb.create_sheet("secondary_stores")
    ws2.append(["store_id", "type"])
    for sid in secondary_only:
        ws2.append([sid, "longtail_hub"])

    wb.save(out_path)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    t0 = time.time()
    primary: dict = {}        # store_id → store record
    all_secondaries: set = set()
    sem = asyncio.Semaphore(10)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=_HEADERS["user-agent"])
        await context.add_cookies(_COOKIES)
        ctx = context.request

        # Sanity check before full run
        print("Sanity check probe...")
        from scraper.platforms.zepto.dark_store.locator import fetch_store_at as _f
        test = await _f(28.6785828, 77.191584, ctx, _HEADERS)
        if not test:
            print("ERROR: Sanity probe returned nothing — check cookies/headers and retry.")
            await browser.close()
            return
        print(f"OK — store {test['store_id']} is reachable\n")
        print("=" * 60)

        # Run strategies in order (each feeds into the same primary dict)
        failed = await strategy_pincode(ctx, primary, all_secondaries, sem)
        await strategy_pincode_city(ctx, primary, all_secondaries, sem, failed)
        await strategy_grid(ctx, primary, all_secondaries, sem)
        await strategy_autosuggestion(ctx, primary, all_secondaries, sem)

        await browser.close()

    secondary_only = strategy_secondary(primary, all_secondaries)

    await enrich_missing(primary)

    out = Path(__file__).parent.parent / "zepto_ncr_dark_stores.xlsx"
    save_excel(primary, secondary_only, out)

    elapsed = int(time.time() - t0)
    print(f"\n{'=' * 60}")
    print(f"Total unique primary stores : {len(primary)}")
    print(f"Secondary-only stores       : {len(secondary_only)}")
    print(f"Time taken                  : {elapsed // 60}m {elapsed % 60}s")
    print(f"Saved → {out}")


asyncio.run(main())
