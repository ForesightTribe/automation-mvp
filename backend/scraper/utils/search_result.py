import re
from typing import Any


HEADERS_COMMON = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://blinkit.com/",
}


def norm_price(raw: str) -> float:
    if not raw:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", str(raw).replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def brand_in(name: str, brand_slug: str, aliases: list[str] | None = None) -> bool:
    """Return True if name contains the brand slug or any of its aliases."""
    terms = aliases if aliases else [brand_slug.lower()]
    return any(t in name.lower() for t in terms)


def dig(obj: Any, *keys: str) -> Any:
    """Safely traverse nested dicts by key path."""
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
        else:
            return None
    return obj


def dig_list(obj: Any, keys: list[str]) -> list:
    """Return the first list found by recursively searching obj for any of the given keys."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                result = dig_list(obj[k], keys)
                if result:
                    return result
    return []


def build_result(
    provider: str,
    brand_slug: str,
    keyword: str,
    products: list[dict],
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """
    Classify a flat list of {name, price, position, in_stock} products into
    brand vs competitors and return a structured search result.

    Used by all three platform scrapers — do not add platform-specific logic here.
    """
    brand_products: list[dict] = []
    comp_map: dict[str, dict] = {}

    for p in products:
        name = p.get("name", "")
        if brand_in(name, brand_slug, aliases):
            brand_products.append({**p, "is_brand": True})
        else:
            words = name.split()
            comp = " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "Unknown")
            entry = comp_map.setdefault(comp, {"name": comp, "count": 0, "positions": []})
            entry["count"] += 1
            if p.get("position"):
                entry["positions"].append(p["position"])

    best_rank = min(
        (p["position"] for p in brand_products if p.get("position")), default=None
    )
    brand_sov = round(len(brand_products) / max(len(products), 1) * 100, 1) if products else 0.0

    total_comp_count = max(sum(v["count"] for v in comp_map.values()), 1)
    competitors = [
        {
            "name": v["name"],
            "count_in_results": v["count"],
            "best_position": min(v["positions"]) if v["positions"] else None,
            "share_of_results": round(v["count"] / total_comp_count * 100, 1),
        }
        for v in sorted(comp_map.values(), key=lambda x: x["count"], reverse=True)[:8]
    ]

    return {
        "provider": provider,
        "brand_slug": brand_slug,
        "keyword": keyword,
        "total_results": len(products),
        "brand_rank": best_rank,
        "brand_product_count": len(brand_products),
        "brand_sov_pct": brand_sov,
        "brand_products": brand_products[:5],
        "competitors": competitors,
        "all_products": products[:20],
    }


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "unknown"


def _first_words(name: str, n: int = 2) -> str:
    words = (name or "").split()
    return " ".join(words[:n]) if words else "Unknown"


def discount_pct(price: Any, mrp: Any) -> float | None:
    """Discount % off MRP. None when prices are missing/incoherent."""
    try:
        price = float(price)
        mrp = float(mrp)
    except (TypeError, ValueError):
        return None
    if mrp <= 0 or price <= 0 or price > mrp:
        return None
    return round((mrp - price) / mrp * 100, 1)


def classify_products(
    products: list[dict],
    brand_slug: str,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """Classify a list of product dicts into own-brand vs competitors.

    Uses each product's explicit ``brand`` field when present (e.g. Blinkit),
    falling back to a name match otherwise. Enriches every product with
    ``is_brand``, a normalized ``brand_slug``, and ``discount_pct`` — the rows
    that become ``search_listings``. Also returns the snapshot-level summary
    (rank, SoV, counts) and a grouped competitor view for display.
    """
    listings: list[dict] = []
    own: list[dict] = []
    comp_map: dict[str, dict] = {}

    for p in products:
        raw_brand = (p.get("brand") or "").strip()
        match_text = raw_brand or p.get("name", "")
        is_brand = brand_in(match_text, brand_slug, aliases)
        if is_brand:
            norm_slug = brand_slug
            comp_name = raw_brand or brand_slug
        else:
            comp_name = raw_brand or _first_words(p.get("name", ""))
            norm_slug = slugify(comp_name)

        listing = {
            **p,
            "is_brand": is_brand,
            "brand_slug": norm_slug,
            "discount_pct": discount_pct(p.get("price"), p.get("mrp")),
        }
        listings.append(listing)

        if is_brand:
            own.append(listing)
        else:
            entry = comp_map.setdefault(
                norm_slug,
                {"name": comp_name, "brand_slug": norm_slug, "count_in_results": 0, "positions": []},
            )
            entry["count_in_results"] += 1
            if listing.get("position"):
                entry["positions"].append(listing["position"])

    best_rank = min((l["position"] for l in own if l.get("position")), default=None)
    brand_sov = round(len(own) / len(listings) * 100, 1) if listings else 0.0

    competitors = sorted(comp_map.values(), key=lambda x: x["count_in_results"], reverse=True)
    for c in competitors:
        c["best_position"] = min(c["positions"]) if c["positions"] else None
        del c["positions"]

    return {
        "listings": listings,
        "brand_products": own,
        "competitors": competitors,
        "brand_rank": best_rank,
        "brand_sov_pct": brand_sov,
        "brand_product_count": len(own),
    }
