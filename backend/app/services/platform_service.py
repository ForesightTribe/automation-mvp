"""Platform connection state for a client. Connecting a session is interactive
(OTP/browser) and stays in the CLI; the API exposes status + disconnect."""
import uuid

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import PlatformSession


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


async def disconnect(
    session: AsyncSession, *, tenant_id: uuid.UUID, platform: str
) -> bool:
    row = (
        await session.execute(
            select(PlatformSession).where(
                PlatformSession.tenant_id == tenant_id,
                PlatformSession.platform == platform,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.commit()
    return True
