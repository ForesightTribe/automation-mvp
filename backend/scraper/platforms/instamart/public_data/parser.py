"""Instamart public search parser: raw scraper output → classified result.

Deliberately thin, and a sibling of blinkit/ and zepto/public_data/parser.py —
the shape it returns is what `scraper/public/` consumes, so the three must not
drift.

Classification uses the explicit `brand` field Instamart returns per item, so
own-brand vs competitor is exact and no name guessing is needed (same as Zepto;
better than Blinkit, which parses the name). Anything Instamart-shaped is
normalised in scraper.py before it gets here — `classify_products` is shared and
forbids platform logic, and `targeted.py` calls `provider.search()` without ever
calling `parse()`, so nothing done here would reach the own-SKU scrape.
"""
from typing import Any

from scraper.utils.search_result import classify_products


def parse(raw: dict) -> dict[str, Any]:
    cls = classify_products(
        raw.get("products") or [], raw["brand_slug"],
        raw.get("aliases"), raw.get("competitors"),
    )
    return {
        "provider": "instamart",
        "brand_slug": raw["brand_slug"],
        "keyword": raw["keyword"],
        "city": raw.get("city", ""),
        "zone": raw.get("zone", ""),
        "pincode": raw.get("pincode", ""),
        "lat": raw.get("lat"),
        "lon": raw.get("lon"),
        # Store-grain, like Zepto: the request binds by store id, and each
        # product carries the store that served it (`podId`), which is what the
        # listing rows store. This is the store that ANSWERED — usually the one
        # asked for, occasionally its secondary.
        "merchant_id": raw.get("merchant_id", ""),
        "total_results": raw.get("total_results") or len(cls["listings"]),
        "brand_rank": cls["brand_rank"],
        "brand_sov_pct": cls["brand_sov_pct"],
        "brand_product_count": cls["brand_product_count"],
        "listings": cls["listings"],
        "brand_products": cls["brand_products"],
        "competitors": cls["competitors"],
    }
