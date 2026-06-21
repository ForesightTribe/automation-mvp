"""Client (tenant) lookups, always scoped to the caller's account."""
import uuid

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant


async def list_clients(session: AsyncSession, account_id: uuid.UUID) -> list[Tenant]:
    return (
        await session.execute(
            select(Tenant)
            .where(Tenant.account_id == account_id)
            .order_by(Tenant.created_at)
        )
    ).scalars().all()


async def get_client_for_account(
    session: AsyncSession, client_id: uuid.UUID, account_id: uuid.UUID
) -> Tenant | None:
    """Return the client only if it belongs to this account — the access wall."""
    client = await session.get(Tenant, client_id)
    if not client or client.account_id != account_id:
        return None
    return client
