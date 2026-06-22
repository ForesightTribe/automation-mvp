import uuid
from datetime import date as date_cls, datetime as datetime_cls

from sqlalchemy import Date, DateTime, String, Uuid
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel.sql.sqltypes import AutoString

from app.models.blinkit_seller import (
    BlinkitPO,
    BlinkitPOItem,
    BlinkitPOSnapshot,
    BlinkitSOH,
    BlinkitScorecardFacility,
    BlinkitScorecardKeySku,
    BlinkitScorecardWeekly,
    BlinkitSellerSale,
    BlinkitSellerSalesSummary,
)
from app.utils.logger import logger


async def save_scrape_results(session: AsyncSession, sales: list[dict], summary: dict) -> int:
    await _upsert(session, BlinkitSellerSale, sales)
    await _upsert(session, BlinkitSellerSalesSummary, [summary])
    await session.commit()
    logger.info(f"Blinkit seller sales saved — rows:{len(sales)} summary:1")
    return len(sales) + 1


async def save_po_results(
    session: AsyncSession, pos: list[dict], items: list[dict], snapshot: dict
) -> int:
    await _upsert(session, BlinkitPO, pos)
    await _upsert(session, BlinkitPOItem, items)
    await _upsert(session, BlinkitPOSnapshot, [snapshot])
    await session.commit()
    logger.info(f"Blinkit PO saved — pos:{len(pos)} items:{len(items)} snapshot:1")
    return len(pos) + len(items) + 1


async def save_soh_results(session: AsyncSession, rows: list[dict]) -> int:
    await _upsert(session, BlinkitSOH, rows)
    await session.commit()
    logger.info(f"Blinkit SOH saved — rows:{len(rows)}")
    return len(rows)


async def save_scorecard_results(
    session: AsyncSession,
    weekly: dict,
    facilities: list[dict],
    key_skus: list[dict],
) -> int:
    await _upsert(session, BlinkitScorecardWeekly, [weekly])
    await _upsert(session, BlinkitScorecardFacility, facilities)
    await _upsert(session, BlinkitScorecardKeySku, key_skus)
    await session.commit()
    logger.info(
        f"Blinkit scorecard saved — weekly:1 facilities:{len(facilities)} skus:{len(key_skus)}"
    )
    return 1 + len(facilities) + len(key_skus)


async def _upsert(session: AsyncSession, model, rows: list[dict]) -> None:
    if not rows:
        return
    prepared = [_prepare(model, r) for r in rows]
    # Postgres caps bind parameters per statement at 32767 (one per column per
    # row). Use the table's full column count as a safe upper bound — SQLAlchemy
    # also binds columns with Python-side defaults (platform, scraped_at) that
    # aren't in the parser dict, so the dict's key count underestimates it.
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
    """Coerce raw parser values to the types asyncpg expects per column.

    Parsers emit convenient Python values (str UUIDs, "YYYY-MM-DD" date strings
    reused in the upsert key, ISO timestamp strings from the API, int ids), but
    asyncpg binds strictly by column type: UUID columns need uuid.UUID, DATE
    needs date, TIMESTAMP needs datetime, and VARCHAR needs str. Coerce based on
    the column's SQL type so every model is covered.
    """
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
        elif isinstance(col.type, DateTime):  # check before Date (distinct types)
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
    """Parse an API ISO timestamp to a naive datetime, preserving the source
    value as-is (UTC) — scraped business timestamps are never shifted to IST."""
    dt = datetime_cls.fromisoformat(val.replace("Z", "+00:00"))
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _update_cols(model) -> list[str]:
    pk = {"id", "upsert_key"}
    return [c.name for c in model.__table__.columns if c.name not in pk]
