"""Product families — singles and their multipacks counted as one product.

Why this sheet exists: catalogues migrate. A flavour sold as a single last month
may be sold as a 2-pack this month under a new product id, and per-product
numbers then show the single collapsing and a new product appearing — which
reads as a brand losing shelf when nothing of the sort happened.

Two rules do the work:

1. **This sheet always looks at every product, singles and multipacks alike**,
   whatever `--kind` the rest of the report is using. Rolling the two together is
   the entire point, so honouring a `main`-only filter here would defeat it.
2. **Multi-flavour bundles are excluded, not merged.** "Nimbu Masala + Blueberry
   Combo" is not a variant of Nimbu Masala; folding it in would credit one
   flavour with a sale of two. They are counted and named in a note instead.

Families are *derived* from the product name, never configured, and the derived
grouping is printed so a wrong call is visible rather than silent.
"""
from sqlalchemy import select

from exports import text
from exports.registry import register
from app.schemas.exports import Column, ReportSpec, Section
from app.services import watchlist_service
from scraper.utils.families import is_bundle, label, normalise

# Family grain — one product family across many stores — exists in no read
# service, so this section projects the service's OWN `_latest_per_store`
# subquery rather than writing its own filters. The window, the store-grain
# de-duplication and the `merchant_id != ''` rule all still come from
# inventory_service; only the column list differs.
from app.services.inventory_service import (  # noqa: PLC2701
    _bounds, _denominators, _latest_per_store,
)

async def product_families(db, spec: ReportSpec) -> Section | None:
    """Sheet: singles plus their multipacks, counted as one product."""
    own = await watchlist_service.get_brands_by_relationship(db, spec.tenant_id, "own")
    if not own:
        return None

    window = _bounds(spec.start, spec.end)
    # kind="all" on purpose — see the module docstring.
    stores_scraped, _, _ = await _denominators(
        db, spec.tenant_id, own, window, spec.city, spec.marketplace, "all"
    )
    latest = _latest_per_store(spec.tenant_id, own, window, spec.city, spec.marketplace, "all")
    rows = (
        await db.execute(
            select(latest.c.pid, latest.c.name, latest.c.merchant_id,
                   latest.c.in_stock, latest.c.price)
        )
    ).all()
    if not rows:
        return None

    # Per product: the stores that carry it, and how many had stock.
    products: dict[str, dict] = {}
    for pid, name, merchant_id, in_stock, price in rows:
        p = products.setdefault(pid, {"name": name, "stores": set(), "in_stock": 0, "prices": []})
        p["stores"].add(merchant_id)
        p["in_stock"] += bool(in_stock)
        if price is not None:
            p["prices"].append(price)

    families: dict[str, dict] = {}
    bundles: list[str] = []
    for pid, p in products.items():
        key = normalise(p["name"], own)
        if is_bundle(key):
            bundles.append(p["name"])
            continue
        f = families.setdefault(key, {"variants": [], "stores": set(), "listed": 0,
                                      "in_stock": 0, "prices": []})
        f["variants"].append(p["name"])
        # A union, not a sum: a store carrying both the single and the 2-pack is
        # one store on the shelf, not two.
        f["stores"] |= p["stores"]
        f["listed"] += len(p["stores"])
        f["in_stock"] += p["in_stock"]
        f["prices"] += p["prices"]

    if not families:
        return None

    data = []
    for key, f in families.items():
        carried = len(f["stores"])
        data.append({
            "family": label(key),
            "variants": len(f["variants"]),
            "stores_carrying": carried,
            "stores_observed": stores_scraped,
            "on_shelf_pct": round(carried / stores_scraped * 100, 1) if stores_scraped else None,
            "listings": f["listed"],
            "in_stock_pct": round(f["in_stock"] / f["listed"] * 100, 1) if f["listed"] else None,
            "price_low": min(f["prices"]) if f["prices"] else None,
            "price_high": max(f["prices"]) if f["prices"] else None,
            "variant_names": " · ".join(sorted(f["variants"])),
        })
    data.sort(key=lambda r: -(r["on_shelf_pct"] or 0))

    multi = sum(1 for r in data if r["variants"] > 1)
    notes = [
        "This sheet counts singles and multipacks together, whatever product filter the rest "
        "of the report uses — that is the point of it.",
        "'Stores carrying any' counts each store once, however many variants it stocks, so it "
        "is never the sum of the per-product figures on the other sheets.",
        "Families are worked out from the product name, not from a configured list. The last "
        "column shows exactly what was grouped — check it if a family looks wrong.",
    ]
    if multi:
        notes.insert(0, f"{multi} of {len(data)} families have more than one variant; the rest "
                        f"are sold as a single pack only.")
    else:
        notes.insert(0, "⚠ Every family currently has exactly one variant — this catalogue has no "
                        "same-flavour multipacks right now, so these figures match the per-product "
                        "sheet. The sheet earns its keep when multipacks appear.")
    if bundles:
        notes.append(f"{len(bundles)} multi-flavour bundle(s) were left out — a bundle of two "
                     f"flavours is not a variant of either. They appear on the product sheets "
                     f"under the combo filter.")

    return Section(
        key="product_families",
        title="Product Families",
        description="Each product with its multipacks counted together, so a repack does not look like a loss.",
        context=text.context_line(spec, f"{len(data)} families · {stores_scraped:,} stores observed"),
        columns=[
            Column(key="family", header="Product family", type="text"),
            Column(key="variants", header="Variants", type="count",
                   help="How many product ids roll up here — the single plus any multipacks."),
            Column(key="stores_carrying", header="Stores carrying any", type="count", emphasis="bar",
                   help="Stores carrying at least one variant. Each store counted once."),
            Column(key="stores_observed", header="Stores observed", type="count"),
            Column(key="on_shelf_pct", header="On shelf %", type="pct", emphasis="good_high",
                   help="Stores carrying any variant ÷ stores observed."),
            Column(key="listings", header="Store-product listings", type="count",
                   help="Store and variant pairs. Higher than 'stores carrying any' wherever a "
                        "store stocks more than one variant."),
            Column(key="in_stock_pct", header="In stock %", type="pct", emphasis="good_high",
                   help="Across every store and variant, how often there was stock."),
            Column(key="price_low", header="Cheapest variant", type="money"),
            Column(key="price_high", header="Dearest variant", type="money"),
            Column(key="variant_names", header="What was grouped", type="text", wrap=True, width=46,
                   help="The exact products rolled into this family."),
        ],
        rows=data,
        notes=notes,
    )


register("product_families", group="public", build=product_families,
         terms=("on_shelf", "in_stock", "main_vs_combo"))
