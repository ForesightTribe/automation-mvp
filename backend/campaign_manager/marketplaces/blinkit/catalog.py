"""Our catalogue at one Blinkit dark store, with availability — the bid engine's stock check.

A BRAND search at a store lists every product we sell there, sold-out ones included, each
carrying `is_sold_out` + `inventory` in its add-to-cart block (verified against Dobra
2026-09-17: e.g. "Pop Goli Soda - Apple Mojito" came back `inventory 0`). It reuses the public
scraper's search, which already parses that block; the bid engine's own position parser does
not read it and does not need to.

The product ids are the SAME id space as a campaign's product list and as the consumer
search's `identity.id` — verified in the same recon — so the join to a campaign is exact.

⚠️ The brand search does not stop at our brand. Blinkit pads it with "similar" products, and
following that tail walked 219 products (soda water, baking soda …) and hit HTTP 429 in recon.
The read is capped at the client's `brand_cap`, and a capped or 429-truncated read may not have
reached every product we sell. `complete` records whether it did — see `summarise`.
"""

# How many trailing results must be OTHER brands before a capped read counts as having seen
# all of ours. A single foreign product proves nothing: in recon a competitor's tapioca chips
# sat between our own combos. A run of them at the end means our brand's block is over.
TAIL_OF_OTHER_BRANDS = 10


def own_names(names) -> set[str]:
    """Normalise brand names for matching the `brand` field on a product."""
    return {n.strip().lower() for n in (names or ()) if n and n.strip()}


def _is_own(product: dict, names: set[str]) -> bool:
    return (product.get("brand") or "").strip().lower() in names


def summarise(res: dict, cap: int, names: set[str]) -> dict:
    """Pure. A public-scraper search result → our products at the store, and whether we saw
    them all.

    Returns `{"ok": False, "error": …}` when the read tells us nothing usable — including a
    search that returned NONE of our products, which is far likelier to be our query failing
    than a store that sells none of them. Otherwise
    `{"ok": True, "complete": bool, "served_by": str, "products": [{pid, name, in_stock,
    inventory}]}`.

    `complete` is True when either:
      - the search ran out of results before the cap, cleanly (no error cut it short), or
      - the last `TAIL_OF_OTHER_BRANDS` results are all other brands — our block has ended.
    """
    if not res or not res.get("ok"):
        return {"ok": False, "error": (res or {}).get("error") or "the brand search failed"}
    products = res.get("products") or []
    ours = [p for p in products if _is_own(p, names) and p.get("product_id")]
    if not ours:
        return {"ok": False, "error": "the brand search returned none of our products"}

    ran_out = len(products) < cap and not res.get("error")
    tail = products[-TAIL_OF_OTHER_BRANDS:]
    moved_on = len(tail) == TAIL_OF_OTHER_BRANDS and not any(_is_own(p, names) for p in tail)
    return {
        "ok": True,
        "complete": bool(ran_out or moved_on),
        "served_by": res.get("merchant_id") or "",
        "products": [{"pid": str(p["product_id"]), "name": p.get("name") or "",
                      "in_stock": bool(p.get("in_stock")), "inventory": p.get("inventory")}
                     for p in ours],
    }


async def read(session: dict, query: str, lat: float, lon: float, *,
               cap: int, names) -> dict:
    """One capped brand search at the store serving (lat, lon), summarised. A READ.

    Runs on the bid engine's already-open consumer session (it carries the `page` + `headers`
    the public search needs); the store is chosen by the lat/lon headers, as for positions."""
    from scraper.platforms.blinkit.public_data import scraper as public_search

    res = await public_search.search(session, query, cap, lat=lat, lon=lon,
                                     follow_similarity=True, distinct_ad_slots=False)
    return summarise(res, cap, own_names(names))
