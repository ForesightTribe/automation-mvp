"""Blinkit position sourcing for the bid optimizer (D17 — MP-specific).

Scrapes consumer search for a keyword at a dark store, then finds THIS campaign's
product among the results and returns its sponsored rank. Ported from v1's
`_find_product_position`; the reused engine is `ad_campaigns.live_position`.

**MVP = always-live** (a fresh scrape every run). Tiering (report-API / DB-snapshot
for at-target keywords) is a deferred scale optimization — see the impl-doc backlog.
The bid loop (`bid.py`) never imports this; it calls `adapter.resolve_position`.
"""
from ad_campaigns.live_position import get_live_positions
from app.utils.logger import logger

# Generic category words that must NOT be used to match a specific product.
_STOP_WORDS = {
    "soda", "water", "drink", "pack", "combo", "with", "from", "and", "the", "zero",
    "sugar", "lime", "mint", "ginger", "cola", "product", "item", "type", "name",
}


def _match_keywords(product_names: list[str], brand_name: str | None) -> set[str]:
    """Meaningful (non-stopword, alpha, >3 char) tokens from the product names, with a
    brand-name fallback when names are PID-only stubs."""
    kws: set[str] = set()
    for name in product_names:
        if name.startswith("Product (ID:"):
            continue
        for word in name.lower().split():
            w = word.strip("(),:.-")
            if len(w) > 3 and w not in _STOP_WORDS and w.isalpha():
                kws.add(w)
    if not kws and brand_name:
        kws.add(brand_name.lower().strip())
    return kws


def match_position(results: list[dict], product_names: list[str],
                   product_pids: list[str] | None = None,
                   brand_name: str | None = None) -> tuple[float | None, bool, bool]:
    """Pure. Returns (sponsored_position | None, is_sponsored, product_found).
    Match priority: PID (definitive) → name tokens → brand fallback. Only a SPONSORED
    hit yields a position; an organic-only match returns (None, False, True) → skip."""
    if not results:
        return None, False, False

    pid_set = {str(p).strip() for p in (product_pids or []) if p}
    keywords = _match_keywords(product_names, brand_name)

    organic_match = None
    for item in results:
        item_pid = str(item.get("pid") or "").strip()
        item_lower = item["name"].lower()
        pid_match = bool(item_pid and pid_set and item_pid in pid_set)
        name_match = bool(keywords and any(kw in item_lower for kw in keywords))
        if pid_match or name_match:
            if item.get("is_ad"):
                return float(item["position"]), True, True
            organic_match = organic_match or item
    return (None, False, True) if organic_match is not None else (None, False, False)


async def resolve(keyword: str, lat: float, lon: float, *, product_names: list[str],
                  product_pids: list[str], brand_name: str | None) -> tuple[float | None, str]:
    """Scrape live positions and locate this campaign's product. Returns
    (position | None, source-string). None = not found / organic-only → skip the bid."""
    results = await get_live_positions(keyword, lat=lat, lon=lon)
    pos, is_sponsored, found = match_position(results, product_names, product_pids, brand_name)
    if pos is None:
        reason = "organic-only (not a sponsored ad)" if found else "product not in results"
        logger.info(f"[cm.bid] {keyword!r} @ ({lat},{lon}): {reason} ({len(results)} results) — skip")
        return None, reason
    logger.info(f"[cm.bid] {keyword!r} @ ({lat},{lon}): sponsored pos {pos} ({len(results)} results)")
    return pos, f"live({len(results)} results)"
