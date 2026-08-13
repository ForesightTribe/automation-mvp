"""Explorer insights — pure aggregation over an ExplorerResult.

`build_insights(result)` turns the raw in-memory rows into the typed
`ExplorerInsights` shape. It does NO I/O — the Excel writer (`export.py`) and a
future JSON insights endpoint both consume the same object, so the numbers are
computed exactly once.

Counting rule: **the unit is the dark store (`merchant_id`)**, matching the read
services and `docs/public-glossary.md`. Rows with no store id are excluded — a
presence we cannot attribute to a shop is not evidence of a shop.

⚠ Until 2026-08-11 this counted serviceable LOCATIONS `(lat, lon)`, which was
correct when Explorer was written and stopped being correct on 2026-07-18 when
dark-store discovery landed. One coordinate can resolve to several stores and one
store can answer several coordinates, so the old counts both split and
double-counted against the client report's.

`locations_scraped` survives as "points we searched from" — it is a measure of
effort, not of shelf. Combos are separated from singles for price comparisons;
rank/share/availability count everything.
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
    FamilyRow,
    GapRow,
    GridCell,
    KeywordScore,
    PriceRow,
    RunOverview,
    StoreScore,
)
from app.utils.time import now_ist
from scraper.public.explorer.orchestrator import ExplorerResult
from scraper.utils.families import is_bundle, label, normalise
from scraper.utils.pack import per_unit_price


def _dominant_uom(rows: list) -> str:
    """The most common parseable UOM among rows — labels the per-unit basis."""
    c = Counter(r.get("pack_uom") for r in rows if r.get("pack_uom"))
    return c.most_common(1)[0][0] if c else ""


def _unit_prices(rows: list) -> list:
    """Per-unit price (₹/100 ml · 100 g · piece) for each row that has a parseable
    pack — the fair cross-pack comparison; unparseable rows drop out."""
    return [p for r in rows
            if (p := per_unit_price(r.get("price"), r.get("pack_size"), r.get("pack_uom") or "")) is not None]


def _avg(xs: list) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _median(xs: list) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(median(vals), 2) if vals else None


def _pct(num: int, den: int) -> float | None:
    return round(num / den * 100, 1) if den else None


def _store(row: dict) -> str | None:
    """The dark store that fulfils this row, or None when unattributable."""
    return (row.get("merchant_id") or "").strip() or None


def _stores(rows) -> set:
    return {m for r in rows if (m := _store(r))}


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
            searches=len(snaps),
            stores=len(_stores(own) | _stores(comp) | _stores(snaps)),
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
            stores=len(_stores(snaps) | _stores(own)),
            searches=len(snaps),
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
            stores=len(_stores(rows)),
            keywords=len({r["keyword"] for r in rows}),
            appearances=len(rows),
            avg_position=_avg([r.get("position") for r in rows]),
            avg_price=_avg([r.get("price") for r in rows]),
            share_pct=_pct(len(rows), total),
        ))
    return sorted(out, key=lambda c: c.stores, reverse=True)


def _price_rows(listings) -> list[PriceRow]:
    own_by_kw: dict[str, list] = defaultdict(list)
    comp_by_kw: dict[str, list] = defaultdict(list)
    for l in listings:
        if l.get("is_combo"):          # singles only for price comparison
            continue
        (own_by_kw if l["is_brand"] else comp_by_kw)[l["keyword"]].append(l)

    out: list[PriceRow] = []
    for kw in sorted(set(own_by_kw) | set(comp_by_kw)):
        own_rows = own_by_kw.get(kw, [])
        comp_rows = comp_by_kw.get(kw, [])
        own_prices = [l.get("price") for l in own_rows if l.get("price")]
        comp_prices = [l.get("price") for l in comp_rows if l.get("price")]
        # Per-unit band (₹/100 ml · 100 g · piece) — comparable across pack sizes.
        own_unit = _unit_prices(own_rows)
        comp_unit = _unit_prices(comp_rows)
        out.append(PriceRow(
            keyword=kw,
            own_avg=_avg(own_prices),
            own_min=min(own_prices) if own_prices else None,
            own_max=max(own_prices) if own_prices else None,
            own_discount_pct=_avg([l.get("discount_pct") for l in own_rows]),
            comp_avg=_avg(comp_prices),
            comp_min=min(comp_prices) if comp_prices else None,
            comp_median=_median(comp_prices),
            comp_max=max(comp_prices) if comp_prices else None,
            unit_uom=_dominant_uom(own_rows) or _dominant_uom(comp_rows),
            own_avg_unit=_avg(own_unit),
            own_min_unit=min(own_unit) if own_unit else None,
            own_max_unit=max(own_unit) if own_unit else None,
            comp_avg_unit=_avg(comp_unit),
            comp_min_unit=min(comp_unit) if comp_unit else None,
            comp_median_unit=_median(comp_unit),
            comp_max_unit=max(comp_unit) if comp_unit else None,
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


def _catalog_rows(sku_rows, stores_seen: int) -> list[CatalogRow]:
    by_pid: dict[str, list] = defaultdict(list)
    for r in sku_rows:
        by_pid[r.get("product_id") or r.get("name", "")].append(r)

    out: list[CatalogRow] = []
    for pid, rows in by_pid.items():
        found = _stores(rows)
        in_stock = _stores([r for r in rows if r.get("in_stock")])
        prices = [r.get("price") for r in rows if r.get("price")]
        names = Counter(r.get("name") for r in rows if r.get("name"))
        # Pack is constant per product, so the per-unit band divides the price band by
        # the same pack_size (₹/100 ml · 100 g · piece).
        uom = _dominant_uom(rows)
        psize = next((r.get("pack_size") for r in rows if r.get("pack_size")), None)
        out.append(CatalogRow(
            product_id=pid,
            name=(names.most_common(1)[0][0] if names else ""),
            found_stores=len(found),
            in_stock_stores=len(in_stock),
            reach_pct=_pct(len(found), stores_seen),
            distribution_pct=_pct(len(in_stock), len(found)),
            price_min=min(prices) if prices else None,
            price_median=_median(prices),
            price_max=max(prices) if prices else None,
            discount_pct=_avg([r.get("discount_pct") for r in rows]),
            rating=_avg([r.get("rating") for r in rows]),
            is_combo=any(r.get("is_combo") for r in rows),
            pack_size=psize,
            pack_uom=uom,
            unit_price_min=per_unit_price(min(prices), psize, uom) if prices else None,
            unit_price_median=per_unit_price(_median(prices), psize, uom) if prices else None,
            unit_price_max=per_unit_price(max(prices), psize, uom) if prices else None,
        ))
    return sorted(out, key=lambda r: (r.distribution_pct or 0))


# ── Store-grain views (mirroring the client report's sheets) ──────────────────

def _own_rows(result_sku_rows, listings) -> list:
    """The brand's own product readings, store-attributed.

    Catalog mode gives a clean per-product-per-store sweep; keyword-only runs
    have to fall back to the own products that surfaced in searches, which is
    biased by which keywords were asked for. The sheets say which was used.
    """
    return list(result_sku_rows) if result_sku_rows else [l for l in listings if l.get("is_brand")]


def _pid(row: dict) -> str:
    return str(row.get("product_id") or row.get("name") or "")


def _store_scores(own_rows) -> list[StoreScore]:
    catalogue = {_pid(r) for r in own_rows if _pid(r)}
    by_store: dict[str, list] = defaultdict(list)
    for r in own_rows:
        if (m := _store(r)):
            by_store[m].append(r)

    out: list[StoreScore] = []
    for merchant_id, rows in by_store.items():
        carried = {_pid(r) for r in rows if _pid(r)}
        in_stock = {_pid(r) for r in rows if r.get("in_stock") and _pid(r)}
        out.append(StoreScore(
            merchant_id=merchant_id,
            store_type=(next((r.get("merchant_type") for r in rows if r.get("merchant_type")), "") or ""),
            city=(next((r.get("city") for r in rows if r.get("city")), "") or ""),
            products_carried=len(carried),
            products_in_stock=len(in_stock),
            products_out_of_stock=len(carried) - len(in_stock),
            products_missing=max(len(catalogue) - len(carried), 0),
            on_shelf_pct=_pct(len(carried), len(catalogue)),
            in_stock_pct=_pct(len(in_stock), len(carried)),
        ))
    # Worst first: most missing, then most out of stock.
    return sorted(out, key=lambda s: (-s.products_missing, -s.products_out_of_stock))


def _gap_rows(own_rows, cap: int = 5000) -> list[GapRow]:
    """One row per problem: a product a store does not carry, or carries empty.

    Two different problems kept apart — not carried is a listing gap, empty is a
    replenishment gap — exactly as the client report does.
    """
    names: dict[str, str] = {}
    for r in own_rows:
        if (pid := _pid(r)):
            names.setdefault(pid, r.get("name") or pid)
    by_store: dict[str, dict] = defaultdict(dict)
    meta: dict[str, dict] = {}
    for r in own_rows:
        if (m := _store(r)) and (pid := _pid(r)):
            by_store[m][pid] = r
            meta.setdefault(m, {"city": r.get("city") or "", "type": r.get("merchant_type") or ""})

    out: list[GapRow] = []
    for merchant_id, carried in by_store.items():
        info = meta[merchant_id]
        for pid, name in names.items():
            row = carried.get(pid)
            if row is None:
                out.append(GapRow(problem="Not carried", product=name, product_id=pid,
                                  city=info["city"], merchant_id=merchant_id,
                                  store_type=info["type"]))
            elif not row.get("in_stock"):
                out.append(GapRow(problem="Out of stock", product=name, product_id=pid,
                                  city=info["city"], merchant_id=merchant_id,
                                  store_type=info["type"],
                                  units=row.get("inventory"), price=row.get("price")))
    out.sort(key=lambda g: (g.problem, g.city, g.product))
    return out[:cap]


def _grid(snapshots) -> list[GridCell]:
    by: dict[tuple, list] = defaultdict(list)
    for s in snapshots:
        by[(s["keyword"], s.get("city") or "")].append(s)
    return [
        GridCell(keyword=kw, city=city,
                 avg_rank=_avg([s.get("brand_rank") for s in rows]),
                 searches=len(rows))
        for (kw, city), rows in sorted(by.items())
    ]


def _families(own_rows, brand: str, stores_seen: int) -> list[FamilyRow]:
    """Singles plus their multipacks as one product — a repack should not read as
    a loss. Multi-flavour bundles are excluded, never merged."""
    products: dict[str, dict] = {}
    for r in own_rows:
        pid = _pid(r)
        if not pid:
            continue
        p = products.setdefault(pid, {"name": r.get("name") or pid, "stores": set(),
                                      "in_stock": 0, "prices": []})
        if (m := _store(r)):
            p["stores"].add(m)
            p["in_stock"] += bool(r.get("in_stock"))
        if r.get("price") is not None:
            p["prices"].append(r["price"])

    fams: dict[str, dict] = {}
    for p in products.values():
        key = normalise(p["name"], [brand])
        if is_bundle(key):
            continue
        f = fams.setdefault(key, {"variants": [], "stores": set(), "listed": 0,
                                  "in_stock": 0, "prices": []})
        f["variants"].append(p["name"])
        f["stores"] |= p["stores"]            # a union: one store, however many variants
        f["listed"] += len(p["stores"])
        f["in_stock"] += p["in_stock"]
        f["prices"] += p["prices"]

    out = [
        FamilyRow(
            family=label(key),
            variants=len(f["variants"]),
            stores_carrying=len(f["stores"]),
            on_shelf_pct=_pct(len(f["stores"]), stores_seen),
            listings=f["listed"],
            in_stock_pct=_pct(f["in_stock"], f["listed"]),
            price_low=min(f["prices"]) if f["prices"] else None,
            price_high=max(f["prices"]) if f["prices"] else None,
            variant_names=" · ".join(sorted(f["variants"])),
        )
        for key, f in fams.items()
    ]
    return sorted(out, key=lambda r: -(r.on_shelf_pct or 0))


def build_insights(result: ExplorerResult) -> ExplorerInsights:
    spec = result.spec
    snaps = result.snapshots
    listings = result.listings

    keywords = _keyword_scores(snaps, listings)
    geography = _city_scores(snaps, listings)
    competitors = _competitor_scores(listings)

    own = [l for l in listings if l["is_brand"]]
    # Every store that answered anything this run — the honest denominator.
    stores_seen = len(_stores(snaps) | _stores(listings) | _stores(result.sku_rows))
    own_rows = _own_rows(result.sku_rows, listings)
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
        stores_seen=stores_seen,
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
        # ROWS, not products: the same product recurs once per search per store.
        # Labelling this "Products captured" (as the sheet briefly did) overstates
        # a brand's range by orders of magnitude.
        total_listings=len(listings),
        total_products=len({_pid(l) for l in listings if _pid(l)}),
        own_products=len({_pid(l) for l in own if _pid(l)}),
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
        catalog=_catalog_rows(result.sku_rows, stores_seen),
        stores=_store_scores(own_rows),
        gaps=_gap_rows(own_rows),
        grid=_grid(snaps),
        families=_families(own_rows, spec.brand, stores_seen),
    )
