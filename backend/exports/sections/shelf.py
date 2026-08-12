"""Shelf presence sections — is the product carried, and is it in stock.

Every number comes from `inventory_service`, never from fresh SQL: an export that
disagrees with the dashboard is worse than no export. This module's job is
translation — service fields into business wording and typed columns.

Registration order is sheet order, so these are defined in reading order:
summary → per product → per city → per store → the work queue → the trend.
"""
from app.dependencies import Pagination
from exports import sources, text
from exports.registry import register
from app.schemas.exports import Column, Kpi, ReportSpec, Section
from app.services import inventory_service

# get_actions expands to one row per (store × product) problem. For a mid-size
# client that is a few thousand rows; the cap stops a pathological run from
# producing an unopenable sheet, and the sheet says when it bit.
_ACTION_CAP = 5000
_TREND_DAYS = 84        # 12 weeks


def _pct(part: float, whole: float) -> float | None:
    return round(part / whole * 100, 1) if whole else None


# ── 1. Shelf Summary ──────────────────────────────────────────────────────────

async def summary(db, spec: ReportSpec) -> Section | None:
    """Sheet: the headline numbers, each with the counts behind it."""
    data = await sources.distribution(db, spec)
    skus = data["skus"]
    if not skus:
        return None

    observed = data["stores_scraped"]
    listed = sum(s["stores_listed"] for s in skus)
    in_stock = sum(s["stores_in_stock"] for s in skus)
    slots = observed * len(skus)
    gaps = sum(1 for s in skus if s["distribution_pct"] < 100)
    thin = sum(1 for s in skus if s["reach_pct"] < 50)
    prices = [s["avg_price"] for s in skus if s["avg_price"] is not None]
    discounts = [s["avg_discount"] for s in skus if s["avg_discount"] is not None]
    tiers = " · ".join(f"{n:,} {name}" for name, n in sorted(
        data["tiers"].items(), key=lambda kv: -kv[1])) or ""

    return Section(
        key="summary",
        title="Shelf Summary",
        description="The headline numbers for your products across every store we saw.",
        context=text.context_line(spec),
        kpis=[
            Kpi(label="Products tracked", value=len(skus), type="count",
                detail=f"{data['active_range']:,} carried somewhere",
                help="Own products seen at least once in this window."),
            Kpi(label="Stores observed", value=observed, type="count", detail=tiers,
                help="Distinct dark stores that answered a scrape. Not every store on the platform."),
            Kpi(label="On shelf", value=_pct(listed, slots), type="pct",
                detail=f"{listed:,} of {slots:,} store-product combinations",
                help="Across every product and every store, how often the product was carried."),
            Kpi(label="In stock", value=_pct(in_stock, listed), type="pct",
                detail=f"{in_stock:,} of {listed:,} where carried",
                help="Where the product was carried, how often it actually had stock."),
            Kpi(label="Products not everywhere", value=thin, type="count",
                detail="carried in under half the stores",
                help="The listing opportunity — products a buyer often cannot find at all."),
            Kpi(label="Products with stock gaps", value=gaps, type="count",
                detail="below 100% in stock",
                help="The replenishment opportunity — carried, but running empty somewhere."),
            Kpi(label="Average price", value=round(sum(prices) / len(prices), 1) if prices else None,
                type="money"),
            Kpi(label="Average discount", value=round(sum(discounts) / len(discounts), 1) if discounts else None,
                type="pct"),
        ],
        notes=[
            "'On shelf' and 'In stock' answer different questions and go to different teams: "
            "a product that is not carried is a listing gap, one that is carried but empty is a "
            "replenishment gap.",
            "A product missing from a store may not be carried there, or may sit past our scrape "
            "depth. From outside the two are indistinguishable.",
        ],
    )


# ── 2. SKU Shelf Presence ─────────────────────────────────────────────────────

async def sku_shelf(db, spec: ReportSpec) -> Section | None:
    """Sheet: every own product, how widely it is carried and how often in stock."""
    data = await sources.distribution(db, spec)
    skus = data["skus"]
    if not skus:
        return None

    observed = data["stores_scraped"]
    rows = [
        {
            "product_id": s["platform_product_id"],
            "product": s["product_name"],
            "stores_listed": s["stores_listed"],
            "stores_observed": observed,
            "on_shelf_pct": s["reach_pct"],
            "stores_in_stock": s["stores_in_stock"],
            "stores_empty": s["stores_out_of_stock"],
            "in_stock_pct": s["distribution_pct"],
            "avg_price": s["avg_price"],
            "avg_discount": s["avg_discount"],
        }
        for s in skus
    ]

    listed = sum(r["stores_listed"] for r in rows)
    in_stock = sum(r["stores_in_stock"] for r in rows)
    # Counts are deliberately left out of the total: summing "stores stocking it"
    # across products yields store×product pairs, a different unit from the column
    # above it. Mixing the two is how a reader concludes the numbers contradict.
    total = {
        "product": "Overall",
        "stores_observed": observed,
        "on_shelf_pct": _pct(listed, observed * len(rows)),
        "in_stock_pct": _pct(in_stock, listed),
    }

    return Section(
        key="sku_shelf",
        title="Product Shelf Presence",
        description="Every own product: how many stores carry it, and how many had it in stock.",
        context=text.context_line(spec, f"{observed:,} stores observed"),
        columns=[
            # The name leads and stays frozen while you scroll right; the id is
            # for looking things up, not for telling rows apart.
            Column(key="product", header="Product", type="text"),
            Column(key="product_id", header="Product ID", type="id",
                   help="The marketplace's own product id."),
            Column(key="stores_listed", header="Stores carrying it", type="count", emphasis="bar",
                   help="Distinct dark stores where this product appeared at all."),
            Column(key="stores_observed", header="Stores observed", type="count",
                   help="Stores that answered a scrape in this window. The denominator for 'On shelf %'."),
            Column(key="on_shelf_pct", header="On shelf %", type="pct", emphasis="good_high",
                   help="Stores carrying it ÷ stores observed. Breadth — is it stocked here at all?"),
            Column(key="stores_in_stock", header="Stores with stock", type="count",
                   help="Of the stores carrying it, how many had stock at the last scrape."),
            Column(key="stores_empty", header="Out of stock", type="count", emphasis="good_low",
                   help="Stores that carry this product but had none at the last scrape. "
                        "A replenishment gap, not a listing gap."),
            Column(key="in_stock_pct", header="In stock %", type="pct", emphasis="good_high",
                   help="Stores with stock ÷ stores carrying it. Availability where it is carried."),
            Column(key="avg_price", header="Average price", type="money"),
            Column(key="avg_discount", header="Discount %", type="pct",
                   help="Average discount off MRP across stores."),
        ],
        rows=rows,
        total_row=total,
        notes=[
            "Widest gaps first — the products carried least are at the top.",
            "The Overall row shows no counts on purpose: adding up 'stores carrying it' "
            "across products counts store-product pairs, not stores.",
        ],
    )


# ── 3. City Shelf Presence ────────────────────────────────────────────────────

async def city_shelf(db, spec: ReportSpec) -> Section | None:
    """Sheet: the same lenses one level up, per city."""
    data = await inventory_service.get_cities(
        db, tenant_id=spec.tenant_id, start=spec.start, end=spec.end,
        marketplace=spec.marketplace, kind=spec.kind,
    )
    cities = data["cities"]
    if not cities:
        return None

    rows = [
        {
            "city": (c["city"] or "unknown").title(),
            "stores": c["stores"],
            "listings": c["skus_listed"],
            "in_stock": c["skus_in_stock"],
            "empty": c["skus_out_of_stock"],
            "not_carried": c["skus_not_listed"],
            "on_shelf_pct": c["reach_pct"],
            "in_stock_pct": c["distribution_pct"],
        }
        for c in cities
    ]
    listed = sum(r["listings"] for r in rows)
    return Section(
        key="city_shelf",
        title="City Shelf Presence",
        description="Where your products are carried and available, city by city.",
        context=text.context_line(spec, f"{data['active_range']} products carried somewhere"),
        columns=[
            Column(key="city", header="City", type="text"),
            Column(key="stores", header="Stores observed", type="count", emphasis="bar",
                   help="Distinct dark stores in this city that answered a scrape."),
            Column(key="listings", header="Carried here", type="count",
                   help="Store-product pairs where the product was on the shelf. "
                        "Counts pairs, not stores — one store carrying 10 products counts 10."),
            Column(key="in_stock", header="With stock", type="count",
                   help="Of those store-product pairs, how many had stock."),
            Column(key="empty", header="Out of stock", type="count", emphasis="good_low",
                   help="Carried but empty — a replenishment gap."),
            Column(key="not_carried", header="Not carried", type="count", emphasis="good_low",
                   help="Store-product pairs where the product was absent — a listing gap."),
            Column(key="on_shelf_pct", header="On shelf %", type="pct", emphasis="good_high",
                   help="Carried ÷ every possible store-product pair in this city."),
            Column(key="in_stock_pct", header="In stock %", type="pct", emphasis="good_high",
                   help="With stock ÷ carried."),
        ],
        rows=rows,
        total_row={
            "city": "Overall",
            "stores": sum(r["stores"] for r in rows),
            "listings": listed,
            "in_stock": sum(r["in_stock"] for r in rows),
            "empty": sum(r["empty"] for r in rows),
            "not_carried": sum(r["not_carried"] for r in rows),
            "in_stock_pct": _pct(sum(r["in_stock"] for r in rows), listed),
        },
        notes=[
            "The middle four columns count store-product pairs, not stores — a city with more "
            "stores will show larger numbers for the same performance. Compare the percentages.",
            "'On shelf %' has no Overall figure here: each city has its own store count, so the "
            "city percentages cannot simply be averaged.",
        ],
    )


# ── 4. Store Shelf Presence ───────────────────────────────────────────────────

async def store_shelf(db, spec: ReportSpec) -> Section | None:
    """Sheet: per dark store — which shops are letting the brand down."""
    data = await inventory_service.get_stores(
        db, tenant_id=spec.tenant_id, start=spec.start, end=spec.end,
        city=spec.city, marketplace=spec.marketplace, kind=spec.kind,
    )
    stores = data["stores"]
    if not stores:
        return None

    rows = [
        {
            "store_id": s["merchant_id"],
            "store_name": s["store_name"],
            "tier": (s["merchant_type"] or "unknown").replace("_", " ").title(),
            "city": (s["city"] or "unknown").title(),
            "carried": s["skus_listed"],
            "in_stock": s["skus_in_stock"],
            "empty": s["skus_out_of_stock"],
            "not_carried": s["skus_not_listed"],
            "on_shelf_pct": s["reach_pct"],
            "in_stock_pct": s["distribution_pct"],
        }
        for s in stores
    ]
    return Section(
        key="store_shelf",
        title="Store Shelf Presence",
        description="Every dark store we saw, worst first — where your range is thinnest.",
        context=text.context_line(spec, f"{data['active_range']} products in your range"),
        columns=[
            Column(key="store_name", header="Store", type="text",
                   help="Blank where the store is not in our catalogue — newly opened stores and "
                        "hubs are often discovered by a scrape before they are named. The id in "
                        "the next column always identifies it."),
            Column(key="store_id", header="Store ID", type="id"),
            Column(key="tier", header="Store tier", type="text",
                   help="Express stores hold the 10-minute core range; hub stores carry extended "
                        "range more slowly. Tier describes how the product is fulfilled, not the store."),
            Column(key="city", header="City", type="text"),
            Column(key="carried", header="Products carried", type="count", emphasis="bar"),
            Column(key="in_stock", header="With stock", type="count"),
            Column(key="empty", header="Out of stock", type="count", emphasis="good_low"),
            Column(key="not_carried", header="Not carried", type="count", emphasis="good_low",
                   help="Products in your range that this store does not carry at all."),
            Column(key="on_shelf_pct", header="On shelf %", type="pct", emphasis="good_high",
                   help="Products carried ÷ products in your range."),
            Column(key="in_stock_pct", header="In stock %", type="pct", emphasis="good_high"),
        ],
        rows=rows,
        notes=[
            "Sorted worst first: most out-of-stock, then thinnest range.",
            "'Your range' is the products seen in at least one store this window — observed, "
            "not a configured list.",
        ],
    )


# ── 5. Needs Attention ────────────────────────────────────────────────────────

async def needs_attention(db, spec: ReportSpec) -> Section | None:
    """Sheet: the work queue — one row per problem, naming a store and a product."""
    kw = dict(tenant_id=spec.tenant_id, start=spec.start, end=spec.end,
              city=spec.city, marketplace=spec.marketplace, kind=spec.kind)
    page = Pagination(page=1, limit=_ACTION_CAP)
    oos = await inventory_service.get_actions(db, pagination=page, action="oos", **kw)
    missing = await inventory_service.get_actions(db, pagination=page, action="not-listed", **kw)

    items = list(oos.items) + list(missing.items)
    if not items:
        return None

    label = {"out-of-stock": "Out of stock", "not-listed": "Not carried"}
    rows = [
        {
            "problem": label.get(i["issue"], i["issue"]),
            "product": i["product_name"],
            "city": (i["city"] or "unknown").title(),
            "store": i["store_name"] or i["merchant_id"],
            "store_id": i["merchant_id"],
            "units": i["inventory"],
            "price": i["price"],
            "action": ("Replenish — the store carries it but has none"
                       if i["issue"] == "out-of-stock"
                       else "Raise a listing request — the store does not carry it"),
        }
        for i in items
    ]
    rows.sort(key=lambda r: (r["problem"], r["city"], r["product"]))

    notes = [
        "Two different problems, deliberately in one filterable list: filter the Problem column "
        "before acting. 'Not carried' goes to the category/commercial team, 'Out of stock' to supply.",
        "Never add the two together — they are different opportunities of different sizes.",
    ]
    if oos.total > _ACTION_CAP or missing.total > _ACTION_CAP:
        notes.insert(0, f"⚠ Truncated: {oos.total:,} out-of-stock and {missing.total:,} "
                        f"not-carried problems exist; the first {_ACTION_CAP:,} of each are listed.")

    return Section(
        key="needs_attention",
        title="Needs Attention",
        description="Every gap worth acting on, one row per store and product.",
        context=text.context_line(spec, f"{len(rows):,} problems"),
        columns=[
            Column(key="product", header="Product", type="text"),
            Column(key="problem", header="Problem", type="text", width=15,
                   chips={"Not carried": "bad", "Out of stock": "warn"},
                   help="'Not carried' is a listing gap (commercial). 'Out of stock' is a "
                        "replenishment gap (supply). Filter this column before acting."),
            Column(key="city", header="City", type="text"),
            Column(key="store", header="Store", type="text"),
            Column(key="store_id", header="Store ID", type="id"),
            Column(key="units", header="Units left", type="count",
                   help="Blank for 'Not carried' — the product is absent, so there is no stock figure."),
            Column(key="price", header="Price", type="money"),
            Column(key="action", header="What to do", type="text", wrap=True, width=44),
        ],
        rows=rows,
        notes=notes,
    )


# ── 6. Availability Trend ─────────────────────────────────────────────────────

async def availability_trend(db, spec: ReportSpec) -> Section | None:
    """Sheet: weekly in-stock rate — is availability improving or slipping."""
    data = await inventory_service.get_availability_history(
        db, tenant_id=spec.tenant_id, days=_TREND_DAYS,
        city=spec.city, marketplace=spec.marketplace, kind=spec.kind,
    )
    points = data["points"]
    if not points:
        return None

    rows = [
        {
            "week": p["week"],
            "in_stock_pct": p["availability_pct"],
            "oos_pct": p["oos_pct"],
            "stores": p["stores"],
        }
        for p in points
    ]
    return Section(
        key="availability_trend",
        title="Availability Trend",
        description="Weekly in-stock rate for your products — the direction of travel.",
        context=f"Last {_TREND_DAYS // 7} weeks · "
                f"{(spec.marketplace or 'all marketplaces').title()} · "
                f"{text.kind_label(spec.kind, short=True)}",
        columns=[
            Column(key="week", header="Week starting", type="date"),
            Column(key="in_stock_pct", header="In stock %", type="pct", emphasis="good_high"),
            Column(key="oos_pct", header="Out of stock %", type="pct", emphasis="good_low"),
            Column(key="stores", header="Stores sampled", type="count",
                   help="How many distinct stores that week's figure is based on. "
                        "A small sample moves the percentage around."),
        ],
        rows=rows,
        freeze_label_col=True,
        notes=[
            f"⚠ This is the ONLY sheet not limited to your selected dates. A trend needs history, "
            f"so it always shows the last {_TREND_DAYS // 7} weeks up to today.",
            "Weeks with few stores sampled are less reliable — check the sample column before "
            "reading a swing as real.",
        ],
    )


register("summary", group="public", build=summary,
         terms=("on_shelf", "in_stock", "store_tier"))
register("sku_shelf", group="public", build=sku_shelf,
         terms=("on_shelf", "in_stock", "discount"))
register("city_shelf", group="public", build=city_shelf,
         terms=("on_shelf", "in_stock"))
register("store_shelf", group="public", build=store_shelf,
         terms=("on_shelf", "in_stock", "store_tier"))
register("needs_attention", group="public", build=needs_attention,
         terms=("on_shelf", "in_stock"))
# Not window-scoped: a trend needs history, so it is anchored to now rather than
# to the selected dates. It must never be the only sheet in a workbook.
register("availability_trend", group="public", build=availability_trend,
         terms=("in_stock",), window_scoped=False)
