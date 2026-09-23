"""Platform connection state for a client.

The heavy lifting — encryption, the inbox reader, the authenticators — lives in
`platform_auth/`. This module is only the API's view of it: what the Connections
screen needs to render, plus the two writes it allows (save credentials, start a
login). Logging in itself stays a JOB, because it waits on mail arriving.
"""
import uuid

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import PlatformSession
from app.schemas.platform import PlatformStatus
from platform_auth import registry, store
from platform_auth.types import Credentials


async def list_sessions(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[PlatformSession]:
    return (
        await session.execute(
            select(PlatformSession)
            .where(PlatformSession.tenant_id == tenant_id)
            .order_by(PlatformSession.platform)
        )
    ).scalars().all()


async def overview(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[PlatformStatus]:
    """Every platform the product knows about, with this client's state on each.

    Driven by the REGISTRY, not by what happens to be in the tables: a platform
    with no credentials and no session is the interesting row on this screen, and
    listing only what exists would hide exactly the ones needing setup.
    """
    sessions = {r.platform: r for r in await list_sessions(session, tenant_id)}
    creds = {
        c["platform"]: c
        for c in await store.credentials_for_tenant(session, str(tenant_id))
    }
    out = []
    for slug, auth in registry.AUTHENTICATORS.items():
        live = sessions.get(slug)
        cred = creds.get(slug)
        out.append(
            PlatformStatus(
                platform=slug,
                name=auth.name,
                wired=auth.wired,
                needs_password=auth.needs_password,
                connected=live is not None,
                connected_at=live.updated_at if live else None,
                has_credentials=cred is not None,
                login_email=cred["login_email"] if cred else None,
                has_password=bool(cred and cred["has_password"]),
                credentials_updated_at=cred["updated_at"] if cred else None,
            )
        )
    return out


async def save_credentials(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    platform: str,
    email: str,
    password: str | None,
) -> None:
    """Store who to log in as. The password is encrypted by the store, never here."""
    await store.save_credentials(
        session,
        str(tenant_id),
        platform,
        Credentials(email=email, password=password),
    )


async def disconnect(
    session: AsyncSession, *, tenant_id: uuid.UUID, platform: str
) -> bool:
    """Stop signing in to this account: drops the session AND the saved login.

    Both are needed. `platform_auth.service.ensure()` performs a fresh login whenever
    no session is stored, so credentials left behind reconnect the account.
    """
    row = (
        await session.execute(
            select(PlatformSession).where(
                PlatformSession.tenant_id == tenant_id,
                PlatformSession.platform == platform,
            )
        )
    ).scalar_one_or_none()
    if row:
        await session.delete(row)
        await session.commit()
    had_credentials = await store.delete_credentials(session, str(tenant_id), platform)
    return bool(row) or had_credentials
