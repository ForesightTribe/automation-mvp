"""Client-scoped Reports — the client's familiar Excel views. Mounted under
/clients/{client_id}/reports, so every handler gets `client: ClientDep`."""
from fastapi import APIRouter, Query

from app.dependencies import ClientDep, PeriodDep, SessionDep
from app.schemas.reports import CompetitionReport, MarketingReport, SalesPivot
from app.services import reports_service

router = APIRouter()


@router.get("/sales-pivot", response_model=SalesPivot)
async def sales_pivot(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    metric: str = Query(
        "value",
        pattern="^(value|units)$",
        description="Cell metric: 'value' (revenue) or 'units'.",
    ),
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await reports_service.get_sales_pivot(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
        metric=metric,
    )


@router.get("/marketing", response_model=MarketingReport)
async def marketing(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await reports_service.get_marketing_report(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
    )


@router.get("/competition", response_model=CompetitionReport)
async def competition(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    kind: str = Query(
        "main",
        pattern="^(main|combo|all)$",
        description="Combo filter: 'main' (singles), 'combo', or 'all'.",
    ),
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await reports_service.get_competition_report(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
        kind=kind,
    )
