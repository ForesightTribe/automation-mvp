import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select

from app.models.job import PlatformSession
from app.utils.encryption import encrypt, decrypt
from app.utils.logger import logger


async def save_session(session: AsyncSession, tenant_id: str, platform: str, storage_state: dict) -> None:
    encrypted = encrypt(json.dumps(storage_state))
    now = datetime.now(timezone.utc)

    stmt = (
        insert(PlatformSession)
        .values(
            tenant_id=uuid.UUID(tenant_id),
            platform=platform,
            encrypted_session=encrypted,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "platform"],
            set_={"encrypted_session": encrypted, "updated_at": now},
        )
    )
    await session.execute(stmt)
    await session.commit()
    logger.info(f"Session saved: tenant={tenant_id} platform={platform}")


async def load_session(session: AsyncSession, tenant_id: str, platform: str) -> dict | None:
    result = await session.exec(
        select(PlatformSession).where(
            PlatformSession.tenant_id == uuid.UUID(tenant_id),
            PlatformSession.platform == platform,
        )
    )
    record = result.first()
    if not record:
        logger.warning(f"No session found: tenant={tenant_id} platform={platform}")
        return None
    return json.loads(decrypt(record.encrypted_session))


async def session_exists(session: AsyncSession, tenant_id: str, platform: str) -> bool:
    result = await session.exec(
        select(PlatformSession).where(
            PlatformSession.tenant_id == uuid.UUID(tenant_id),
            PlatformSession.platform == platform,
        )
    )
    return result.first() is not None
