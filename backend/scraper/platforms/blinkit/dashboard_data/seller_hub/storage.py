import uuid
from datetime import date as date_cls, datetime as datetime_cls

from sqlalchemy import Date, DateTime, String, Uuid
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel.sql.sqltypes import AutoString

from app.models.blinkit_seller_hub import (
    BlinkitSellerHubSalesDailyRO,
    BlinkitSellerHubSalesByProductRO,
    BlinkitSellerHubSalesCityDailyRO,
    BlinkitSellerHubSalesCategoryDailyRO,
)
from app.utils.logger import logger


async def save_sales_results(
    session: AsyncSession,
    daily: list[dict],
    by_product: list[dict],
    by_city: list[dict] | None = None,
    by_category: list[dict] | None = None,
) -> int:
    await _upsert(session, BlinkitSellerHubSalesDailyRO, daily)
    await _upsert(session, BlinkitSellerHubSalesByProductRO, by_product)
    if by_city:
        await _upsert(session, BlinkitSellerHubSalesCityDailyRO, by_city)
    if by_category:
        await _upsert(session, BlinkitSellerHubSalesCategoryDailyRO, by_category)
    await session.commit()
    logger.info(
        f"Blinkit seller-hub sales saved — daily:{len(daily)} by_product:{len(by_product)} "
        f"by_city:{len(by_city or [])} by_category:{len(by_category or [])}"
    )
    return len(daily) + len(by_product) + len(by_city or []) + len(by_category or [])


# Identical to scraper/platforms/blinkit/dashboard_data/seller/storage.py's
# _upsert/_prepare — duplicated rather than imported because that module is
# scoped to its own model set (app/models/blinkit_seller.py) and the two are
# small enough that sharing a helper isn't worth a cross-module dependency.
async def _upsert(session: AsyncSession, model, rows: list[dict]) -> None:
    if not rows:
        return
    prepared = [_prepare(model, r) for r in rows]
    cols = max(1, len(model.__table__.columns))
    chunk = max(1, 32000 // cols)
    update_cols = _update_cols(model)
    for i in range(0, len(prepared), chunk):
        stmt = (
            insert(model)
            .values(prepared[i:i + chunk])
            .on_conflict_do_update(
                index_elements=["upsert_key"],
                set_={c: insert(model).excluded[c] for c in update_cols},
            )
        )
        await session.execute(stmt)


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
