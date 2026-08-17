import json
import uuid
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select

from app.models.job import PlatformSession
from app.utils.encryption import encrypt, decrypt
from app.utils.logger import logger
from app.utils.time import now_ist


class SessionUnhealthy(Exception):
    """Raised by ensure_healthy_session() when a saved session is missing or
    was rejected by the platform — the caller should stop and ask for a fresh
    login rather than attempt real scrape work with a dead session."""


async def save_session(session: AsyncSession, tenant_id: str, platform: str, storage_state: dict) -> None:
    encrypted = encrypt(json.dumps(storage_state))
    now = now_ist()

    # A fresh save always follows a real, just-succeeded login — so it's
    # definitionally healthy and validated at this exact moment.
    stmt = (
        insert(PlatformSession)
        .values(
            tenant_id=uuid.UUID(tenant_id),
            platform=platform,
            encrypted_session=encrypted,
            created_at=now,
            updated_at=now,
            status="healthy",
            last_login_at=now,
            last_validated_at=now,
            consecutive_failures=0,
            last_error=None,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "platform"],
            set_={
                "encrypted_session": encrypted,
                "updated_at": now,
                "status": "healthy",
                "last_login_at": now,
                "last_validated_at": now,
                "consecutive_failures": 0,
                "last_error": None,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()
    logger.info(f"Session saved: tenant={tenant_id} platform={platform}")


async def load_session(session: AsyncSession, tenant_id: str, platform: str) -> dict | None:
    result = await session.execute(
        select(PlatformSession).where(
            PlatformSession.tenant_id == uuid.UUID(tenant_id),
            PlatformSession.platform == platform,
        )
    )
    record = result.scalars().first()
    if not record:
        logger.warning(f"No session found: tenant={tenant_id} platform={platform}")
        return None
    return json.loads(decrypt(record.encrypted_session))


async def session_exists(session: AsyncSession, tenant_id: str, platform: str) -> bool:
    result = await session.execute(
        select(PlatformSession).where(
            PlatformSession.tenant_id == uuid.UUID(tenant_id),
            PlatformSession.platform == platform,
        )
    )
    return result.scalars().first() is not None


# A single miss could be a transient network blip rather than a genuinely dead
# session, so "dead" only sticks after a second consecutive failure.
_DEAD_AFTER_FAILURES = 2


async def record_validation(
    session: AsyncSession,
    tenant_id: str,
    platform: str,
    ok: bool,
    error: str | None = None,
) -> str:
    """Update a session's health fields after a validate_session() probe.
    Returns the resulting status ("healthy" | "degraded" | "dead")."""
    now = now_ist()

    if ok:
        status = "healthy"
        stmt = (
            select(PlatformSession)
            .where(PlatformSession.tenant_id == uuid.UUID(tenant_id), PlatformSession.platform == platform)
        )
        record = (await session.execute(stmt)).scalars().first()
        if record:
            record.status = status
            record.last_validated_at = now
            record.consecutive_failures = 0
            record.last_error = None
            session.add(record)
            await session.commit()
        return status

    stmt = (
        select(PlatformSession)
        .where(PlatformSession.tenant_id == uuid.UUID(tenant_id), PlatformSession.platform == platform)
    )
    record = (await session.execute(stmt)).scalars().first()
    if not record:
        return "unknown"

    record.consecutive_failures += 1
    record.last_validated_at = now
    record.last_error = error
    record.status = "dead" if record.consecutive_failures >= _DEAD_AFTER_FAILURES else "degraded"
    session.add(record)
    await session.commit()
    logger.warning(
        f"Session validation failed ({record.consecutive_failures}x): "
        f"tenant={tenant_id} platform={platform} status={record.status} error={error}"
    )
    return record.status


async def ensure_healthy_session(
    session: AsyncSession,
    tenant_id: str,
    platform: str,
    validator: Callable[[dict], Awaitable[tuple[bool, str | None]]],
) -> dict:
    """Pre-flight check for scrape commands: load the saved session, run its
    validator, and only return the storage_state if the platform actually
    still accepts it. Raises SessionUnhealthy (not a silent None) so a scrape
    fails fast with a clear "please re-login" message instead of burning
    time on real work with a session that's already dead."""
    storage_state = await load_session(session, tenant_id, platform)
    if not storage_state:
        raise SessionUnhealthy(f"No saved session for tenant={tenant_id} platform={platform} — run the login command first")

    ok, error = await validator(storage_state)
    status = await record_validation(session, tenant_id, platform, ok, error)

    if not ok:
        raise SessionUnhealthy(
            f"Session for tenant={tenant_id} platform={platform} is {status} ({error}) — re-login required"
        )

    return storage_state
