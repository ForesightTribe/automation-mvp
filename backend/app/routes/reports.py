"""Client-scoped Reports — the client's familiar Excel views. Mounted under
/clients/{client_id}/reports, so every handler gets `client: ClientDep`."""
import os
import shutil
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.dependencies import ClientDep, PaginationDep, PeriodDep, SessionDep
from app.schemas.reports import CompetitionReport, MarketingReport, SalesPivot, WeekendPlanning
from app.services import instamart_reports, report_export_service, reports_service

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


@router.get("/weekend-planning", response_model=WeekendPlanning)
async def weekend_planning(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    """Campaign spend and return with each Fri–Sun weekend as its own column group."""
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await reports_service.get_weekend_planning(
        session, tenant_id=client.id, start=period.start, end=period.end, marketplaces=mps
    )


@router.get("/raw-ads")
async def raw_ads(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    pagination: PaginationDep,
    marketplace: str = Query("blinkit", description="blinkit | instamart"),
    campaign_type: str | None = Query(
        None, description="PRODUCT_LISTING | PRODUCT_RECOMMENDATION — blinkit only"
    ),
):
    """The platform's own per-day export rows, paginated.

    Paginated rather than capped: these sheets run to tens of thousands of rows,
    and a page that silently shows the first few hundred is a page that quietly
    lies about what the export contains.

    Blinkit has two campaign-type sheets (`campaign_type` required); Instamart
    has one flat sheet (no campaign-type split — see instamart_reports.py).
    """
    if marketplace == "instamart":
        rows = await instamart_reports.raw_ad_rows(
            session, tenant_id=client.id, start=period.start, end=period.end
        )
    else:
        if not campaign_type:
            raise HTTPException(422, "campaign_type is required for blinkit")
        rows = await reports_service.get_raw_ad_rows(
            session,
            tenant_id=client.id,
            start=period.start,
            end=period.end,
            campaign_type=campaign_type,
        )
    total = len(rows)
    lo = pagination.offset
    return {
        "items": rows[lo : lo + pagination.limit],
        "total": total,
        "page": pagination.page,
        "limit": pagination.limit,
        "pages": max(1, -(-total // pagination.limit)),
    }


@router.get("/{which}/file")
async def download_report(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    which: str,
    marketplaces: str | None = Query(None, description="Comma-separated slugs; omit for all."),
    metric: str = Query("value", pattern="^(value|units)$"),
    view: str = Query("daily", pattern="^(daily|weekly)$"),
    kind: str = Query("main", pattern="^(main|combo|all)$"),
):
    """The report on screen, as an .xlsx.

    Every parameter mirrors a control on the page, because the file has to be the
    report the reader was looking at: the same window, the same metric, the same
    half of the pivot. It is rendered from `reports_service`, the same code that
    fed the table, so the two cannot disagree.
    """
    try:
        path, name = await report_export_service.build_file(
            session,
            which=which,
            tenant_id=client.id,
            start=period.start,
            end=period.end,
            marketplaces=[m for m in marketplaces.split(",") if m] if marketplaces else None,
            metric=metric,
            view=view,
            kind=kind,
            client_name=client.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # The workbook is written to a throwaway directory, so it has to be swept up once the
    # response has been sent. Without the background task every download leaves a directory
    # behind for the life of the process.
    return FileResponse(
        path,
        filename=name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(shutil.rmtree, os.path.dirname(path), ignore_errors=True),
    )
