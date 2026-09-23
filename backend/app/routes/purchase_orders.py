"""Client-scoped purchase orders. Mounted under /clients/{client_id}/purchase-orders."""
import os
import shutil

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.dependencies import ClientDep, PaginationDep, PeriodDep, SessionDep
from app.schemas.common import Page
from app.schemas.purchase_order import (
    PODetailOut,
    POInsightRow,
    POInsightsSummary,
    POSkuRow,
    POSnapshotOut,
    PurchaseOrderOut,
)
from app.services import po_export_service, po_service

router = APIRouter()


@router.get("", response_model=Page[PurchaseOrderOut])
async def list_pos(session: SessionDep, client: ClientDep, pagination: PaginationDep):
    return await po_service.list_pos(
        session, tenant_id=client.id, pagination=pagination
    )


@router.get("/insights/summary", response_model=POInsightsSummary)
async def insights_summary(session: SessionDep, client: ClientDep, period: PeriodDep):
    """PO value, fill rate and undelivered value, against the preceding window."""
    return await po_service.insights_summary(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        prev_start=period.prev_start,
        prev_end=period.prev_end,
    )


@router.get("/insights", response_model=Page[POInsightRow])
async def insights(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    pagination: PaginationDep,
    scope: str = Query("priority", pattern="^(priority|all)$"),
    search: str | None = None,
    status: str | None = Query(
        None,
        description="A PO state (Scheduled, Unscheduled, Fulfilled, Expired…), "
        "or 'open' / 'closed' for the two groups.",
    ),
):
    """The PO queue. `priority` keeps open POs with something still undelivered."""
    return await po_service.insights(
        session,
        tenant_id=client.id,
        pagination=pagination,
        start=period.start,
        end=period.end,
        scope=scope,
        search=search,
        status=status,
    )


@router.get("/insights/skus", response_model=Page[POSkuRow])
async def sku_insights(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    pagination: PaginationDep,
    search: str | None = None,
):
    """The shortfall per SKU across every PO in the window."""
    return await po_service.sku_insights(
        session,
        tenant_id=client.id,
        pagination=pagination,
        start=period.start,
        end=period.end,
        search=search,
    )


@router.get("/insights/file")
async def download_insights(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    scope: str = Query("priority", pattern="^(priority|all)$"),
    status: str | None = None,
):
    """The section on screen, as an .xlsx: the PO table and the SKU shortfall.

    `scope` mirrors the page's toggle, so the file holds the POs the reader was
    looking at rather than a different selection.
    """
    try:
        path, name = await po_export_service.build_file(
            session,
            tenant_id=client.id,
            start=period.start,
            end=period.end,
            scope=scope,
            status=status,
            client_name=client.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # The workbook is written to a throwaway directory; without the background task
    # every download leaves one behind for the life of the process.
    return FileResponse(
        path,
        filename=name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(shutil.rmtree, os.path.dirname(path), ignore_errors=True),
    )


# Declared before /{po_number} so the static path wins.
@router.get("/snapshots", response_model=Page[POSnapshotOut])
async def list_snapshots(
    session: SessionDep, client: ClientDep, pagination: PaginationDep
):
    return await po_service.list_snapshots(
        session, tenant_id=client.id, pagination=pagination
    )


@router.get("/{po_number}", response_model=PODetailOut)
async def get_po(session: SessionDep, client: ClientDep, po_number: str):
    po = await po_service.get_po(session, tenant_id=client.id, po_number=po_number)
    if not po:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found"
        )
    return po
