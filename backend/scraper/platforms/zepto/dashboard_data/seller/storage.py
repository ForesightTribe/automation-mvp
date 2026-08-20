"""Upsert Zepto seller rows into Postgres.

Mirrors blinkit/dashboard_data/seller/storage.py — same ON CONFLICT
(upsert_key) DO UPDATE shape, same bind-parameter chunking. No type coercion
layer here, unlike Blinkit's: this parser emits real `date`/`uuid.UUID` objects
rather than strings, so there is nothing to convert.
"""
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zepto_seller import ZeptoSellerProductPerf, ZeptoSellerSalesDaily
from app.utils.logger import logger


async def save_sales_results(
    session: AsyncSession, daily: list[dict], products: list[dict]
) -> int:
    await _upsert(session, ZeptoSellerSalesDaily, daily)
    await _upsert(session, ZeptoSellerProductPerf, products)
    await session.commit()
    logger.info(f"Zepto seller sales saved — days:{len(daily)} products:{len(products)}")
    return len(daily) + len(products)


async def _upsert(session: AsyncSession, model, rows: list[dict]) -> None:
    if not rows:
        return
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
