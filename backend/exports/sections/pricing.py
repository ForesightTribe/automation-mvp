"""Pricing sections — what the shelf price actually is, store by store.

Note the sheet is called "Price Spread", never "price distribution": in this
codebase `distribution` means the in-stock rate, and the glossary guard rejects
the word outright.
"""
from exports import text
from exports.registry import register
from app.schemas.exports import Column, ReportSpec, Section

from app.services import inventory_service

# ₹/100 ml, ₹/100 g, ₹/piece — the basis the per-unit columns are quoted in.
_BASIS = {"ml": "₹ per 100 ml", "g": "₹ per 100 g", "pc": "₹ per piece"}


async def price_spread(db, spec: ReportSpec) -> Section | None:
    """Sheet: per product, the cheapest and dearest store, and the per-unit band."""
    data = await inventory_service.get_pricing(
        db, tenant_id=spec.tenant_id, start=spec.start, end=spec.end,
        city=spec.city, marketplace=spec.marketplace, kind=spec.kind,
    )
    skus = data["skus"]
    if not skus:
        return None

    rows = [
        {
            "product_id": s["platform_product_id"],
            "product": s["product_name"],
            "stores": s["stores"],
            "min_price": s["min_price"],
            "median_price": s["median_price"],
            "max_price": s["max_price"],
            # The spread is what makes this sheet actionable — a wide band means
            # the same product is priced differently depending on the store.
            "spread": round(s["max_price"] - s["min_price"], 2)
            if s["min_price"] is not None and s["max_price"] is not None else None,
            "pack": f"{s['pack_size']:g} {s['pack_uom']}" if s["pack_size"] and s["pack_uom"] else None,
            "basis": _BASIS.get(s["pack_uom"], ""),
            "unit_min": s["unit_price_min"],
            "unit_median": s["unit_price_median"],
            "unit_max": s["unit_price_max"],
            "discount": s["avg_discount"],
        }
        for s in skus
    ]
    rows.sort(key=lambda r: -(r["spread"] or 0))

    return Section(
        key="price_spread",
        title="Price Spread",
        description="What each product sells for, and how far prices vary between stores.",
        context=text.context_line(spec, f"{data['stores_scraped']:,} stores observed"),
        columns=[
            Column(key="product", header="Product", type="text"),
            Column(key="product_id", header="Product ID", type="id"),
            Column(key="stores", header="Stores priced", type="count",
                   help="Stores with a price for this product at the last scrape."),
            Column(key="min_price", header="Cheapest", type="money"),
            Column(key="median_price", header="Typical", type="money",
                   help="The middle price across stores — a fairer 'normal' than the average, "
                        "which one odd store can drag."),
            Column(key="max_price", header="Dearest", type="money"),
            Column(key="spread", header="Spread", type="money", emphasis="good_low",
                   help="Dearest minus cheapest. A wide spread means the same product costs "
                        "different amounts depending on which store serves the customer."),
            Column(key="pack", header="Pack", type="text", width=12),
            Column(key="basis", header="Per-unit basis", type="text", width=16,
                   help="What the three per-unit columns are quoted in."),
            Column(key="unit_min", header="Per unit — low", type="money_fine"),
            Column(key="unit_median", header="Per unit — typical", type="money_fine",
                   help="Price normalised by pack size, so products in different pack "
                        "sizes can be compared fairly."),
            Column(key="unit_max", header="Per unit — high", type="money_fine"),
            Column(key="discount", header="Discount %", type="pct"),
        ],
        rows=rows,
        notes=[
            "Widest spread first — those are the products priced inconsistently across stores.",
            "Per-unit columns are blank where the pack size could not be read from the listing.",
        ],
    )


register("price_spread", group="public", build=price_spread,
         terms=("unit_price", "discount"))
