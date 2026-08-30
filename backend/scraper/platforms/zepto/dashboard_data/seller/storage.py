"""Upsert Zepto seller rows into Postgres.

Mirrors blinkit/dashboard_data/seller/storage.py — same ON CONFLICT
(upsert_key) DO UPDATE shape, same bind-parameter chunking. No type coercion
layer here, unlike Blinkit's: this parser emits real `date`/`uuid.UUID` objects
rather than strings, so there is nothing to convert.
"""
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zepto_seller import (
    ZeptoASN,
    ZeptoGRN,
    ZeptoPO,
    ZeptoPOItem,
    ZeptoAdCampaignDaily,
    ZeptoAdBreakdownDaily,
    ZeptoAdKeywordDaily,
    ZeptoAdProductDaily,
    ZeptoSellerProductCityDaily,
    ZeptoSellerSales,
    ZeptoSellerSalesSummary,
)
from app.utils.logger import logger


async def save_sales_results(
    session: AsyncSession,
    daily: list[dict],
    products: list[dict],
    product_cities: list[dict] | None = None,
) -> int:
    # SKU x city x day. A finer grain than `products` (SKU x day, all cities)
    # and deliberately its own table — see ZeptoSellerProductCityDaily. The two
    # hold the same money at different resolutions; never sum across them.
    product_cities = product_cities or []
    await _upsert(session, ZeptoSellerSalesSummary, daily)
    await _upsert(session, ZeptoSellerSales, products)
    await _upsert(session, ZeptoSellerProductCityDaily, product_cities)
    await session.commit()
    logger.info(
        f"Zepto seller sales saved — days:{len(daily)} products:{len(products)} "
        f"product-city-days:{len(product_cities)}"
    )
    return len(daily) + len(products) + len(product_cities)


async def save_ad_results(
    session: AsyncSession,
    campaigns: list[dict],
    keywords: list[dict] | None = None,
    products: list[dict] | None = None,
    breakdown: list[dict] | None = None,
) -> dict[str, int]:
    """Returns rows actually written per table — i.e. after duplicates are
    collapsed, not the length of the input. Reporting the input length made a
    run that fetched the same campaigns under three category tabs claim 390
    rows and triple the real spend."""
    keywords = keywords or []
    products = products or []
    breakdown = breakdown or []
    written = {
        "campaigns": len({r["upsert_key"] for r in campaigns}),
        "keywords": len({r["upsert_key"] for r in keywords}),
        "products": len({r["upsert_key"] for r in products}),
        "breakdown": len({r["upsert_key"] for r in breakdown}),
    }
    await _upsert(session, ZeptoAdCampaignDaily, campaigns)
    await _upsert(session, ZeptoAdKeywordDaily, keywords)
    await _upsert(session, ZeptoAdProductDaily, products)
    await _upsert(session, ZeptoAdBreakdownDaily, breakdown)
    await session.commit()
    logger.info(
        "Zepto ads saved — " + " ".join(f"{k}:{v}" for k, v in written.items())
    )
    return written


# Columns a re-scrape must never blank out.
#
# `zepto_seller_sales` rows are keyed on the SALES date, but these three
# columns are not facts about that date — they carry the same value on every day
# of the window a scrape covered, because they describe the moment of the CALL.
# Re-scraping an older window returns null for them, and a plain upsert then
# writes that null over a real reading.
#
# Which columns belong here was measured, not assumed. For each column, count
# the (scrape_job, sku) groups whose value varies across the days in that job:
#
#     stock_on_hand           0/14   constant within a job  -> snapshot
#     week_on_week_growth     0/33   constant within a job  -> snapshot
#     month_on_month_growth   0/34   constant within a job  -> snapshot
#     available_stores       18/34   varies by day          -> FACT, not listed
#     sales_contribution     18/34   varies by day          -> FACT, not listed
#     gmv / qty_sold         18/34   varies by day          -> FACT, obviously
#
# `available_stores` was in this list until 2026-08-28, on the strength of one
# 88.52% -> 55.98% comparison. That comparison spanned six days AND two scrape
# jobs, so it never isolated the variable; the per-job test above shows it moves
# with the sales date exactly like gmv. It belongs with sales, and guarding it
# here would have been harmless but wrong — a claim someone would later inherit.
#
# What the guard prevents, observed 2026-08-27: re-scraping 21-Aug and 26-Aug
# (for an unrelated city sweep) wiped stock on every row of both days — 16 rows,
# 0 retained. Batches scraped once still held 89% and 68% coverage. The value
# cannot be re-fetched afterwards: the moment has passed.
#
# COALESCE keeps what we already have when the incoming value is null. It does
# NOT block a genuine update — a non-null reading still overwrites.
#
# Longer term these belong in a snapshot table keyed on the scrape JOB rather
# than the sales date. Deliberately NOT built yet: whether the two growth
# columns are scrape-time readings or window-level aggregates is still unproven.
# Stored data cannot settle it — the upsert overwrites in place, so no SKU-day
# has ever had two rows to compare. That needs a live experiment; see
# docs/zepto.md. This guard is the containment until then.
_KEEP_IF_NULL: dict[str, tuple[str, ...]] = {
    "zepto_seller_sales": (
        "stock_on_hand",
        "week_on_week_growth",
        "month_on_month_growth",
    ),
}


async def _upsert(session: AsyncSession, model, rows: list[dict]) -> None:
    if not rows:
        return

    # Collapse rows sharing an upsert_key before they reach Postgres.
    # ON CONFLICT DO UPDATE cannot touch the same row twice in one statement
    # ("command cannot affect row a second time"), and Zepto's ads endpoint
    # makes that easy to hit: `--category all` returns the same campaign under
    # more than one tab, and those rows now key on campaign+date alone. Last
    # write wins, which for ads means the last category fetched supplies the
    # `campaign_category` label — the metrics are identical either way.
    if rows and "upsert_key" in rows[0]:
        deduped = {r["upsert_key"]: r for r in rows}
        if len(deduped) != len(rows):
            logger.info(
                f"{model.__tablename__}: collapsed {len(rows) - len(deduped)} duplicate "
                f"upsert_key row(s) before insert"
            )
        rows = list(deduped.values())

    # Every row in a batch must carry the same keys. A multi-row
    # INSERT ... VALUES binds one parameter set per row, so SQLAlchemy rejects a
    # ragged batch with "INSERT value for column X is explicitly rendered as a
    # boundparameter in the VALUES clause" — which reads like a type problem and
    # names only one column. Fail here instead, naming the columns that actually
    # disagree.
    shape = set(rows[0])
    for r in rows[1:]:
        if set(r) != shape:
            missing = shape - set(r)
            extra = set(r) - shape
            raise ValueError(
                f"{model.__tablename__}: rows in one batch have different columns — "
                f"missing from a later row: {sorted(missing) or 'none'}; "
                f"unexpected in it: {sorted(extra) or 'none'}. Every parser row "
                f"must carry the full key set, using None for absent values."
            )

    # Postgres caps bind parameters per statement at 32767 (one per column per
    # row). Use the table's full column count as the bound — SQLAlchemy also
    # binds columns with Python-side defaults that aren't in the parser dict.
    cols = max(1, len(model.__table__.columns))
    chunk = max(1, 32000 // cols)
    update_cols = _update_cols(model)
    for i in range(0, len(rows), chunk):
        stmt = (
            insert(model)
            .values(rows[i:i + chunk])
            .on_conflict_do_update(
                index_elements=["upsert_key"],
                set_={
                    c: (
                        func.coalesce(
                            insert(model).excluded[c], getattr(model, c)
                        )
                        if c in _KEEP_IF_NULL.get(model.__tablename__, ())
                        else insert(model).excluded[c]
                    )
                    for c in update_cols
                },
            )
        )
        await session.execute(stmt)


def _update_cols(model) -> list[str]:
    pk = {"id", "upsert_key"}
    return [c.name for c in model.__table__.columns if c.name not in pk]


async def save_po_results(
    session: AsyncSession,
    pos: list[dict],
    grns: list[dict],
    asns: list[dict],
    po_items: list[dict] | None = None,
) -> dict[str, int]:
    """Upsert the PO-management tables. Returns rows written per table.

    A PO is keyed on its own id (not id+date), so re-scraping an overlapping
    window UPDATES status and received quantity in place — which is the point:
    a PO issued today is PENDING_ACKNOWLEDGEMENT and receives stock over the
    following weeks, and we want the current state, not a row per observation.
    """
    await _upsert(session, ZeptoPO, pos)
    await _upsert(session, ZeptoGRN, grns)
    await _upsert(session, ZeptoASN, asns)
    await _upsert(session, ZeptoPOItem, po_items or [])
    await session.commit()
    written = {"pos": len(pos), "grns": len(grns), "asns": len(asns),
               "po_items": len(po_items or [])}
    logger.info(
        f"Zepto PO saved — pos:{written['pos']} grns:{written['grns']} "
        f"asns:{written['asns']} items:{written['po_items']}"
    )
    return written
