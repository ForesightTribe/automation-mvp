"""Our catalogue at one Zepto store — the bid engine's stock check (C6).

A BRAND search at a store lists the products of ours that store can sell right now. Unlike
Blinkit's, it does NOT list sold-out ones: Zepto hides them from search entirely (1,495 own-SKU
rows from the brand search across 165 stores, 1-9 Brik Oven products per store, and not one
flagged `outOfStock`; the keyword search the same — 0 sold-out in 6,073 rows). So on Zepto,
"not in the brand search" IS the stock-out signal, and the read has to be allowed to say it:

  * a product that came back is available (or, if Zepto ever does flag one, it is not);
  * a campaign product that did NOT come back, from a read that saw the whole brand, is not
    sellable at that store — `coverage.eligibility` reads that as NOT_LISTED, which is exactly
    the answer the bid engine needs ("don't raise here, try the next store").

That is also why a search returning NONE of our products is an answer here (the store has
nothing of ours right now), not an error as it is on Blinkit. Only a search that returned
nothing at all, or failed, tells us nothing.

The ids are Zepto's `variant_id` — the same id space as a campaign's `product_variant_id`
(`adapter.read_products`), so the join to a campaign is exact.
"""

# How many trailing results must be OTHER brands before a capped read counts as having seen
# all of ours — the same rule as Blinkit's (`blinkit/catalog.py`).
TAIL_OF_OTHER_BRANDS = 10


def own_names(names) -> set[str]:
    return {n.strip().lower() for n in (names or ()) if n and n.strip()}


def _is_own(product: dict, names: set[str]) -> bool:
    """Brand field first, then the name — Zepto's `brand` is usually set, but a product
    without one is still ours if our brand name is in its title (`search_result.brand_in`)."""
    text = ((product.get("brand") or "").strip() or product.get("name") or "").lower()
    return any(n in text for n in names)


def summarise(res: dict, cap: int, names: set[str]) -> dict:
    """Pure. A public-scraper search result → our products at the store, and whether we saw
    them all. Same shape as Blinkit's (`base.read_store_catalog`)."""
    if not res or not res.get("ok"):
        return {"ok": False, "error": (res or {}).get("error") or "the brand search failed"}
    products = res.get("products") or []
    if not products:
        return {"ok": False, "error": "the brand search came back empty, so it says nothing "
                                      "about stock"}
    ours = [p for p in products if _is_own(p, names) and p.get("variant_id")]
    ran_out = len(products) < cap and not res.get("error")
    tail = products[-TAIL_OF_OTHER_BRANDS:]
    moved_on = len(tail) == TAIL_OF_OTHER_BRANDS and not any(_is_own(p, names) for p in tail)
    return {
        "ok": True,
        "complete": bool(ran_out or moved_on),
        "served_by": res.get("merchant_id") or "",
        "products": [{"pid": str(p["variant_id"]), "name": p.get("name") or "",
                      "in_stock": p.get("in_stock") is not False,
                      "inventory": p.get("inventory")}
                     for p in ours],
    }


async def read(session: dict, query: str, lat: float, lon: float, *, cap: int, names,
               merchant_id: str | None = None) -> dict:
    """One capped brand search at one store, summarised. A READ, on the bid engine's open
    position session.

    `merchant_id` binds the search to the store. Without it the scraper resolves the
    coordinate through `get_page`, a separate and much scarcer allowance — every catalogue
    store has an id, so the engine always passes one."""
    from scraper.platforms.zepto.public_data import scraper as zs

    res = await zs.search(session, query, cap, lat=lat, lon=lon, merchant_id=merchant_id,
                          distinct_ad_slots=False)
    return summarise(res, cap, own_names(names))
