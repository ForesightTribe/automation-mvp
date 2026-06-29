"""Client-scoped Blinkit scorecard. Mounted under /clients/{client_id}/scorecard.

Scorecard data is weekly snapshots (keyed on `from_date_ist`), so these endpoints
navigate by week — `?from=` selects a week, defaulting to the latest. `/weeks`
lists the choices for the page's week picker. There's no marketplace scoping
(Blinkit is the only platform with a seller scorecard)."""
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.common import Page
from app.schemas.scorecard import (
    FacilityPoRow,
    FacilityRow,
    KeySkuRow,
    ScorecardTrendPoint,
    ScorecardWeeklyOut,
)
from app.services import scorecard_service

router = APIRouter()


@router.get("/weeks", response_model=list[date])
async def weeks(session: SessionDep, client: ClientDep):
    return await scorecard_service.get_weeks(session, tenant_id=client.id)


@router.get("/weekly", response_model=ScorecardWeeklyOut)
async def weekly(
    session: SessionDep,
    client: ClientDep,
    from_date: date | None = Query(None, alias="from", description="Defaults to latest"),
):
    data = await scorecard_service.get_weekly(
        session, tenant_id=client.id, from_date=from_date
    )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No scorecard data"
        )
    return data


@router.get("/trend", response_model=list[ScorecardTrendPoint])
async def trend(
    session: SessionDep,
    client: ClientDep,
    weeks: int = Query(12, ge=1, le=104, description="Number of recent weeks"),
):
    return await scorecard_service.get_trend(
        session, tenant_id=client.id, weeks=weeks
    )


@router.get("/key-skus", response_model=Page[KeySkuRow])
async def key_skus(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    from_date: date | None = Query(None, alias="from", description="Defaults to latest"),
):
    return await scorecard_service.get_key_skus(
        session, tenant_id=client.id, pagination=pagination, from_date=from_date
    )


@router.get("/facilities", response_model=Page[FacilityRow])
async def facilities(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    from_date: date | None = Query(None, alias="from", description="Defaults to latest"),
):
    return await scorecard_service.get_facilities(
        session, tenant_id=client.id, pagination=pagination, from_date=from_date
    )


@router.get("/facility/{facility_id}/pos", response_model=Page[FacilityPoRow])
async def facility_pos(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    facility_id: str,
):
    return await scorecard_service.get_facility_pos(
        session, tenant_id=client.id, facility_id=facility_id, pagination=pagination
    )
