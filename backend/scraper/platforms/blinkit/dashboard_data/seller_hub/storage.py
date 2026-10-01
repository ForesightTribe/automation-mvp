import uuid
from datetime import date as date_cls, datetime as datetime_cls

from sqlalchemy import Date, DateTime, String, Uuid
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel.sql.sqltypes import AutoString

from app.models.blinkit_seller_hub import (
    BlinkitSellerHubSalesByProductRO,
    BlinkitSellerHubSalesOrderRO,
)
from app.utils.logger import logger

# BlinkitSellerHubSalesDailyRO / CityDailyRO / CategoryDailyRO are no longer
# written here (scope narrowed 2026-10-01 — see scraper.py's module
# docstring: they're fully derivable from BlinkitSellerHubSalesOrderRO now).
# Their tables and any rows from past runs are left in the database
# untouched; this module just doesn't import or upsert into them anymore.


async def save_sales_results(
    session: AsyncSession, by_product: list[dict], orders: list[dict] | None = None,
) -> int:
    written = 0
    written += await _upsert(session, BlinkitSellerHubSalesByProductRO, by_product)
    if orders:
        written += await _upsert(session, BlinkitSellerHubSalesOrderRO, orders)
    await session.commit()
    logger.info(
        f"Blinkit seller-hub sales saved — by_product:{len(by_product)} orders:{len(orders or [])}"
    )
    return written


# Identical to scraper/platforms/blinkit/dashboard_data/seller/storage.py's
# _upsert/_prepare — duplicated rather than imported because that module is
# scoped to its own model set (app/models/blinkit_seller.py) and the two are
# small enough that sharing a helper isn't worth a cross-module dependency.
async def _upsert(session: AsyncSession, model, rows: list[dict]) -> int:
    """Returns rows actually inserted-or-updated (Postgres's own rowcount per
    chunk), not len(rows) — the parsed count can be higher than what lands if
    two parsed rows ever share an upsert_key, which len(rows) would hide."""
    if not rows:
        return 0
    prepared = [_prepare(model, r) for r in rows]
    cols = max(1, len(model.__table__.columns))
    chunk = max(1, 32000 // cols)
    update_cols = _update_cols(model)
    affected = 0
    for i in range(0, len(prepared), chunk):
        stmt = (
            insert(model)
            .values(prepared[i:i + chunk])
            .on_conflict_do_update(
                index_elements=["upsert_key"],
                set_={c: insert(model).excluded[c] for c in update_cols},
            )
        )
        result = await session.execute(stmt)
        affected += result.rowcount
    return affected


def _prepare(model, row: dict) -> dict:
    data = dict(row)
    for col in model.__table__.columns:
        if col.name not in data:
            continue
        val = data[col.name]
        if val is None:
            continue
        if isinstance(col.type, Uuid):
            if isinstance(val, str):
                data[col.name] = uuid.UUID(val)
        elif isinstance(col.type, DateTime):
            if isinstance(val, str) and val:
                data[col.name] = _parse_dt(val)
        elif isinstance(col.type, Date):
            if isinstance(val, str) and val:
                data[col.name] = date_cls.fromisoformat(val)
        elif isinstance(col.type, (String, AutoString)):
            if not isinstance(val, str):
                data[col.name] = str(val)
    return data


def _parse_dt(val: str) -> datetime_cls:
    dt = datetime_cls.fromisoformat(val.replace("Z", "+00:00"))
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _update_cols(model) -> list[str]:
    pk = {"id", "upsert_key"}
    return [c.name for c in model.__table__.columns if c.name not in pk]
