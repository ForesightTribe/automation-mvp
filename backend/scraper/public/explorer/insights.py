"""Explorer insights — pure aggregation over an ExplorerResult.

`build_insights(result)` turns the raw in-memory rows into the typed
`ExplorerInsights` shape. It does NO I/O — the Excel writer (`export.py`) and a
future JSON insights endpoint both consume the same object, so the numbers are
computed exactly once.

Counting rule (matches the rest of the platform): the unit is the serviceable
LOCATION `(lat, lon)`, never the store/row — see docs/public-glossary.md.
Combos are separated from singles for price comparisons (they're priced/stocked
differently); rank/SoV/availability count everything.
"""
from collections import Counter, defaultdict
from statistics import median
from typing import Any

from app.schemas.explorer import (
    AvailabilityRow,
    CatalogRow,
    CityScore,
    CompetitorScore,
    ExplorerInsights,
    KeywordScore,
    PriceRow,
    RunOverview,
)
from app.utils.time import now_ist
from scraper.public.explorer.orchestrator import ExplorerResult


def _avg(xs: list) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _median(xs: list) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(median(vals), 2) if vals else None


def _pct(num: int, den: int) -> float | None:
    return round(num / den * 100, 1) if den else None


def _loc(row: dict) -> tuple:
    return (row.get("lat"), row.get("lon"))


def _keyword_scores(snapshots, listings) -> list[KeywordScore]:
    snaps_by_kw: dict[str, list] = defaultdict(list)
    for s in snapshots:
        snaps_by_kw[s["keyword"]].append(s)
    own_by_kw: dict[str, list] = defaultdict(list)
    comp_by_kw: dict[str, list] = defaultdict(list)
    for l in listings:
        (own_by_kw if l["is_brand"] else comp_by_kw)[l["keyword"]].append(l)

    out: list[KeywordScore] = []
    for kw, snaps in snaps_by_kw.items():
        ranks = [s["brand_rank"] for s in snaps if s.get("brand_rank")]
        present = sum(1 for s in snaps if (s.get("brand_product_count") or 0) > 0)
        own = own_by_kw.get(kw, [])
        comp = comp_by_kw.get(kw, [])
        comp_counts = Counter(c.get("brand") or c.get("brand_slug") for c in comp)
        out.append(KeywordScore(
            keyword=kw,
            locations=len(snaps),
            avg_rank=_avg(ranks),
            best_rank=min(ranks) if ranks else None,
            sov_pct=_avg([s.get("brand_sov_pct") for s in snaps]),
            presence_pct=_pct(present, len(snaps)),
            in_stock_pct=_pct(sum(1 for l in own if l.get("in_stock")), len(own)),
            competitors=len({c.get("brand_slug") for c in comp}),
            top_competitor=(comp_counts.most_common(1)[0][0] if comp_counts else None),
        ))
    return sorted(out, key=lambda k: (k.sov_pct or 0), reverse=True)


def _city_scores(snapshots, listings) -> list[CityScore]:
    snaps_by_city: dict[str, list] = defaultdict(list)
    for s in snapshots:
        snaps_by_city[s["city"]].append(s)
    own_by_city: dict[str, list] = defaultdict(list)
    for l in listings:
        if l["is_brand"]:
            own_by_city[l["city"]].append(l)

    out: list[CityScore] = []
    for city, snaps in snaps_by_city.items():
        ranks = [s["brand_rank"] for s in snaps if s.get("brand_rank")]
        own = own_by_city.get(city, [])
        out.append(CityScore(
            city=city,
            locations=len({_loc(s) for s in snaps}),
            avg_rank=_avg(ranks),
            sov_pct=_avg([s.get("brand_sov_pct") for s in snaps]),
            in_stock_pct=_pct(sum(1 for l in own if l.get("in_stock")), len(own)),
            keywords=len({s["keyword"] for s in snaps}),
        ))
    return sorted(out, key=lambda c: (c.sov_pct or 0), reverse=True)


def _competitor_scores(listings) -> list[CompetitorScore]:
    comp = [l for l in listings if not l["is_brand"]]
    total = len(comp)
    by_slug: dict[str, list] = defaultdict(list)
    for l in comp:
        by_slug[l.get("brand_slug") or "unknown"].append(l)

    out: list[CompetitorScore] = []
    for slug, rows in by_slug.items():
        names = Counter(r.get("brand") for r in rows if r.get("brand"))
        out.append(CompetitorScore(
            competitor=(names.most_common(1)[0][0] if names else slug),
            locations=len({_loc(r) for r in rows}),
            keywords=len({r["keyword"] for r in rows}),
            appearances=len(rows),
            avg_position=_avg([r.get("position") for r in rows]),
            avg_price=_avg([r.get("price") for r in rows]),
            share_pct=_pct(len(rows), total),
        ))
    return sorted(out, key=lambda c: c.locations, reverse=True)


def _price_rows(listings) -> list[PriceRow]:
    own_by_kw: dict[str, list] = defaultdict(list)
    comp_by_kw: dict[str, list] = defaultdict(list)
    for l in listings:
        if l.get("is_combo"):          # singles only for price comparison
            continue
        (own_by_kw if l["is_brand"] else comp_by_kw)[l["keyword"]].append(l)

    out: list[PriceRow] = []
    for kw in sorted(set(own_by_kw) | set(comp_by_kw)):
        own_prices = [l.get("price") for l in own_by_kw.get(kw, []) if l.get("price")]
        comp_prices = [l.get("price") for l in comp_by_kw.get(kw, []) if l.get("price")]
        out.append(PriceRow(
            keyword=kw,
            own_avg=_avg(own_prices),
            own_min=min(own_prices) if own_prices else None,
            own_max=max(own_prices) if own_prices else None,
            own_discount_pct=_avg([l.get("discount_pct") for l in own_by_kw.get(kw, [])]),
            comp_avg=_avg(comp_prices),
            comp_min=min(comp_prices) if comp_prices else None,
            comp_median=_median(comp_prices),
            comp_max=max(comp_prices) if comp_prices else None,
        ))
    return out


def _availability_rows(listings) -> list[AvailabilityRow]:
    by: dict[tuple, list] = defaultdict(list)
    for l in listings:
        if l["is_brand"]:
            by[(l["keyword"], l["city"])].append(l)
    out: list[AvailabilityRow] = []
    for (kw, city), rows in by.items():
        in_stock = sum(1 for r in rows if r.get("in_stock"))
        out.append(AvailabilityRow(
            keyword=kw, city=city,
            own_found=len(rows), own_in_stock=in_stock,
            in_stock_pct=_pct(in_stock, len(rows)),
        ))
    return sorted(out, key=lambda r: (r.in_stock_pct or 0))


def _catalog_rows(sku_rows, total_locations: int) -> list[CatalogRow]:
    by_pid: dict[str, list] = defaultdict(list)
    for r in sku_rows:
        by_pid[r.get("product_id") or r.get("name", "")].append(r)

    out: list[CatalogRow] = []
    for pid, rows in by_pid.items():
        found = {_loc(r) for r in rows}
        in_stock = {_loc(r) for r in rows if r.get("in_stock")}
        prices = [r.get("price") for r in rows if r.get("price")]
        names = Counter(r.get("name") for r in rows if r.get("name"))
        out.append(CatalogRow(
            product_id=pid,
            name=(names.most_common(1)[0][0] if names else ""),
            found_locations=len(found),
            reach_pct=_pct(len(found), total_locations),
            distribution_pct=_pct(len(in_stock), len(found)),
            price_min=min(prices) if prices else None,
            price_median=_median(prices),
            price_max=max(prices) if prices else None,
            discount_pct=_avg([r.get("discount_pct") for r in rows]),
            rating=_avg([r.get("rating") for r in rows]),
            is_combo=any(r.get("is_combo") for r in rows),
        ))
    return sorted(out, key=lambda r: (r.distribution_pct or 0))


def build_insights(result: ExplorerResult) -> ExplorerInsights:
    spec = result.spec
    snaps = result.snapshots
    listings = result.listings

    keywords = _keyword_scores(snaps, listings)
    geography = _city_scores(snaps, listings)
    competitors = _competitor_scores(listings)

    own = [l for l in listings if l["is_brand"]]
    ranks = [s["brand_rank"] for s in snaps if s.get("brand_rank")]
    strongest_kw = keywords[0].keyword if keywords else None
    weakest_kw = keywords[-1].keyword if keywords else None
    strongest_city = geography[0].city if geography else None
    weakest_city = geography[-1].city if geography else None

    overview = RunOverview(
        marketplace=spec.marketplace,
        brand=spec.brand,
        mode=spec.mode,
        label=spec.label or "",
        keywords=list(spec.keywords),
        cities=list(spec.cities),
        locations_scraped=result.locations,
        sample=spec.sample,
        full=spec.full,
        generated_at=now_ist(),
        overall_sov_pct=_avg([s.get("brand_sov_pct") for s in snaps]),
        avg_rank=_avg(ranks),
        in_stock_pct=_pct(sum(1 for l in own if l.get("in_stock")), len(own)),
        keywords_top3=sum(1 for k in keywords if k.best_rank is not None and k.best_rank <= 3),
        strongest_keyword=strongest_kw,
        weakest_keyword=weakest_kw,
        strongest_city=strongest_city,
        weakest_city=weakest_city,
        total_listings=len(listings),
        total_competitors=len({l.get("brand_slug") for l in listings if not l["is_brand"]}),
        errors=len(result.errors),
    )

    return ExplorerInsights(
        overview=overview,
        keywords=keywords,
        geography=geography,
        competitors=competitors,
        pricing=_price_rows(listings),
        availability=_availability_rows(listings),
        catalog=_catalog_rows(result.sku_rows, result.locations),
    )
