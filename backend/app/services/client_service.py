"""Client (tenant) lookups, scoped to the caller's account and user.

Two walls: a Client must belong to the caller's Account, and a user with
`client_scope='listed'` must also have been granted it in `user_clients`.
Scope only narrows what the account wall already allows.
"""
import uuid

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant, User, UserClient


async def visible_client_ids(
    session: AsyncSession, user_id: uuid.UUID
) -> set[uuid.UUID] | None:
    """The Clients this user may reach, or None for "no restriction".

    ⚠️ None (scope='all') and the empty set (scope='listed', nothing granted) are
    different answers — test `is None`, never a falsy check. An unknown or
    inactive user returns the empty set, so access closes rather than opens.
    """
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        return set()
    if user.client_scope != "listed":
        return None
    rows = (
        await session.execute(
            select(UserClient.tenant_id).where(UserClient.user_id == user_id)
        )
    ).scalars().all()
    return set(rows)


async def list_clients(
    session: AsyncSession, account_id: uuid.UUID, user_id: uuid.UUID
) -> list[Tenant]:
    """The Clients this user may switch between — what the picker shows.

    Scope-filtered too: listing a Client the caller cannot open gives a 404 on click.
    """
    stmt = select(Tenant).where(Tenant.account_id == account_id)
    allowed = await visible_client_ids(session, user_id)
    if allowed is not None:
        if not allowed:
            return []
        stmt = stmt.where(Tenant.id.in_(allowed))
    return (await session.execute(stmt.order_by(Tenant.created_at))).scalars().all()


async def get_client_for_account(
    session: AsyncSession,
    client_id: uuid.UUID,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Tenant | None:
    """Return the Client only if this user may reach it — the access wall.

    None for both "another account's" and "outside your scope", so the caller
    raises one 404 and never reveals that a Client exists but is off-limits.

    Deliberately NOT cached here: `dependencies.get_client` already remembers a
    passed check and detaches the row, and a second cache in front of it would
    hand that caller an instance its session never held.
    """
    client = await session.get(Tenant, client_id)
    if not client or client.account_id != account_id:
        return None
    allowed = await visible_client_ids(session, user_id)
    if allowed is not None and client_id not in allowed:
        return None
    return client
