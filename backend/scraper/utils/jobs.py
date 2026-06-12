from datetime import datetime, timezone
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.utils.logger import logger


async def create_scrape_job(db: AsyncIOMotorDatabase, tenant_id: str, platform: str) -> str:
    result = await db["scrape_jobs"].insert_one({
        "tenant_id": tenant_id,
        "platform": platform,
        "status": "running",
        "started_at": datetime.now(timezone.utc),
        "finished_at": None,
        "error_message": None,
    })
    job_id = str(result.inserted_id)
    logger.info(f"Scrape job created: {job_id} tenant={tenant_id} platform={platform}")
    return job_id


async def complete_scrape_job(db: AsyncIOMotorDatabase, job_id: str) -> None:
    await db["scrape_jobs"].update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": "completed", "finished_at": datetime.now(timezone.utc)}},
    )
    logger.info(f"Scrape job completed: {job_id}")


async def fail_scrape_job(db: AsyncIOMotorDatabase, job_id: str, error: str) -> None:
    await db["scrape_jobs"].update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": "failed", "finished_at": datetime.now(timezone.utc), "error_message": error}},
    )
    logger.error(f"Scrape job failed: {job_id} — {error}")
