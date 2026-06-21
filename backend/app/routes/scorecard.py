"""Client-scoped Blinkit scorecard. Mounted under /clients/{client_id}/scorecard."""
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.common import Page
from app.schemas.scorecard import FacilityRow, KeySkuRow, ScorecardWeeklyOut
from app.services import scorecard_service

router = APIRouter()


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
