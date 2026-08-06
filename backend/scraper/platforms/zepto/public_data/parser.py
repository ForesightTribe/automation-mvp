"""Zepto public search parser: raw scraper output → classified result.

Deliberately thin, and a sibling of blinkit/public_data/parser.py — the shape it
returns is what `scraper/public/` consumes, so the two must not drift.

Classification uses the explicit `brand` field Zepto returns per product (Q5), so
own-brand vs competitor is exact and no name guessing is needed. Emits `listings`
(the rows that become `search_listings`) plus the snapshot summary.

`classify_products` is shared by every marketplace and its docstring forbids
platform-specific logic. Anything Zepto-shaped is normalised in scraper.py before
it gets here — never inside the shared classifier.
"""
from typing import Any

from scraper.utils.search_result import classify_products


def parse(raw: dict) -> dict[str, Any]:
    # raw["competitors"] (from the orchestrator) whitelists which competitors to
    # store; absent (ad-hoc mode) → keep all.
    cls = classify_products(
        raw["products"], raw["brand_slug"], raw.get("aliases"), raw.get("competitors")
    )
    return {
        "provider": "zepto",
        "brand_slug": raw["brand_slug"],
        "keyword": raw["keyword"],
        "city": raw.get("city", ""),
        "zone": raw.get("zone", ""),
        "pincode": raw.get("pincode", ""),
        "lat": raw.get("lat"),
        "lon": raw.get("lon"),
        # Zepto is store-grain (Q4): each product carries its fulfilling store id.
        # Unlike Blinkit the merchant is also a scrape INPUT, because the request
        # binds by store header rather than by coordinate — see
        # endpoints.store_headers and the D8 note in docs/zepto.md.
        "merchant_id": raw.get("merchant_id", ""),
        "total_results": raw.get("total_results") or len(cls["listings"]),
        "brand_rank": cls["brand_rank"],
        "brand_sov_pct": cls["brand_sov_pct"],
        "brand_product_count": cls["brand_product_count"],
        # Per-product rows for storage (Phase 4):
        "listings": cls["listings"],
        # Summary views (also used by the CLI printout):
        "brand_products": cls["brand_products"],
        "competitors": cls["competitors"],
    }
