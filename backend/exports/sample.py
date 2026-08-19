"""A fixture `Report` that exercises the whole design system — no DB, no scrape.

`cli export sample` renders this so the look can be judged (and regressions
spotted) in seconds instead of waiting on a query. It deliberately includes the
awkward cases: an empty cell, a 90-character product name, a KPI-only sheet,
both colour scales, data bars, chips and a totals row.

There is no raw-data sheet here, and there is none in a real report either: raw
rows go to CSV through `cli export raw`. Nothing to preview — it is just rows.
"""
import random
from datetime import datetime

from exports import glossary
from app.schemas.exports import Column, Kpi, MetaItem, Report, Section

_CITIES = ["Bengaluru", "Mumbai", "Delhi NCR", "Hyderabad", "Pune", "Chennai"]
_SKUS = [
    "Nimbu Masala Goli Soda 250 ml",
    "Kokum Jeera Goli Soda 250 ml",
    "Blueberry Goli Soda 250 ml",
    "Mango Goli Soda 250 ml",
    "Grape Goli Soda 250 ml",
    "Apple Mojito Goli Soda 250 ml",
    "Rose Apple Goli Soda 250 ml",
    "Strawberry Cotton Candy 20 g",
    "Bubblegum Cotton Candy 20 g",
    "Smoky BBQ Tapioca Chips 60 g",
    "Spicy Kari Tapioca Chips 60 g",
    "Tangy Tomato Tapioca Chips 60 g",
    "Garlic Pickle Tapioca Chips 60 g",
    # The pathological long name — proves the p90 width rule keeps the sheet readable.
    "Plain Salted Tapioca Chips 60 g (Limited Edition Festive Multipack Sleeve)",
]
_KEYWORDS = ["goli soda", "nimbu soda", "masala soda", "cotton candy", "tapioca chips", "banana chips"]


def _summary() -> Section:
    return Section(
        key="summary",
        title="Shelf Summary",
        description="The headline numbers for your brand across every dark store we saw.",
        context="1–7 Aug 2026 · Blinkit · Main SKUs · 5,090 stores observed",
        kpis=[
            Kpi(label="SKUs tracked", value=14, type="count",
                help="Own SKUs seen at least once in the selected window."),
            Kpi(label="Stores observed", value=5090, type="count",
                detail="2,059 express · 510 hub",
                help="Distinct dark stores that answered a scrape. Not the same as stores that exist."),
            Kpi(label="On shelf", value=84.7, type="pct", detail="4,312 of 5,090 stores",
                help="Stores where the SKU was listed at all — breadth."),
            Kpi(label="In stock", value=95.8, type="pct", detail="4,131 of 4,312 listed",
                help="Of the stores where it was listed, how many actually had stock."),
            Kpi(label="Average selling price", value=39.4, type="money"),
            Kpi(label="Average discount", value=8.2, type="pct"),
            Kpi(label="SKUs with gaps", value=6, type="count",
                detail="below 100% in-stock", help="Own SKUs not fully in stock everywhere they are listed."),
            Kpi(label="Rating", value=4.3, type="rating"),
        ],
        notes=[
            "A SKU missing from a store is not proof it is out of stock — it may simply not be carried there.",
            "Percentages are of stores observed in this window, never of every store on the platform.",
        ],
    )


def _sku_shelf() -> Section:
    rng = random.Random(7)
    rows = []
    for i, name in enumerate(_SKUS):
        listed = rng.randint(2600, 5050)
        in_stock = int(listed * rng.uniform(0.86, 1.0))
        price = rng.choice([35, 40, 45, 50, 20])
        rows.append({
            "product_id": f"55{4760 + i * 7}",
            "name": name,
            "stores_listed": listed,
            "stores_observed": 5090,
            "on_shelf_pct": round(listed / 5090 * 100, 1),
            "stores_in_stock": in_stock,
            "in_stock_pct": round(in_stock / listed * 100, 1),
            "price_median": price,
            "price_min": price - rng.randint(0, 6),
            "price_max": price + rng.randint(0, 8),
            "unit_price": round(price / 2.5, 2),
            "discount_pct": round(rng.uniform(0, 18), 1),
            # A genuinely missing rating — must render as a dash, not a zero.
            "rating": None if i == 3 else round(rng.uniform(3.6, 4.8), 1),
        })
    total = {
        "name": "Overall",
        "stores_listed": sum(r["stores_listed"] for r in rows),
        "stores_observed": 5090,
        "on_shelf_pct": 84.7,
        "stores_in_stock": sum(r["stores_in_stock"] for r in rows),
        "in_stock_pct": 95.8,
    }
    return Section(
        key="sku_shelf",
        title="SKU Shelf Presence",
        description="Every own SKU: how many stores stock it, and how many had it in stock.",
        context="1–7 Aug 2026 · Blinkit · Main SKUs · 5,090 stores observed",
        columns=[
            Column(key="product_id", header="Product ID", type="id",
                   help="Blinkit's consumer-side product id."),
            Column(key="name", header="Product", type="text"),
            Column(key="stores_listed", header="Stores stocking it", type="count", emphasis="bar",
                   help="Distinct dark stores where this SKU appeared at all."),
            Column(key="stores_observed", header="Stores observed", type="count",
                   help="Stores that answered a scrape in this window. The denominator."),
            Column(key="on_shelf_pct", header="On shelf %", type="pct", emphasis="good_high",
                   help="Stores stocking it ÷ stores observed. Breadth — am I on the shelf here at all?"),
            Column(key="stores_in_stock", header="Stores with stock", type="count",
                   help="Of the stores listing it, how many had stock on the last scrape."),
            Column(key="in_stock_pct", header="In stock %", type="pct", emphasis="good_high",
                   help="Stores with stock ÷ stores stocking it. Health — where I am listed, am I available?"),
            Column(key="price_median", header="Price (median)", type="money"),
            Column(key="price_min", header="Price (low)", type="money"),
            Column(key="price_max", header="Price (high)", type="money"),
            Column(key="unit_price", header="₹ per 100 ml", type="money_fine",
                   help="Price normalised by pack size, so packs of different sizes compare fairly."),
            Column(key="discount_pct", header="Discount %", type="pct", emphasis="good_low",
                   help="Average discount off MRP."),
            Column(key="rating", header="Rating", type="rating"),
        ],
        rows=rows,
        total_row=total,
        notes=["Sorted by product id. Combos and multipacks are excluded — this is the Main SKU view."],
    )


def _competitors() -> Section:
    """Where the own-brand tint earns its keep — one highlighted row in a list of
    rivals. (Tinting *every* row, as on a pure own-SKU sheet, says nothing.)"""
    rng = random.Random(19)
    brands = ["Paper Boat", "Coca-Cola", "Bindu", "Dobra", "Sting", "Jayanti", "Lahori", "Rasna"]
    rows = []
    for i, brand in enumerate(brands):
        stores = rng.randint(400, 4800)
        rows.append({
            "brand": brand,
            "is_own": brand == "Dobra",
            "stores_seen": stores,
            "share_pct": round(stores / 14000 * 100, 1),
            "keywords": rng.randint(1, 6),
            "avg_position": round(rng.uniform(2, 22), 1),
            "avg_price": rng.randint(20, 90),
        })
    rows.sort(key=lambda r: -r["stores_seen"])
    return Section(
        key="competitors",
        title="Top Competitors",
        description="The brands that keep turning up in the same searches as yours.",
        context="1–7 Aug 2026 · Blinkit · your tracked search terms",
        columns=[
            Column(key="brand", header="Brand", type="text"),
            Column(key="stores_seen", header="Stores seen in", type="count", emphasis="bar",
                   help="Distinct dark stores where this brand appeared in your search terms."),
            Column(key="share_pct", header="Share of shelf %", type="pct", emphasis="good_high"),
            Column(key="keywords", header="Search terms", type="count"),
            Column(key="avg_position", header="Avg position", type="rating", emphasis="good_low",
                   help="Their average rank. Position 1 is the top of the page — lower is better."),
            Column(key="avg_price", header="Avg price", type="money"),
        ],
        rows=rows,
        highlight_key="is_own",
        notes=["Your own brand is highlighted. Share is of all brand appearances across your search terms."],
    )


def _rank_grid() -> Section:
    rng = random.Random(11)
    rows = [
        {"keyword": kw, **{c.lower().replace(" ", "_"): round(rng.uniform(1, 28), 1) for c in _CITIES}}
        for kw in _KEYWORDS
    ]
    return Section(
        key="rank_grid",
        title="Rank by Keyword × City",
        description="Where you appear in search results. Position 1 is the top of the page — lower is better.",
        context="1–7 Aug 2026 · Blinkit · average position across stores in each city",
        columns=[Column(key="keyword", header="Search term", type="text")] + [
            Column(key=c.lower().replace(" ", "_"), header=c, type="rating", emphasis="heat",
                   help=f"Average search position in {c}. Green is strong, red is weak.")
            for c in _CITIES
        ],
        rows=rows,
        notes=["Green cells are strong positions, red are weak. This is the one grid that uses a full colour ramp."],
    )


def _needs_attention() -> Section:
    rng = random.Random(3)
    rows = []
    for i in range(18):
        problem = "Not listed" if i % 3 == 0 else ("Out of stock" if i % 3 == 1 else "Low stock")
        rows.append({
            "name": _SKUS[i % len(_SKUS)],
            "city": _CITIES[i % len(_CITIES)],
            "store": f"BLR-{1400 + i * 13}",
            "problem": problem,
            "stores_affected": rng.randint(3, 240),
            "what_to_do": "Raise a listing request with the category team"
                          if problem == "Not listed" else "Replenish — the store carries it but has none",
        })
    return Section(
        key="needs_attention",
        title="Needs Attention",
        description="The gaps worth acting on, split by who can fix them.",
        context="1–7 Aug 2026 · Blinkit · ranked by stores affected",
        columns=[
            Column(key="name", header="Product", type="text"),
            Column(key="city", header="City", type="text"),
            Column(key="store", header="Store", type="id"),
            Column(key="problem", header="Problem", type="text", width=16,
                   chips={"Not listed": "bad", "Out of stock": "warn", "Low stock": "good"},
                   help="Not listed is a range gap (commercial). Out of stock is a replenishment gap (supply)."),
            Column(key="stores_affected", header="Stores affected", type="count", emphasis="bar"),
            Column(key="what_to_do", header="What to do", type="text", wrap=True, width=40),
        ],
        rows=rows,
        notes=["'Not listed' and 'Out of stock' are different problems for different teams — they are never merged."],
    )


def _glossary():
    """The glossary is NOT redefined here — it comes from the same dict the real
    reports use, so the fixture can never drift from the shipped wording."""
    return glossary.collect(
        "on_shelf", "in_stock", "store_tier", "share_of_search",
        "position", "unit_price", "discount",
    )


def sample_report() -> Report:
    """The fixture. Every column type, both scales, chips, an empty cell, a
    totals row and a KPI-only sheet."""
    return Report(
        title="Dobra — Blinkit Shelf Report",
        subtitle="Sample workbook · rendered from fixture data, no database involved",
        filename_stem="sample_report",
        generated_at=datetime.now(),
        meta=[
            MetaItem(label="Client", value="Dobra"),
            MetaItem(label="Marketplace", value="Blinkit"),
            MetaItem(label="Date range", value="1 – 7 August 2026", note="the dates you selected"),
            MetaItem(label="Cities", value="Bengaluru, Mumbai, Delhi NCR, Hyderabad, Pune, Chennai"),
            MetaItem(label="Product filter", value="Main SKUs (combos excluded)"),
            MetaItem(label="Data freshness", value="Scraped 7 Aug 2026", note="3 days ago — collected weekly, not live"),
            MetaItem(label="Stores observed", value=5090),
            MetaItem(label="SKUs tracked", value=14),
            MetaItem(label="Search terms", value=6),
        ],
        sections=[_summary(), _sku_shelf(), _rank_grid(), _competitors(),
                  _needs_attention()],
        glossary=_glossary(),
    )
