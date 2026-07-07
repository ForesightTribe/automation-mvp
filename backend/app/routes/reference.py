"""Global reference data (login required, but not client-scoped)."""
from fastapi import APIRouter

from app.dependencies import CurrentUserDep, SessionDep
from app.schemas.reference import BrandOut, CityOut, MarketplaceOut
from app.services import reference_service

router = APIRouter()


@router.get("/brands", response_model=list[BrandOut])
async def brands(session: SessionDep, _user: CurrentUserDep):
    return await reference_service.list_brands(session)


@router.get("/marketplaces", response_model=list[MarketplaceOut])
async def marketplaces(session: SessionDep, _user: CurrentUserDep):
    return await reference_service.list_marketplaces(session)


@router.get("/cities", response_model=list[CityOut])
async def cities(_user: CurrentUserDep):
    return reference_service.list_cities()


@router.get("/blinkit-zones")
async def blinkit_zones(_user: CurrentUserDep):
    """All blinkit dark store zones with lat/lon — for bid optimizer location picker."""
    return reference_service.list_blinkit_zones()
