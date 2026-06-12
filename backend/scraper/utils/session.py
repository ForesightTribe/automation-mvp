import json
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.utils.encryption import encrypt, decrypt
from app.utils.logger import logger

_COLLECTION = "platform_sessions"


async def save_session(db: AsyncIOMotorDatabase, tenant_id: str, platform: str, storage_state: dict) -> None:
    encrypted = encrypt(json.dumps(storage_state))
    now = datetime.now(timezone.utc)
    await db[_COLLECTION].update_one(
        {"tenant_id": tenant_id, "platform": platform},
        {
            "$set": {"encrypted_session": encrypted, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    logger.info(f"Session saved: tenant={tenant_id} platform={platform}")


async def load_session(db: AsyncIOMotorDatabase, tenant_id: str, platform: str) -> dict | None:
    doc = await db[_COLLECTION].find_one({"tenant_id": tenant_id, "platform": platform})
    if not doc:
        logger.warning(f"No session found: tenant={tenant_id} platform={platform}")
        return None
    return json.loads(decrypt(doc["encrypted_session"]))


async def session_exists(db: AsyncIOMotorDatabase, tenant_id: str, platform: str) -> bool:
    doc = await db[_COLLECTION].find_one(
        {"tenant_id": tenant_id, "platform": platform},
        {"_id": 1},
    )
    return doc is not None
