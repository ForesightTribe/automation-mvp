import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blinkit_seller import (
    BlinkitPO,
    BlinkitPOSnapshot,
    BlinkitSOH,
    BlinkitScorecardFacility,
    BlinkitScorecardKeySku,
    BlinkitScorecardWeekly,
    BlinkitSellerSale,
    BlinkitSellerSalesSummary,
)
from app.utils.logger import logger


async def save_scrape_results(session: AsyncSession, sales: list[dict], summary: dict) -> int:
    await _upsert(session, BlinkitSellerSale, sales)
    await _upsert(session, BlinkitSellerSalesSummary, [summary])
    await session.commit()
    logger.info(f"Blinkit seller sales saved — rows:{len(sales)} summary:1")
    return len(sales) + 1


async def save_po_results(session: AsyncSession, pos: list[dict], snapshot: dict) -> int:
    await _upsert(session, BlinkitPO, pos)
    await _upsert(session, BlinkitPOSnapshot, [snapshot])
    await session.commit()
    logger.info(f"Blinkit PO saved — rows:{len(pos)} snapshot:1")
    return len(pos) + 1


async def save_soh_results(session: AsyncSession, rows: list[dict]) -> int:
    await _upsert(session, BlinkitSOH, rows)
    await session.commit()
    logger.info(f"Blinkit SOH saved — rows:{len(rows)}")
    return len(rows)


async def save_scorecard_results(
    session: AsyncSession,
    weekly: dict,
    facilities: list[dict],
    key_skus: list[dict],
) -> int:
    await _upsert(session, BlinkitScorecardWeekly, [weekly])
    await _upsert(session, BlinkitScorecardFacility, facilities)
    await _upsert(session, BlinkitScorecardKeySku, key_skus)
    await session.commit()
    logger.info(
        f"Blinkit scorecard saved — weekly:1 facilities:{len(facilities)} skus:{len(key_skus)}"
    )
    return 1 + len(facilities) + len(key_skus)


async def _upsert(session: AsyncSession, model, rows: list[dict]) -> None:
    if not rows:
        return
    stmt = (
        insert(model)
        .values([_prepare(model, r) for r in rows])
        .on_conflict_do_update(
            index_elements=["upsert_key"],
            set_={c: insert(model).excluded[c] for c in _update_cols(model)},
        )
    )
    await session.execute(stmt)


def _prepare(model, row: dict) -> dict:
    data = dict(row)
    if "tenant_id" in data and isinstance(data["tenant_id"], str):
        data["tenant_id"] = uuid.UUID(data["tenant_id"])
    if "scrape_job_id" in data and isinstance(data["scrape_job_id"], str):
        data["scrape_job_id"] = uuid.UUID(data["scrape_job_id"])
    return data


def _update_cols(model) -> list[str]:
    pk = {"id", "upsert_key"}
    return [c.name for c in model.__table__.columns if c.name not in pk]
