import uuid
from datetime import date as date_cls, datetime as datetime_cls

from sqlalchemy import Date, DateTime, String, Uuid
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel.sql.sqltypes import AutoString

from app.models.blinkit_marketing import (
    AdCampaign,
    AdPerformanceSummary,
    BrandCollection,
    SponsoredSOV,
    VisibilityPlan,
)
from app.utils.logger import logger


async def save_scrape_results(
    session: AsyncSession,
    summary: dict,
    campaigns: list[dict],
    sov: list[dict],
    collections: list[dict],
    plans: list[dict],
) -> int:
    await _upsert(session, AdPerformanceSummary, [summary])
    await _upsert(session, AdCampaign, campaigns)
    await _upsert(session, SponsoredSOV, sov)
    await _upsert(session, BrandCollection, collections)
    await _upsert(session, VisibilityPlan, plans)
    await session.commit()

    total = 1 + len(campaigns) + len(sov) + len(collections) + len(plans)
    logger.info(
        f"Blinkit marketing saved — summary:1 campaigns:{len(campaigns)} "
        f"sov:{len(sov)} collections:{len(collections)} plans:{len(plans)}"
    )
    return total


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
