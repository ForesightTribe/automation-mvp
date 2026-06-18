import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

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
    stmt = (
        insert(model)
        .values([_prepare(model, r) for r in rows])
        .on_conflict_do_update(
            index_elements=["upsert_key"],
            set_={c: insert(model).excluded[c] for c in _update_cols(model)},
        )
    )
    await session.execute(stmt)


def _prepare(model, row: dict) -> dict:
    data = dict(row)
    if "tenant_id" in data and isinstance(data["tenant_id"], str):
        data["tenant_id"] = uuid.UUID(data["tenant_id"])
    if "scrape_job_id" in data and isinstance(data["scrape_job_id"], str):
        data["scrape_job_id"] = uuid.UUID(data["scrape_job_id"])
    return data


def _update_cols(model) -> list[str]:
    pk = {"id", "upsert_key"}
    return [c.name for c in model.__table__.columns if c.name not in pk]
