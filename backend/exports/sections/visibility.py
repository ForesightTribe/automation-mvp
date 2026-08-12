"""Visibility sections — where you show up when a shopper searches.

These read `competition_service`. Note the vocabulary: the service's `sov` is
"share of search" here, and `position` is always described as "1 is the top"
because a *rising* position number is a decline — the one metric on the whole
report where a bigger number is worse.
"""
import re

from exports import sources, text
from exports.registry import register
from app.schemas.exports import Column, ReportSpec, Section
from app.services import competition_service

_CITY_LIMIT = 12        # columns on the grid before it stops being readable


def _key(city: str) -> str:
    """A city name as a safe row-dict key ('Delhi NCR' -> 'c_delhi_ncr')."""
    return "c_" + re.sub(r"[^a-z0-9]+", "_", city.lower()).strip("_")


# ── 8. Search Visibility ──────────────────────────────────────────────────────

async def search_visibility(db, spec: ReportSpec) -> Section | None:
    """Sheet: per search term — how much of the page you own and where you rank.

    Share and position come from `get_share_of_voice`, one call per term, rather
    than being rolled up here. Rolling up looks tempting — the grid already has
    per-city averages — but the two averages have different denominators: the
    service averages position over the searches where the brand *appeared*, while
    the grid's search count includes searches where it did not. Weighting by the
    latter overstated position on exactly the low-visibility terms where it
    matters most (12.2 against a true 11.81 for "soda"). The city columns below
    are read straight off the grid cells, which is a lookup, not an average.
    """
    data = await sources.rank_matrix(db, spec)
    cells = data["cells"]
    if not cells:
        return None

    by_kw: dict[str, list] = {}
    for c in cells:
        by_kw.setdefault(c["keyword"], []).append(c)

    rows = []
    for kw, group in by_kw.items():
        sov = await competition_service.get_share_of_voice(
            db, tenant_id=spec.tenant_id, keyword=kw, city=spec.city,
            marketplace=spec.marketplace, start=spec.start, end=spec.end,
        )
        s = sov["summary"]
        ranked = [c for c in group if c["avg_rank"] is not None]
        rows.append({
            "keyword": kw,
            "cities": len({c["city"] for c in group}),
            "searches": s["total_samples"],
            "share_pct": s["avg_sov"],
            "avg_position": s["avg_rank"],
            "best_city": min(ranked, key=lambda c: c["avg_rank"])["city"].title() if ranked else None,
            "worst_city": max(ranked, key=lambda c: c["avg_rank"])["city"].title() if ranked else None,
        })
    rows.sort(key=lambda r: -(r["share_pct"] or 0))

    return Section(
        key="search_visibility",
        title="Search Visibility",
        description="For each search term, how much of the results page you own and where you sit on it.",
        context=text.context_line(spec, f"{sum(r['searches'] for r in rows):,} searches sampled"),
        columns=[
            Column(key="keyword", header="Search term", type="text"),
            Column(key="cities", header="Cities", type="count",
                   help="Cities where this term was searched."),
            Column(key="searches", header="Searches sampled", type="count", emphasis="bar",
                   help="How many individual searches sit behind this row."),
            Column(key="share_pct", header="Share of search %", type="pct", emphasis="good_high",
                   help="The share of the results page taken by your products, averaged across "
                        "searches."),
            Column(key="avg_position", header="Average position", type="rating", emphasis="good_low",
                   help="Where your best product sits in the results. Position 1 is the top of "
                        "the page — LOWER IS BETTER."),
            Column(key="best_city", header="Strongest city", type="text",
                   help="Where you rank highest for this term."),
            Column(key="worst_city", header="Weakest city", type="text"),
        ],
        rows=rows,
        notes=[
            "Position 1 is the top of the page, so a lower average position is better. "
            "This is the only column on the report where a smaller number is the good news.",
            "A blank position means your products did not appear in that search at all.",
        ],
    )


# ── 9. Rank by Keyword × City ─────────────────────────────────────────────────

async def rank_grid(db, spec: ReportSpec) -> Section | None:
    """Sheet: the weakness grid — average position per search term and city."""
    data = await sources.rank_matrix(db, spec)
    cells = data["cells"]
    if not cells:
        return None

    # Busiest cities first, so a truncated grid keeps the ones that matter.
    weight: dict[str, int] = {}
    for c in cells:
        weight[c["city"]] = weight.get(c["city"], 0) + c["searches"]
    cities = sorted(weight, key=lambda c: -weight[c])[:_CITY_LIMIT]

    lookup = {(c["keyword"], c["city"]): c for c in cells}
    rows = []
    for kw in data["keywords"]:
        row = {"keyword": kw}
        for city in cities:
            cell = lookup.get((kw, city))
            row[_key(city)] = cell["avg_rank"] if cell else None
        rows.append(row)

    notes = [
        "Green is a strong position, red is weak. Position 1 is the top of the page, "
        "so LOW numbers are good — the colours follow that, not the number.",
        "A blank cell means your products did not appear for that term in that city.",
    ]
    if len(weight) > _CITY_LIMIT:
        notes.insert(0, f"Showing the {_CITY_LIMIT} most-searched cities of {len(weight)}. "
                        f"The Search Visibility sheet covers every city.")

    return Section(
        key="rank_grid",
        title="Position by Search Term and City",
        description="Where you rank for each search term in each city — the map of where you are weak.",
        context=text.context_line(spec, "average position"),
        columns=[Column(key="keyword", header="Search term", type="text")] + [
            Column(key=_key(c), header=c.title(), type="rating", emphasis="heat",
                   help=f"Average position in {c.title()}. Position 1 is the top of the page.")
            for c in cities
        ],
        rows=rows,
        notes=notes,
    )


# ── 10. Top Competitors ───────────────────────────────────────────────────────

async def competitors(db, spec: ReportSpec) -> Section | None:
    """Sheet: which rival brands keep appearing in your searches."""
    data = await competition_service.get_top_competitors(
        db, tenant_id=spec.tenant_id, city=spec.city, marketplace=spec.marketplace,
        start=spec.start, end=spec.end, limit=25,
    )
    found = data["competitors"]
    if not found:
        return None

    rows = [
        {
            "brand": (c["competitor"] or "unknown").replace("-", " ").title(),
            "stores": c["stores"],
            "share_pct": c["share_pct"],
            "keywords": c["keywords"],
            "avg_position": c["avg_position"],
            "avg_price": c["avg_price"],
        }
        for c in found
    ]
    return Section(
        key="competitors",
        title="Top Competitors",
        description="The brands that keep turning up in the same searches as your products.",
        context=text.context_line(spec, f"{data['total_competitor_stores']:,} brand-store appearances"),
        columns=[
            Column(key="brand", header="Brand", type="text"),
            Column(key="stores", header="Stores seen in", type="count", emphasis="bar",
                   help="Distinct dark stores where this brand appeared in your search terms."),
            Column(key="share_pct", header="Share of shelf %", type="pct", emphasis="good_low",
                   help="This brand's slice of every competitor appearance across your searches. "
                        "A rival's gain is your loss, so lower is better for you."),
            Column(key="keywords", header="Search terms", type="count",
                   help="How many of your search terms this brand showed up in. A brand on many "
                        "terms competes with your whole range, not one product."),
            Column(key="avg_position", header="Average position", type="rating",
                   help="Where they sit in the results. Position 1 is the top of the page."),
            Column(key="avg_price", header="Average price", type="money"),
        ],
        rows=rows,
        notes=[
            "This sheet counts stores, so it only covers scrapes from 18 July 2026 onward — "
            "earlier records do not identify which store served a result. Expect a shorter "
            "history here than on the other search sheets.",
            "Your own brand is excluded; these are competitors only.",
        ],
    )


# ── 11. Price vs Competitors ──────────────────────────────────────────────────

async def price_position(db, spec: ReportSpec) -> Section | None:
    """Sheet: your price band against the competitor band, per search term."""
    data = await competition_service.get_price_position(
        db, tenant_id=spec.tenant_id, city=spec.city, marketplace=spec.marketplace,
        start=spec.start, end=spec.end, kind=spec.kind,
    )
    found = data["rows"]
    if not found:
        return None

    basis = {"ml": "per 100 ml", "g": "per 100 g", "pc": "per piece"}
    rows = []
    for r in found:
        own, comp = r["own_avg_price"], r["comp_median_price"]
        rows.append({
            "keyword": r["keyword"],
            "own_min": r["own_min_price"],
            "own_avg": r["own_avg_price"],
            "own_max": r["own_max_price"],
            "comp_min": r["comp_min_price"],
            "comp_median": r["comp_median_price"],
            "comp_max": r["comp_max_price"],
            # The whole point of the sheet in one column.
            "vs_market": round((own - comp) / comp * 100, 1) if own and comp else None,
            "basis": basis.get(r["unit_uom"], ""),
            "own_unit": r["own_avg_unit_price"],
            "comp_unit": r["comp_median_unit_price"],
            "own_samples": r["own_samples"],
            "comp_samples": r["comp_samples"],
        })
    rows.sort(key=lambda r: -(abs(r["vs_market"]) if r["vs_market"] is not None else -1))

    return Section(
        key="price_position",
        title="Price vs Competitors",
        description="What you charge against what the rest of the shelf charges, per search term.",
        context=text.context_line(spec),
        columns=[
            Column(key="keyword", header="Search term", type="text"),
            Column(key="own_min", header="You — low", type="money"),
            Column(key="own_avg", header="You — average", type="money"),
            Column(key="own_max", header="You — high", type="money"),
            Column(key="comp_min", header="Market — low", type="money"),
            Column(key="comp_median", header="Market — typical", type="money",
                   help="The middle competitor price on the results page."),
            Column(key="comp_max", header="Market — high", type="money"),
            Column(key="vs_market", header="You vs market %", type="pct",
                   help="How far your average sits above (+) or below (−) the typical competitor "
                        "price. Neither direction is automatically good — it depends on where you "
                        "mean to sit."),
            Column(key="basis", header="Per-unit basis", type="text", width=14),
            Column(key="own_unit", header="You per unit", type="money_fine",
                   help="Price normalised by pack size — the fair comparison when your pack "
                        "differs from a competitor's."),
            Column(key="comp_unit", header="Market per unit", type="money_fine"),
            Column(key="own_samples", header="Your listings", type="count",
                   help="How many of your listings this row is based on. A handful is not a trend."),
            Column(key="comp_samples", header="Competitor listings", type="count"),
        ],
        rows=rows,
        notes=[
            "Biggest gap from the market first.",
            "Compare the per-unit columns, not the shelf prices, when pack sizes differ — a "
            "dearer bottle can still be the cheaper drink.",
            "Rows with very few listings are noisy; check the last two columns before acting.",
        ],
    )


register("search_visibility", group="public", build=search_visibility,
         terms=("share_of_search", "position"))
register("rank_grid", group="public", build=rank_grid, terms=("position",))
register("competitors", group="public", build=competitors,
         terms=("position", "store_tier"))
register("price_position", group="public", build=price_position,
         terms=("unit_price", "main_vs_combo"))
