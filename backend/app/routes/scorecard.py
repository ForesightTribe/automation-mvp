"""Client-scoped seller scorecard. Mounted under /clients/{client_id}/scorecard.

Scorecard data is weekly snapshots (keyed on `from_date_ist`), so these endpoints
navigate by week — `?from=` selects a week, defaulting to the latest. `/weeks`
lists the choices for the page's week picker.

`?marketplace=` is OPTIONAL and rarely needed. Left out, the service picks the
platform this tenant actually has data for: Blinkit if it publishes a scorecard
for them, Zepto otherwise (where the same figures are derived from the PO tables
because Zepto publishes none). Callers that never send it keep their old
behaviour exactly."""
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

# Blinkit publishes a scorecard; Zepto's and Instamart's are both derived from
# PO tables at read time (see scorecard_service module docstring). Any value
# outside this set used to fall straight through `scorecard_service._platform`'s
# `== "zepto"`/`== "instamart"` checks into the BLINKIT branch by default,
# silently serving Blinkit's rows under whatever marketplace was actually
# asked for. Guarding here, once, before any service call, is cheaper and
# safer than teaching every branch in the service to recognise a platform it
# has no data for.
_SUPPORTED = {"blinkit", "zepto", "instamart"}


def _check_marketplace(marketplace: str | None) -> None:
    if marketplace is not None and marketplace not in _SUPPORTED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scorecard is not available for {marketplace!r} yet "
            f"(only blinkit and zepto publish/derive one).",
        )


@router.get("/weeks", response_model=list[date])
async def weeks(
    session: SessionDep,
    client: ClientDep,
    marketplace: str | None = Query(None, description="blinkit | zepto | instamart; auto-detects blinkit/zepto when omitted, instamart is explicit-only"),
):
    _check_marketplace(marketplace)
    return await scorecard_service.get_weeks(
        session, tenant_id=client.id, marketplace=marketplace
    )


@router.get("/weekly", response_model=ScorecardWeeklyOut)
async def weekly(
    session: SessionDep,
    client: ClientDep,
    from_date: date | None = Query(None, alias="from", description="Defaults to latest"),
    marketplace: str | None = Query(None, description="blinkit | zepto | instamart; auto-detects blinkit/zepto when omitted, instamart is explicit-only"),
):
    _check_marketplace(marketplace)
    data = await scorecard_service.get_weekly(
        session, tenant_id=client.id, from_date=from_date, marketplace=marketplace
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
    marketplace: str | None = Query(None, description="blinkit | zepto | instamart; auto-detects blinkit/zepto when omitted, instamart is explicit-only"),
):
    _check_marketplace(marketplace)
    return await scorecard_service.get_trend(
        session, tenant_id=client.id, weeks=weeks, marketplace=marketplace
    )


@router.get("/key-skus", response_model=Page[KeySkuRow])
async def key_skus(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    from_date: date | None = Query(None, alias="from", description="Defaults to latest"),
    marketplace: str | None = Query(None, description="blinkit | zepto | instamart; auto-detects blinkit/zepto when omitted, instamart is explicit-only"),
):
    _check_marketplace(marketplace)
    return await scorecard_service.get_key_skus(
        session, tenant_id=client.id, pagination=pagination, from_date=from_date,
        marketplace=marketplace,
    )


@router.get("/facilities", response_model=Page[FacilityRow])
async def facilities(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    from_date: date | None = Query(None, alias="from", description="Defaults to latest"),
    marketplace: str | None = Query(None, description="blinkit | zepto | instamart; auto-detects blinkit/zepto when omitted, instamart is explicit-only"),
):
    _check_marketplace(marketplace)
    return await scorecard_service.get_facilities(
        session, tenant_id=client.id, pagination=pagination, from_date=from_date,
        marketplace=marketplace,
    )


@router.get("/facility/{facility_id}/pos", response_model=Page[FacilityPoRow])
async def facility_pos(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    facility_id: str,
    marketplace: str | None = Query(None, description="blinkit | zepto | instamart; auto-detects blinkit/zepto when omitted, instamart is explicit-only"),
):
    _check_marketplace(marketplace)
    return await scorecard_service.get_facility_pos(
        session, tenant_id=client.id, facility_id=facility_id, pagination=pagination,
        marketplace=marketplace,
    )
