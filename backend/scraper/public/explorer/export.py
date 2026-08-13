"""Explorer Excel export — an adapter onto the shared renderer.

`write_workbook(insights, result, path)` keeps its old signature, but no longer
draws anything itself: it maps the typed `ExplorerInsights` onto a `Report` and
hands that to `exports.write_workbook`. Explorer and the client report now
come out of one writer, so a fix to widths, colours or print setup lands in both.

Two things the shared layer changed here, deliberately:

- **The vocabulary is checked.** The old sheets said "SoV %" and "Reach %";
  `glossary.check_wording` rejects both, so they now read "Share of search %" and
  "On shelf %" like everywhere else.
- **Counts are LOCATIONS, not stores.** Explorer samples probe points and never
  resolves them to dark stores, so the client report's store wording would be a
  lie here. The glossary carries a `Location` entry saying exactly that.
"""
import re

from exports import glossary
from exports import write_workbook as _render
from app.schemas.exports import Column, Kpi, MetaItem, Report, Section
from app.schemas.explorer import ExplorerInsights
from scraper.public.explorer.orchestrator import ExplorerResult


def _c(key: str, header: str, type_: str = "text", **kw) -> Column:
    return Column(key=key, header=header, type=type_, **kw)


def _overview(ins: ExplorerInsights) -> Section:
    ov = ins.overview
    return Section(
        key="overview",
        title="Run Overview",
        description="How the brand performed across everything this run searched.",
        context=f"{len(ov.keywords)} search term(s) · "
                f"{ov.stores_seen:,} dark stores seen from {ov.locations_scraped:,} search points · "
                f"{'full census' if ov.full else f'sample of {ov.sample} per city'}",
        kpis=[
            Kpi(label="Share of search", value=ov.overall_sov_pct, type="pct",
                help="Share of the results page taken by this brand's products, across every "
                     "search in the run."),
            Kpi(label="Average position", value=ov.avg_rank, type="rating",
                help="Position 1 is the top of the page — lower is better."),
            Kpi(label="In stock", value=ov.in_stock_pct, type="pct",
                help="Of the brand's products that were found, how many had stock."),
            Kpi(label="Search terms in the top 3", value=ov.keywords_top3, type="count"),
            Kpi(label="Strongest search term", value=ov.strongest_keyword or "—", type="text"),
            Kpi(label="Weakest search term", value=ov.weakest_keyword or "—", type="text"),
            Kpi(label="Strongest city", value=ov.strongest_city or "—", type="text"),
            Kpi(label="Weakest city", value=ov.weakest_city or "—", type="text"),
            Kpi(label="Dark stores seen", value=ov.stores_seen, type="count",
                detail=f"from {ov.locations_scraped:,} search points",
                help="Distinct shops that answered. One search point can be served by "
                     "several stores, so this is not the number of points searched."),
            Kpi(label="Your products found", value=ov.own_products, type="count",
                help="Distinct products of the focus brand seen anywhere in this run."),
            Kpi(label="Competitors found", value=ov.total_competitors, type="count",
                help="Distinct rival brands appearing in these searches."),
            Kpi(label="Product listings captured", value=ov.total_listings, type="count",
                detail=f"{ov.total_products:,} distinct products",
                help="ROWS of search results, not products: the same product is counted "
                     "once per store per search term."),
            Kpi(label="Fetch errors", value=ov.errors, type="count",
                help="Searches that failed outright. A high count means the run under-sampled."),
        ],
        notes=[
            "Counts are DARK STORES, the same unit the client report uses, so the two are "
            "comparable. 'Search points' is how many coordinates we searched from — effort, "
            "not shelf.",
            "This is a one-off scrape of whatever was asked for, not a tracked client feed. "
            "Nothing here is stored, so the captured sheets at the end are the only copy.",
        ],
    )


def _keywords(ins: ExplorerInsights) -> Section | None:
    if not ins.keywords:
        return None
    return Section(
        key="keywords",
        title="Search Visibility",
        description="For each search term, how much of the results page the brand owns and where it sits.",
        context="Position 1 is the top of the page — lower is better",
        columns=[
            _c("keyword", "Search term"),
            _c("searches", "Searches sampled", "count", emphasis="bar",
               help="Individual searches behind this row."),
            _c("stores", "Dark stores", "count",
               help="Distinct shops that answered for this term."),
            _c("avg_rank", "Average position", "rating", emphasis="good_low",
               help="Position 1 is the top of the page — LOWER IS BETTER."),
            _c("best_rank", "Best position", "count"),
            _c("sov_pct", "Share of search %", "pct", emphasis="good_high"),
            _c("presence_pct", "Presence %", "pct", emphasis="good_high",
               help="Locations where the brand appeared at all, out of those searched."),
            _c("in_stock_pct", "In stock %", "pct", emphasis="good_high"),
            _c("competitors", "Competitors", "count"),
            _c("top_competitor", "Top competitor"),
        ],
        rows=[r.model_dump() for r in ins.keywords],
    )


def _geography(ins: ExplorerInsights) -> Section | None:
    if not ins.geography:
        return None
    return Section(
        key="geography",
        title="City Shelf Presence",
        description="The same numbers city by city.",
        columns=[
            _c("city", "City"),
            _c("stores", "Dark stores", "count", emphasis="bar"),
            _c("searches", "Searches sampled", "count"),
            _c("avg_rank", "Average position", "rating", emphasis="good_low"),
            _c("sov_pct", "Share of search %", "pct", emphasis="good_high"),
            _c("in_stock_pct", "In stock %", "pct", emphasis="good_high"),
            _c("keywords", "Search terms", "count"),
        ],
        rows=[r.model_dump() for r in ins.geography],
    )


def _competitors(ins: ExplorerInsights) -> Section | None:
    if not ins.competitors:
        return None
    return Section(
        key="competitors",
        title="Top Competitors",
        description="Every rival brand that appeared in these searches.",
        columns=[
            _c("competitor", "Brand"),
            _c("stores", "Dark stores seen in", "count", emphasis="bar"),
            _c("keywords", "Search terms", "count"),
            _c("appearances", "Appearances", "count"),
            _c("avg_position", "Average position", "rating"),
            _c("avg_price", "Average price", "money"),
            _c("share_pct", "Share of shelf %", "pct",
               help="This brand's slice of every competitor appearance in the run."),
        ],
        rows=[r.model_dump() for r in ins.competitors],
    )


def _pricing(ins: ExplorerInsights) -> Section | None:
    if not ins.pricing:
        return None
    return Section(
        key="pricing",
        title="Price vs Competitors",
        description="The brand's price band against the rest of the shelf, per search term.",
        columns=[
            _c("keyword", "Search term"),
            _c("own_avg", "You — average", "money"),
            _c("own_min", "You — low", "money"),
            _c("own_max", "You — high", "money"),
            _c("own_discount_pct", "Your discount %", "pct"),
            _c("comp_avg", "Market — average", "money"),
            _c("comp_min", "Market — low", "money"),
            _c("comp_median", "Market — typical", "money"),
            _c("comp_max", "Market — high", "money"),
            _c("unit_uom", "Per-unit basis", width=14),
            _c("own_avg_unit", "You per unit", "money_fine",
               help="Price normalised by pack size — the fair comparison across pack sizes."),
            _c("own_min_unit", "You per unit — low", "money_fine"),
            _c("own_max_unit", "You per unit — high", "money_fine"),
            _c("comp_avg_unit", "Market per unit", "money_fine"),
            _c("comp_median_unit", "Market per unit — typical", "money_fine"),
            _c("comp_max_unit", "Market per unit — high", "money_fine"),
        ],
        rows=[r.model_dump() for r in ins.pricing],
    )


def _availability(ins: ExplorerInsights) -> Section | None:
    if not ins.availability:
        return None
    return Section(
        key="availability",
        title="Availability",
        description="Where the brand's products were found but empty.",
        columns=[
            _c("keyword", "Search term"),
            _c("city", "City"),
            _c("own_found", "Products found", "count"),
            _c("own_in_stock", "With stock", "count"),
            _c("in_stock_pct", "In stock %", "pct", emphasis="good_high"),
        ],
        rows=[r.model_dump() for r in ins.availability],
    )


def _product_shelf(ins: ExplorerInsights) -> Section | None:
    """Sheet: every own product and how widely it is carried — the client
    report's Product Shelf Presence, at the same grain."""
    if not ins.catalog:
        return None
    return Section(
        key="product_shelf",
        title="Product Shelf Presence",
        description="Every product of the focus brand: how many stores carry it, and how many had stock.",
        columns=[
            _c("name", "Product"),
            _c("product_id", "Product ID", "id"),
            _c("found_stores", "Stores carrying it", "count", emphasis="bar",
               help="Distinct dark stores where this product appeared at all."),
            _c("in_stock_stores", "Stores with stock", "count"),
            _c("reach_pct", "On shelf %", "pct", emphasis="good_high",
               help="Stores carrying it divided by stores seen in this run."),
            _c("distribution_pct", "In stock %", "pct", emphasis="good_high",
               help="Of the stores carrying it, how many had stock."),
            _c("discount_pct", "Discount %", "pct"),
            _c("rating", "Rating", "rating"),
            _c("is_combo", "Multipack", width=12),
        ],
        rows=[r.model_dump() for r in ins.catalog],
        notes=["Sampled run: the denominator is the stores this run saw, not every store "
               "on the platform."],
    )


def _price_spread(ins: ExplorerInsights) -> Section | None:
    """Sheet: what each product sells for and how far it varies between stores."""
    if not ins.catalog:
        return None
    rows = []
    for r in ins.catalog:
        d = r.model_dump()
        d["spread"] = (round(r.price_max - r.price_min, 2)
                       if r.price_min is not None and r.price_max is not None else None)
        rows.append(d)
    rows.sort(key=lambda r: -(r["spread"] or 0))
    return Section(
        key="price_spread",
        title="Price Spread",
        description="What each product sells for, and how far prices vary between stores.",
        columns=[
            _c("name", "Product"),
            _c("product_id", "Product ID", "id"),
            _c("found_stores", "Stores priced", "count"),
            _c("price_min", "Cheapest", "money"),
            _c("price_median", "Typical", "money"),
            _c("price_max", "Dearest", "money"),
            _c("spread", "Spread", "money", emphasis="good_low",
               help="Dearest minus cheapest — how differently the same product is priced "
                    "depending on which store serves the customer."),
            _c("pack_size", "Pack", "rating"),
            _c("pack_uom", "Unit", width=10),
            _c("unit_price_min", "Per unit — low", "money_fine"),
            _c("unit_price_median", "Per unit — typical", "money_fine",
               help="Price normalised by pack size, so different pack sizes compare fairly."),
            _c("unit_price_max", "Per unit — high", "money_fine"),
        ],
        rows=rows,
        notes=["Widest spread first."],
    )


def _stores(ins: ExplorerInsights) -> Section | None:
    """Sheet: per dark store — which shops carry the range and which do not."""
    if not ins.stores:
        return None
    return Section(
        key="store_shelf",
        title="Store Shelf Presence",
        description="Every dark store seen, worst first — where the range is thinnest.",
        columns=[
            _c("merchant_id", "Store ID", "id"),
            _c("city", "City"),
            _c("store_type", "Store tier",
               help="Express stores hold the 10-minute core range; hub stores carry extended "
                    "range more slowly."),
            _c("products_carried", "Products carried", "count", emphasis="bar"),
            _c("products_in_stock", "With stock", "count"),
            _c("products_out_of_stock", "Out of stock", "count", emphasis="good_low"),
            _c("products_missing", "Not carried", "count", emphasis="good_low",
               help="Products seen elsewhere in this run that this store does not carry."),
            _c("on_shelf_pct", "On shelf %", "pct", emphasis="good_high"),
            _c("in_stock_pct", "In stock %", "pct", emphasis="good_high"),
        ],
        rows=[r.model_dump() for r in ins.stores],
        notes=[
            "Sorted worst first: most products not carried, then most out of stock.",
            "'Not carried' is measured against the products this run saw anywhere — an "
            "observed range, not a configured product list.",
        ],
    )


def _gaps(ins: ExplorerInsights) -> Section | None:
    """Sheet: the work queue — one row per product per store with a problem."""
    if not ins.gaps:
        return None
    return Section(
        key="needs_attention",
        title="Needs Attention",
        description="Every gap worth acting on, one row per store and product.",
        context=f"{len(ins.gaps):,} problems",
        columns=[
            _c("product", "Product"),
            _c("problem", "Problem", width=15,
               chips={"Not carried": "bad", "Out of stock": "warn"},
               help="'Not carried' is a listing gap (commercial). 'Out of stock' is a "
                    "replenishment gap (supply). Filter this column before acting."),
            _c("city", "City"),
            _c("merchant_id", "Store ID", "id"),
            _c("store_type", "Store tier"),
            _c("units", "Units left", "count",
               help="Blank for 'Not carried' — the product is absent, so there is no stock figure."),
            _c("price", "Price", "money"),
        ],
        rows=[r.model_dump() for r in ins.gaps],
        notes=[
            "Two different problems in one filterable list — they go to different teams and "
            "must never be added together.",
        ],
    )


def _grid(ins: ExplorerInsights) -> Section | None:
    """Sheet: average position per search term and city — the weakness map."""
    if not ins.grid:
        return None
    cities = sorted({c.city for c in ins.grid})
    keywords = sorted({c.keyword for c in ins.grid})
    lookup = {(c.keyword, c.city): c.avg_rank for c in ins.grid}

    def key(city: str) -> str:
        return "c_" + re.sub(r"[^a-z0-9]+", "_", city.lower()).strip("_")

    rows = [{"keyword": kw, **{key(c): lookup.get((kw, c)) for c in cities}} for kw in keywords]
    return Section(
        key="rank_grid",
        title="Position by Search Term and City",
        description="Where the brand ranks for each term in each city — the map of where it is weak.",
        context="average position · 1 is the top of the page",
        columns=[_c("keyword", "Search term")] + [
            _c(key(c), c.title(), "rating", emphasis="heat",
               help=f"Average position in {c.title()}. Position 1 is the top of the page.")
            for c in cities
        ],
        rows=rows,
        notes=[
            "Green is a strong position, red is weak — LOW numbers are good, and the colours "
            "follow that rather than the number.",
            "A blank cell means the brand did not appear for that term in that city.",
        ],
    )


def _families(ins: ExplorerInsights) -> Section | None:
    """Sheet: singles plus their multipacks, counted as one product."""
    if not ins.families:
        return None
    multi = sum(1 for f in ins.families if f.variants > 1)
    notes = [
        "'Stores carrying any' counts each store once however many variants it stocks, so it "
        "is never the sum of the per-product figures.",
        "Families are worked out from the product name, not a configured list — the last "
        "column shows exactly what was grouped.",
    ]
    notes.insert(0, f"{multi} of {len(ins.families)} families have more than one variant."
                 if multi else
                 "Every family here has one variant — this brand has no same-flavour "
                 "multipacks in what was scraped.")
    return Section(
        key="product_families",
        title="Product Families",
        description="Each product with its multipacks counted together, so a repack does not look like a loss.",
        columns=[
            _c("family", "Product family"),
            _c("variants", "Variants", "count"),
            _c("stores_carrying", "Stores carrying any", "count", emphasis="bar"),
            _c("on_shelf_pct", "On shelf %", "pct", emphasis="good_high"),
            _c("listings", "Store-product listings", "count"),
            _c("in_stock_pct", "In stock %", "pct", emphasis="good_high"),
            _c("price_low", "Cheapest variant", "money"),
            _c("price_high", "Dearest variant", "money"),
            _c("variant_names", "What was grouped", wrap=True, width=46),
        ],
        rows=[r.model_dump() for r in ins.families],
        notes=notes,
    )


# ── Captured rows ─────────────────────────────────────────────────────────────
# Explorer is ephemeral: nothing it scrapes is stored, so the workbook is the
# only copy and the captured rows have to ride along. They are `dense` — long
# sheets get headers, widths and freeze but no per-cell painting.

def _snapshots(result: ExplorerResult) -> Section | None:
    if not result.snapshots:
        return None
    return Section(
        key="captured_searches",
        title="Captured — Searches",
        description="One row per search at one location.",
        dense=True,
        columns=[
            _c("keyword", "Search term"), _c("city", "City"), _c("zone", "Zone"),
            _c("lat", "Latitude", "rating"), _c("lon", "Longitude", "rating"),
            _c("merchant_id", "Store ID", "id"),
            _c("total_results", "Results on page", "count"),
            _c("brand_rank", "Your position", "count"),
            _c("brand_sov_pct", "Share of search %", "pct"),
            _c("brand_product_count", "Your products", "count"),
        ],
        rows=result.snapshots,
    )


def _listings(result: ExplorerResult) -> Section | None:
    if not result.listings:
        return None
    return Section(
        key="captured_products",
        title="Captured — Products",
        description="Every product seen on every results page, yours and competitors'.",
        dense=True,
        columns=[
            _c("keyword", "Search term"), _c("city", "City"),
            _c("lat", "Latitude", "rating"), _c("lon", "Longitude", "rating"),
            _c("position", "Position", "count"), _c("merchant_id", "Store ID", "id"),
            _c("name", "Product"), _c("brand", "Brand"), _c("is_brand", "Yours?", width=10),
            _c("brand_slug", "Brand key", "id"),
            _c("price", "Price", "money"), _c("mrp", "MRP", "money"),
            _c("discount_pct", "Discount %", "pct"),
            _c("in_stock", "In stock", width=10), _c("inventory", "Units", "count"),
            _c("product_id", "Product ID", "id"), _c("unit", "Pack"),
            _c("pack_size", "Pack size", "rating"), _c("pack_uom", "Unit", width=10),
            _c("pack_count", "Items in pack", "count"), _c("rating", "Rating", "rating"),
            _c("product_state", "State"), _c("l0", "Category"), _c("l1", "Sub-category"),
            _c("l2", "Group"), _c("merchant_type", "Store tier"),
            _c("is_combo", "Multipack", width=12),
        ],
        rows=result.listings,
    )


def _catalog_rows(result: ExplorerResult) -> Section | None:
    if not result.sku_rows:
        return None
    return Section(
        key="captured_catalogue",
        title="Captured — Own Catalogue",
        description="Every own-product reading, one row per product per location.",
        dense=True,
        columns=[
            _c("name", "Product"), _c("product_id", "Product ID", "id"),
            _c("city", "City"), _c("lat", "Latitude", "rating"), _c("lon", "Longitude", "rating"),
            _c("merchant_id", "Store ID", "id"), _c("merchant_type", "Store tier"),
            _c("price", "Price", "money"), _c("mrp", "MRP", "money"),
            _c("discount_pct", "Discount %", "pct"), _c("unit", "Pack"),
            _c("pack_size", "Pack size", "rating"), _c("pack_uom", "Unit", width=10),
            _c("pack_count", "Items in pack", "count"),
            _c("in_stock", "In stock", width=10), _c("inventory", "Units", "count"),
            _c("rating", "Rating", "rating"), _c("is_combo", "Multipack", width=12),
        ],
        rows=result.sku_rows,
    )


def _locations(result: ExplorerResult) -> Section | None:
    seen: dict[tuple, dict] = {}
    for r in result.snapshots + result.sku_rows:
        seen.setdefault((r.get("lat"), r.get("lon")), {
            "city": r.get("city"), "zone": r.get("zone"), "pincode": r.get("pincode"),
            "lat": r.get("lat"), "lon": r.get("lon"),
        })
    if not seen:
        return None
    return Section(
        key="captured_locations",
        title="Captured — Locations",
        description="The points this run searched from.",
        dense=True,
        columns=[
            _c("city", "City"), _c("zone", "Zone"), _c("pincode", "Pincode", "id"),
            _c("lat", "Latitude", "rating"), _c("lon", "Longitude", "rating"),
        ],
        rows=list(seen.values()),
    )


def _report(insights: ExplorerInsights, result: ExplorerResult) -> Report:
    ov = insights.overview
    # Sheet order mirrors the client report so the two read the same way.
    sections = [
        _overview(insights),          # Shelf summary
        _product_shelf(insights),     # per product
        _geography(insights),         # per city
        _stores(insights),            # per store
        _gaps(insights),              # the work queue
        _families(insights),          # variants rolled up
        _price_spread(insights),      # per product price band
        _keywords(insights),          # search visibility
        _grid(insights),              # position grid
        _competitors(insights),       # who else is on the shelf
        _pricing(insights),           # price vs competitors
        _availability(insights),      # keyword x city availability (Explorer-only)
        _snapshots(result), _listings(result), _catalog_rows(result), _locations(result),
    ]
    return Report(
        title=f"{ov.brand.title()} — Market Explorer",
        subtitle=f"{ov.marketplace.title()} · one-off scrape · "
                 f"{ov.generated_at:%d %b %Y, %H:%M}"
                 + (f" · {ov.label}" if ov.label else ""),
        filename_stem=f"{ov.brand}_explorer",
        generated_at=ov.generated_at,
        meta=[
            MetaItem(label="Brand", value=ov.brand),
            MetaItem(label="Marketplace", value=ov.marketplace.title()),
            MetaItem(label="Mode", value=ov.mode),
            MetaItem(label="Label", value=ov.label or "—"),
            MetaItem(label="Search terms", value=", ".join(ov.keywords) or "—"),
            MetaItem(label="Cities", value=", ".join(ov.cities) or "every city in the catalogue"),
            MetaItem(label="Locations searched", value=ov.locations_scraped,
                     note="points searched from, not shops"),
            MetaItem(label="Sampling", value="full census" if ov.full else f"{ov.sample} per city"),
            MetaItem(label="Scraped", value=f"{ov.generated_at:%d %b %Y, %H:%M}",
                     note="live at the time of this run"),
        ],
        sections=[s for s in sections if s is not None],
        # No "stores observed" or "freshness": Explorer counts locations and is
        # scraped live, so the client report's core terms would mislead here.
        # Store terms now apply: Explorer counts dark stores, same as the client
        # report. `probe_location` stays because the cover still quotes search
        # points; `freshness` is dropped because this is scraped live.
        glossary=glossary.collect(
            "on_shelf", "in_stock", "stores_observed", "store_tier",
            "share_of_search", "position", "unit_price", "discount",
            "main_vs_combo", "probe_location",
            core=(),
        ),
    )


def write_workbook(insights: ExplorerInsights, result: ExplorerResult, path: str) -> str:
    """Render the run to an .xlsx at `path`. Returns `path`."""
    return _render(_report(insights, result), path)
