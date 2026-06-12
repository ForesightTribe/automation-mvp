import asyncio
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.utils.logger import logger
from scraper.utils.storage import upsert_one, upsert_many


async def save_scrape_results(
    db: AsyncIOMotorDatabase,
    sales: list[dict],
    summary: dict,
) -> int:
    await asyncio.gather(
        upsert_many(db, "blinkit_seller_sales", sales),
        upsert_one(db, "blinkit_seller_sales_summary", summary),
    )

    logger.info(f"Blinkit seller sales saved — rows: {len(sales)}, summary: 1")
    return len(sales) + 1


async def save_po_results(
    db: AsyncIOMotorDatabase,
    pos: list[dict],
    snapshot: dict,
) -> int:
    await asyncio.gather(
        upsert_many(db, "blinkit_pos", pos),
        upsert_one(db, "blinkit_po_snapshots", snapshot),
    )

    logger.info(f"Blinkit PO saved — rows: {len(pos)}, snapshot: 1")
    return len(pos) + 1


async def save_soh_results(
    db: AsyncIOMotorDatabase,
    rows: list[dict],
) -> int:
    await upsert_many(db, "blinkit_soh", rows)
    logger.info(f"Blinkit SOH saved — rows: {len(rows)}")
    return len(rows)


async def save_scorecard_results(
    db: AsyncIOMotorDatabase,
    weekly: dict,
    facilities: list[dict],
    key_skus: list[dict],
) -> int:
    tasks = [upsert_one(db, "blinkit_scorecard_weekly", weekly)]
    if facilities:
        tasks.append(upsert_many(db, "blinkit_scorecard_facilities", facilities))
    if key_skus:
        tasks.append(upsert_many(db, "blinkit_scorecard_key_skus", key_skus))
    await asyncio.gather(*tasks)

    logger.info(
        f"Blinkit scorecard saved — weekly: 1, facilities: {len(facilities)}, skus: {len(key_skus)}"
    )
    return 1 + len(facilities) + len(key_skus)
