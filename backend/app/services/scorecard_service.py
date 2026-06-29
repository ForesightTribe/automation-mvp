"""Client-scoped Blinkit scorecard: weekly brand health, key SKUs at risk,
facility-level fill performance, and the multi-week trend.

Scorecard data is **weekly snapshots** keyed on `from_date_ist` (not daily), so
this page navigates by week rather than reading the global date range. Blinkit is
the only platform that publishes a seller scorecard, so there's no marketplace
scoping here."""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.blinkit_seller import (
    BlinkitPO,
    BlinkitScorecardFacility,
    BlinkitScorecardKeySku,
    BlinkitScorecardWeekly,
)
from app.schemas.common import Page
from app.schemas.scorecard import FacilityPoRow, FacilityRow, KeySkuRow
from app.services.analytics_service import _metric

# Overall-snapshot keys repacked as growth metrics for the KPI strip.
_OVERALL_METRIC_KEYS = (
    "fill_rate",
    "weighted_fill_rate_percent",
    "potential_loss",
    "total_gmv",
    "total_po_quantity",
    "total_grn_quantity",
    "manufacturer_rank",
)


async def _latest_from(session: AsyncSession, model, tenant_id: uuid.UUID):
    return (
        await session.execute(
            select(func.max(model.from_date_ist)).where(model.tenant_id == tenant_id)
        )
    ).scalar()


async def get_weeks(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[date]:
    """Available scorecard weeks, newest first — powers the page's week picker."""
    return list(
        (
            await session.execute(
                select(BlinkitScorecardWeekly.from_date_ist)
                .where(BlinkitScorecardWeekly.tenant_id == tenant_id)
                .distinct()
                .order_by(BlinkitScorecardWeekly.from_date_ist.desc())
            )
        ).scalars().all()
    )


async def get_weekly(
    session: AsyncSession, *, tenant_id: uuid.UUID, from_date: date | None = None
) -> dict | None:
    """The selected (or latest) week plus growth vs the immediately-preceding
    week. Two rows at most: the target week and the one before it."""
    rows = (
        await session.execute(
            select(BlinkitScorecardWeekly)
            .where(
                BlinkitScorecardWeekly.tenant_id == tenant_id,
                *(
                    [BlinkitScorecardWeekly.from_date_ist <= from_date]
                    if from_date
                    else []
                ),
            )
            .order_by(BlinkitScorecardWeekly.from_date_ist.desc())
            .limit(2)
        )
    ).scalars().all()
    if not rows:
        return None

    current = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    cur_overall = current.overall or {}
    prev_overall = (prev.overall or {}) if prev else {}

    metrics = {
        key: _metric(cur_overall.get(key), prev_overall.get(key))
        for key in _OVERALL_METRIC_KEYS
    }
    return {
        "from_date": current.from_date_ist,
        "prev_from_date": prev.from_date_ist if prev else None,
        "overall": cur_overall,
        "metrics": metrics,
        "best_category": current.best_category,
        "categories": current.categories,
    }


async def get_trend(
    session: AsyncSession, *, tenant_id: uuid.UUID, weeks: int = 12
) -> list[dict]:
    """Per-week overall metrics across the last `weeks` snapshots, oldest first —
    feeds the fill-rate / potential-loss trend chart."""
    rows = (
        await session.execute(
            select(
                BlinkitScorecardWeekly.from_date_ist,
                BlinkitScorecardWeekly.overall,
            )
            .where(BlinkitScorecardWeekly.tenant_id == tenant_id)
            .order_by(BlinkitScorecardWeekly.from_date_ist.desc())
            .limit(weeks)
        )
    ).all()

    out = []
    for fdate, overall in reversed(rows):  # oldest first for the x-axis
        o = overall or {}
        out.append(
            {
                "from_date": fdate,
                "fill_rate": o.get("fill_rate"),
                "weighted_fill_rate_percent": o.get("weighted_fill_rate_percent"),
                "potential_loss": o.get("potential_loss"),
                "total_gmv": o.get("total_gmv"),
                "total_po_quantity": o.get("total_po_quantity"),
                "total_grn_quantity": o.get("total_grn_quantity"),
                "manufacturer_rank": o.get("manufacturer_rank"),
            }
        )
    return out


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


async def get_facility_pos(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    facility_id: str,
    pagination: Pagination,
) -> Page[FacilityPoRow]:
    """POs behind a facility's fill loss — the supply story drill-down. Joined on
    `facility_id`; newest issue date first. Not week-scoped (a poor scorecard
    week traces back to POs issued before it)."""
    cond = [
        BlinkitPO.tenant_id == tenant_id,
        BlinkitPO.facility_id == facility_id,
    ]
    total = (
        await session.execute(
            select(func.count()).select_from(BlinkitPO).where(*cond)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(BlinkitPO)
            .where(*cond)
            .order_by(BlinkitPO.issue_date.desc().nullslast())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()
    return Page.build(
        [FacilityPoRow.model_validate(r) for r in rows], total, pagination
    )
