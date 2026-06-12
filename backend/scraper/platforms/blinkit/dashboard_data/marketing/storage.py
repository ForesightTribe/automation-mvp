import asyncio
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.utils.logger import logger
from scraper.utils.storage import upsert_one, upsert_many


async def save_scrape_results(
    db: AsyncIOMotorDatabase,
    summary: dict,
    campaigns: list[dict],
    sov: list[dict],
    collections: list[dict],
    plans: list[dict],
) -> int:
    await asyncio.gather(
        upsert_one(db, "ad_performance_summary", summary),
        upsert_many(db, "ad_campaigns", campaigns),
        upsert_many(db, "sponsored_sov", sov),
        upsert_many(db, "brand_collections", collections),
        upsert_many(db, "visibility_plans", plans),
    )

    logger.info(
        f"Blinkit marketing saved — summary: 1, campaigns: {len(campaigns)}, "
        f"sov: {len(sov)}, collections: {len(collections)}, plans: {len(plans)}"
    )
    return 1 + len(campaigns) + len(sov) + len(collections) + len(plans)
