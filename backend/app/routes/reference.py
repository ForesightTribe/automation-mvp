"""Global reference data (login required, but not client-scoped)."""
import uuid

from fastapi import APIRouter, Query

from app.dependencies import CurrentUserDep, SessionDep
from app.schemas.reference import BrandOut, MarketplaceOut
from app.services import reference_service

router = APIRouter()


@router.get("/brands", response_model=list[BrandOut])
async def brands(session: SessionDep, _user: CurrentUserDep):
    return await reference_service.list_brands(session)


@router.get("/marketplaces", response_model=list[MarketplaceOut])
async def marketplaces(
    session: SessionDep,
    _user: CurrentUserDep,
    client_id: uuid.UUID | None = Query(
        None, description="Narrow `connected` to the marketplaces THIS client has data for"
    ),
):
    """`client_id` makes `connected` client-scoped, so the picker can grey out a
    channel this brand is not served on rather than offering an empty one."""
    return await reference_service.list_marketplaces(session, tenant_id=client_id)


@router.get("/blinkit-zones")
async def blinkit_zones(session: SessionDep, _user: CurrentUserDep):
    """All active Blinkit dark store locations from marketplace_locations table."""
    return await reference_service.list_blinkit_zones(session)
