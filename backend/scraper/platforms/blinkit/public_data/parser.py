from typing import Any

from scraper.utils.search_result import build_result


def parse(raw: dict) -> dict[str, Any]:
    result = build_result(
        provider="blinkit",
        brand_slug=raw["brand_slug"],
        keyword=raw["keyword"],
        products=raw["products"],
        aliases=raw.get("aliases"),
    )
    result.update({
        "city": raw["city"],
        "zone": raw["zone"],
        "pincode": raw["pincode"],
        "lat": raw["lat"],
        "lon": raw["lon"],
    })
    return result
