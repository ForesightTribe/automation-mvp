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


# Combos / multipacks are stocked selectively, so they must be analysed apart from
# singular main SKUs (their low distribution is by design, not a gap). Blinkit names
# them explicitly: "- Pack of N", "… + … Combo", "Buy N Get 1 Free".
_COMBO_RE = re.compile(r"(pack of|combo|buy\s*\d+\s*get|\s\+\s)", re.IGNORECASE)


def is_combo_name(name: str) -> bool:
    """True if a product name marks it as a combo/multipack (vs a single main SKU)."""
    return bool(_COMBO_RE.search(name or ""))


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
    competitors: list[tuple[str, list[str]]] | None = None,
) -> dict[str, Any]:
    """Classify a list of product dicts into own-brand vs competitors.

    Uses each product's explicit ``brand`` field when present (e.g. Blinkit),
    falling back to a name match. Enriches every product with ``is_brand``, a
    normalized ``brand_slug``, and ``discount_pct``.

    ``competitors`` is the whitelist of (slug, aliases) to KEEP as listing rows
    (own brand is always kept). When given, only own + declared competitors are
    returned as ``listings`` — everything else is still counted for rank/SoV but
    not stored. When ``None`` (ad-hoc mode), every product is kept.

    Rank and SoV are always computed over the FULL result page, not the filtered
    subset.
    """
    keep = competitors  # None = keep all
    all_rows: list[dict] = []
    own: list[dict] = []

    for p in products:
        raw_brand = (p.get("brand") or "").strip()
        match_text = raw_brand or p.get("name", "")
        is_brand = brand_in(match_text, brand_slug, aliases)
        if is_brand:
            norm_slug, comp_name = brand_slug, raw_brand or brand_slug
        else:
            comp_name = raw_brand or _first_words(p.get("name", ""))
            norm_slug = slugify(comp_name)

        row = {
            **p,
            "is_brand": is_brand,
            "brand_slug": norm_slug,
            "_comp_name": comp_name,
            "discount_pct": discount_pct(p.get("price"), p.get("mrp")),
        }
        all_rows.append(row)
        if is_brand:
            own.append(row)

    # Metrics over the full page (before filtering).
    best_rank = min((r["position"] for r in own if r.get("position")), default=None)
    brand_sov = round(len(own) / len(all_rows) * 100, 1) if all_rows else 0.0

    # Match on the slugified form so how you write the config (e.g. "Bombay Banta",
    # "bombay banta", "bombay-banta") doesn't matter — all normalize to the same slug.
    keep_slugs = {slugify(s) for s, _ in keep} if keep is not None else set()

    def _keep(row: dict) -> bool:
        if row["is_brand"] or keep is None:
            return True
        if row["brand_slug"] in keep_slugs:
            return True
        text = row.get("brand") or row.get("name", "")
        return any(al and brand_in(text, slug, al) for slug, al in keep)

    listings = [r for r in all_rows if _keep(r)]

    comp_map: dict[str, dict] = {}
    for r in listings:
        if r["is_brand"]:
            continue
        entry = comp_map.setdefault(
            r["brand_slug"],
            {"name": r["_comp_name"], "brand_slug": r["brand_slug"], "count_in_results": 0, "positions": []},
        )
        entry["count_in_results"] += 1
        if r.get("position"):
            entry["positions"].append(r["position"])

    competitors_out = sorted(comp_map.values(), key=lambda x: x["count_in_results"], reverse=True)
    for c in competitors_out:
        c["best_position"] = min(c["positions"]) if c["positions"] else None
        del c["positions"]

    for r in listings:
        r.pop("_comp_name", None)  # internal only

    return {
        "listings": listings,
        "brand_products": own,
        "competitors": competitors_out,
        "brand_rank": best_rank,
        "brand_sov_pct": brand_sov,
        "brand_product_count": len(own),
    }
