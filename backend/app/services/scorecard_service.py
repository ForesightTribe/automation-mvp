"""Client-scoped Blinkit scorecard: weekly brand health, key SKUs at risk,
and facility-level fill performance."""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.blinkit_seller import (
    BlinkitScorecardFacility,
    BlinkitScorecardKeySku,
    BlinkitScorecardWeekly,
)
from app.schemas.common import Page
from app.schemas.scorecard import FacilityRow, KeySkuRow


async def _latest_from(session: AsyncSession, model, tenant_id: uuid.UUID):
    return (
        await session.execute(
            select(func.max(model.from_date_ist)).where(model.tenant_id == tenant_id)
        )
    ).scalar()


async def get_weekly(
    session: AsyncSession, *, tenant_id: uuid.UUID, from_date: date | None = None
) -> dict | None:
    cond = [BlinkitScorecardWeekly.tenant_id == tenant_id]
    if from_date:
        cond.append(BlinkitScorecardWeekly.from_date_ist == from_date)
    row = (
        await session.execute(
            select(BlinkitScorecardWeekly)
            .where(*cond)
            .order_by(BlinkitScorecardWeekly.from_date_ist.desc())
            .limit(1)
        )
    ).scalars().first()
    if not row:
        return None
    return {
        "from_date": row.from_date_ist,
        "overall": row.overall,
        "best_category": row.best_category,
        "categories": row.categories,
    }


async def get_key_skus(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    from_date: date | None = None,
) -> Page[KeySkuRow]:
    target = from_date or await _latest_from(session, BlinkitScorecardKeySku, tenant_id)
    if target is None:
        return Page.build([], 0, pagination)

    cond = [
        BlinkitScorecardKeySku.tenant_id == tenant_id,
        BlinkitScorecardKeySku.from_date_ist == target,
    ]
    total = (
        await session.execute(
            select(func.count()).select_from(BlinkitScorecardKeySku).where(*cond)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(BlinkitScorecardKeySku)
            .where(*cond)
            .order_by(BlinkitScorecardKeySku.potential_loss.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()
    return Page.build([KeySkuRow.model_validate(r) for r in rows], total, pagination)


async def get_facilities(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    from_date: date | None = None,
) -> Page[FacilityRow]:
    target = from_date or await _latest_from(session, BlinkitScorecardFacility, tenant_id)
    if target is None:
        return Page.build([], 0, pagination)

    cond = [
        BlinkitScorecardFacility.tenant_id == tenant_id,
        BlinkitScorecardFacility.from_date_ist == target,
    ]
    total = (
        await session.execute(
            select(func.count()).select_from(BlinkitScorecardFacility).where(*cond)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(BlinkitScorecardFacility)
            .where(*cond)
            .order_by(BlinkitScorecardFacility.potential_loss.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()
    return Page.build([FacilityRow.model_validate(r) for r in rows], total, pagination)
