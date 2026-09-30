"""Client (tenant) lookups, always scoped to the caller's account."""
import uuid

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.utils.cache import ttl_cache


async def list_clients(session: AsyncSession, account_id: uuid.UUID) -> list[Tenant]:
    return (
        await session.execute(
            select(Tenant)
            .where(Tenant.account_id == account_id)
            .order_by(Tenant.created_at)
        )
    ).scalars().all()


# ⚠️ Short on purpose. This is the ACCESS WALL, and caching it means a client
# moved to another account, or deleted, stays reachable until the entry lapses.
# A minute bounds that while removing the ~80ms round trip every single request
# was paying before any of its own work began.
_WALL_TTL = 60


@ttl_cache(_WALL_TTL)
async def get_client_for_account(
    session: AsyncSession, client_id: uuid.UUID, account_id: uuid.UUID
) -> Tenant | None:
    """Return the client only if it belongs to this account — the access wall.

    The identity checked here is the (client, account) PAIR, which is also the
    cache key: a second account asking for the same client is a different
    entry and gets its own check.
    """
    client = await session.get(Tenant, client_id)
    if not client or client.account_id != account_id:
        return None
    # Detached from the session that loaded it, so the cached copy cannot lazy
    # load later. Every column is already populated by `session.get`.
    session.expunge(client)
    return client
