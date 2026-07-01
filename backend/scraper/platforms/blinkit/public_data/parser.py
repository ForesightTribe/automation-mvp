"""Blinkit public search parser: raw scraper output → classified result.

Classification uses the explicit `brand` field Blinkit returns per product, so
own-brand vs competitor is exact (no name guessing). Emits `listings` (the rows
that become `search_listings`) plus the snapshot summary.
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
        "provider": "blinkit",
        "brand_slug": raw["brand_slug"],
        "keyword": raw["keyword"],
        "city": raw.get("city", ""),
        "zone": raw.get("zone", ""),
        "pincode": raw.get("pincode", ""),
        "lat": raw.get("lat"),
        "lon": raw.get("lon"),
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
