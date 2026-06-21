"""Client-scoped inventory. Mounted under /clients/{client_id}/inventory."""
from datetime import date

from fastapi import APIRouter, Query

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.common import Page
from app.schemas.inventory import AvailabilityRow, FillRateSummary, SohRow
from app.services import inventory_service

router = APIRouter()


@router.get("/soh", response_model=Page[SohRow])
async def soh(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    on_date: date | None = Query(None, alias="date", description="Defaults to latest"),
):
    return await inventory_service.get_soh(
        session, tenant_id=client.id, pagination=pagination, on_date=on_date
    )


@router.get("/fill-rate", response_model=FillRateSummary)
async def fill_rate(
    session: SessionDep,
    client: ClientDep,
    from_date: date | None = Query(None, alias="from", description="Defaults to latest"),
):
    return await inventory_service.get_fill_rate(
        session, tenant_id=client.id, from_date=from_date
    )


@router.get("/availability", response_model=Page[AvailabilityRow])
async def availability(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    days: int = Query(7, ge=1, le=90),
    city: str | None = None,
    marketplace: str | None = None,
):
    """Public stock-out monitoring for the client's own brand (out-of-stock first)."""
    return await inventory_service.get_availability(
        session,
        tenant_id=client.id,
        pagination=pagination,
        days=days,
        city=city,
        marketplace=marketplace,
    )
