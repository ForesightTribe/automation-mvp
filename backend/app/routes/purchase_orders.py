"""Client-scoped purchase orders. Mounted under /clients/{client_id}/purchase-orders."""
from fastapi import APIRouter, HTTPException, status

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.common import Page
from app.schemas.purchase_order import PODetailOut, POSnapshotOut, PurchaseOrderOut
from app.services import po_service

router = APIRouter()


@router.get("", response_model=Page[PurchaseOrderOut])
async def list_pos(session: SessionDep, client: ClientDep, pagination: PaginationDep):
    return await po_service.list_pos(
        session, tenant_id=client.id, pagination=pagination
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
