"""Client-scoped purchase orders (blinkit_pos) and PO snapshots."""
import uuid

from sqlalchemy import func
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.blinkit_seller import BlinkitPO, BlinkitPOSnapshot
from app.schemas.common import Page
from app.schemas.purchase_order import POSnapshotOut, PurchaseOrderOut


async def list_pos(
    session: AsyncSession, *, tenant_id: uuid.UUID, pagination: Pagination
) -> Page[PurchaseOrderOut]:
    cond = [BlinkitPO.tenant_id == tenant_id]
    total = (
        await session.execute(
            select(func.count()).select_from(BlinkitPO).where(*cond)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(BlinkitPO)
            .where(*cond)
            .order_by(BlinkitPO.scraped_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()
    return Page.build(
        [PurchaseOrderOut.model_validate(r) for r in rows], total, pagination
    )


async def get_po(
    session: AsyncSession, *, tenant_id: uuid.UUID, po_number: str
) -> BlinkitPO | None:
    return (
        await session.execute(
            select(BlinkitPO).where(
                BlinkitPO.tenant_id == tenant_id, BlinkitPO.po_number == po_number
            )
        )
    ).scalar_one_or_none()


async def list_snapshots(
    session: AsyncSession, *, tenant_id: uuid.UUID, pagination: Pagination
) -> Page[POSnapshotOut]:
    cond = [BlinkitPOSnapshot.tenant_id == tenant_id]
    total = (
        await session.execute(
            select(func.count()).select_from(BlinkitPOSnapshot).where(*cond)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(BlinkitPOSnapshot)
            .where(*cond)
            .order_by(BlinkitPOSnapshot.window_start.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()
    return Page.build(
        [POSnapshotOut.model_validate(r) for r in rows], total, pagination
    )
