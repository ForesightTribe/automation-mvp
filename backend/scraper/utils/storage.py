from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne
from typing import Any


def make_upsert_key(*parts: Any) -> str:
    return ":".join(str(p) for p in parts)


async def upsert_one(db: AsyncIOMotorDatabase, collection: str, doc: dict) -> None:
    await db[collection].update_one(
        {"upsert_key": doc["upsert_key"]},
        {"$set": doc},
        upsert=True,
    )


async def upsert_many(db: AsyncIOMotorDatabase, collection: str, docs: list[dict]) -> int:
    if not docs:
        return 0
    ops = [
        UpdateOne({"upsert_key": doc["upsert_key"]}, {"$set": doc}, upsert=True)
        for doc in docs
    ]
    result = await db[collection].bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count
