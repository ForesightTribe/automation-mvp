"""Upsert Zepto seller rows into Postgres.

Mirrors blinkit/dashboard_data/seller/storage.py — same ON CONFLICT
(upsert_key) DO UPDATE shape, same bind-parameter chunking. No type coercion
layer here, unlike Blinkit's: this parser emits real `date`/`uuid.UUID` objects
rather than strings, so there is nothing to convert.
"""
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zepto_seller import (
    ZeptoAdCampaignDaily,
    ZeptoAdBreakdownDaily,
    ZeptoAdKeywordDaily,
    ZeptoAdProductDaily,
    ZeptoSellerProductPerf,
    ZeptoSellerSalesCityDaily,
    ZeptoSellerSalesDaily,
)
from app.utils.logger import logger


async def save_sales_results(
    session: AsyncSession,
    daily: list[dict],
    products: list[dict],
    cities: list[dict] | None = None,
) -> int:
    cities = cities or []
    await _upsert(session, ZeptoSellerSalesDaily, daily)
    await _upsert(session, ZeptoSellerProductPerf, products)
    await _upsert(session, ZeptoSellerSalesCityDaily, cities)
    await session.commit()
    logger.info(
        f"Zepto seller sales saved — days:{len(daily)} products:{len(products)} "
        f"city-days:{len(cities)}"
    )
    return len(daily) + len(products) + len(cities)


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
                set_={c: insert(model).excluded[c] for c in update_cols},
            )
        )
        await session.execute(stmt)


def _update_cols(model) -> list[str]:
    pk = {"id", "upsert_key"}
    return [c.name for c in model.__table__.columns if c.name not in pk]
