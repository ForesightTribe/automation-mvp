import uuid
from datetime import date as date_cls, datetime as datetime_cls

from sqlalchemy import Date, DateTime, Float, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel.sql.sqltypes import AutoString

from app.models.blinkit_marketing import (
    BlinkitAdCampaign,
    BlinkitAdCampaignDaily,
    BlinkitAdCampaignDetail,
    BlinkitAdCampaignKeyword,
    BlinkitBrandCollection,
    BlinkitSponsoredSOV,
    BlinkitVisibilityPlan,
)
from app.utils.logger import logger


async def save_scrape_results(
    session: AsyncSession,
    campaigns: list[dict],
    daily: list[dict],
    detail: list[dict],
    sov: list[dict],
    collections: list[dict],
    plans: list[dict],
    keywords: list[dict] | None = None,
) -> int:
    await _upsert(session, BlinkitAdCampaign, campaigns)
    await _upsert(session, BlinkitAdCampaignDaily, daily)
    await _upsert(session, BlinkitAdCampaignDetail, detail)
    await _upsert(session, BlinkitAdCampaignKeyword, keywords or [])
    await _upsert(session, BlinkitSponsoredSOV, sov)
    await _upsert(session, BlinkitBrandCollection, collections)
    await _upsert(session, BlinkitVisibilityPlan, plans)
    await session.commit()

    total = (
        len(campaigns) + len(daily) + len(detail) + len(keywords or [])
        + len(sov) + len(collections) + len(plans)
    )
    logger.info(
        f"Blinkit marketing saved — campaigns:{len(campaigns)} daily:{len(daily)} "
        f"detail:{len(detail)} keyword_bids:{len(keywords or [])} sov:{len(sov)} "
        f"collections:{len(collections)} plans:{len(plans)}"
    )
    return total


async def _upsert(session: AsyncSession, model, rows: list[dict]) -> None:
    if not rows:
        return
    prepared = [prepare_row(model, r) for r in rows]
    # ON CONFLICT can't update the same row twice in one statement, so drop
    # in-batch duplicate upsert_keys (keep the last occurrence).
    prepared = list({r["upsert_key"]: r for r in prepared}.values())
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


def prepare_row(model, row: dict) -> dict:
    """Coerce raw parser values to the types asyncpg expects per column.

    Public because the campaign manager's catalogue refresh writes the same table from the
    same API shape (`repo.upsert_campaign_catalog`) and must coerce identically."""
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
        elif isinstance(col.type, Integer) and not isinstance(val, bool):
            # asyncpg rejects float->INTEGER; the ad APIs return some counts /
            # positions as floats (e.g. an average position), so round to int.
            if isinstance(val, float):
                data[col.name] = round(val)
            elif isinstance(val, str) and val:
                data[col.name] = round(float(val))
        elif isinstance(col.type, Float):
            if isinstance(val, str) and val:
                data[col.name] = float(val)
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
