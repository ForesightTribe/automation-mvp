"""Brand Portal writes — sales and ads, every table an ON CONFLICT (upsert_key)
DO UPDATE (common.upsert), so re-running any window overwrites in place.

    sales   instamart_seller_store_daily   date|store|item
            instamart_brand_city_daily     date|city
    ads     instamart_ad_campaigns         campaign (lifetime totals)
            instamart_ad_account_daily     date
            instamart_ad_product_daily     date|candidate[|campaign]
            instamart_ad_keyword_daily     date|keyword[|campaign]
            instamart_product_catalog      (tenant_id, candidate_id)
"""
import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InstamartAdAccountDaily, InstamartAdCampaign, InstamartAdKeywordDaily,
    InstamartAdProductDaily, InstamartBrandCityDaily, InstamartProductCatalog,
    InstamartSellerStoreDaily,
)
from app.utils.time import now_ist
from scraper.platforms.instamart.dashboard_data.common import PLATFORM, upsert, upsert_key


def _stamp(rows: list[dict], tenant_id: str, scrape_job_id: uuid.UUID | None) -> uuid.UUID:
    """Add the bookkeeping columns every Instamart table shares. Returns the tenant uuid."""
    tid = uuid.UUID(str(tenant_id))
    stamped = now_ist()
    for row in rows:
        row["tenant_id"] = tid
        row["platform"] = PLATFORM
        row["scrape_job_id"] = scrape_job_id
        row["scraped_at"] = stamped
    return tid


# ── sales ────────────────────────────────────────────────────────────────────

async def save_sales(session: AsyncSession, tenant_id: str,
                     store_rows: list[dict], brand_rows: list[dict],
                     scrape_job_id: uuid.UUID | None = None) -> dict[str, int]:
    """Both grains of the report. A 31-day report and a single-day report for a
    date inside it produce the same keys. Returns rows written per table."""
    tid = _stamp(store_rows, tenant_id, scrape_job_id)
    _stamp(brand_rows, tenant_id, scrape_job_id)
    for row in store_rows:
        row["upsert_key"] = upsert_key(PLATFORM, tid, row["date"], row["store_id"], row["item_code"])
    for row in brand_rows:
        row["upsert_key"] = upsert_key(PLATFORM, tid, row["date"], row["city"])
    return {
        "store_daily": await upsert(session, InstamartSellerStoreDaily, store_rows),
        "brand_city": await upsert(session, InstamartBrandCityDaily, brand_rows),
    }


# ── ads ──────────────────────────────────────────────────────────────────────

async def save_campaigns(session: AsyncSession, tenant_id: str, rows: list[dict],
                         scrape_job_id: uuid.UUID | None = None) -> int:
    tid = _stamp(rows, tenant_id, scrape_job_id)
    for r in rows:
        r["upsert_key"] = upsert_key(PLATFORM, tid, r["campaign_id"])
    return await upsert(session, InstamartAdCampaign, rows)


async def save_account_daily(session: AsyncSession, tenant_id: str, rows: list[dict],
                             scrape_job_id: uuid.UUID | None = None) -> int:
    tid = _stamp(rows, tenant_id, scrape_job_id)
    for r in rows:
        r["upsert_key"] = upsert_key(PLATFORM, tid, r["date"])
    return await upsert(session, InstamartAdAccountDaily, rows)


async def _save_asset_daily(session: AsyncSession, model, tenant_id: str, rows: list[dict],
                            key_field: str, scrape_job_id: uuid.UUID | None) -> int:
    tid = _stamp(rows, tenant_id, scrape_job_id)
    for r in rows:
        r.setdefault("campaign_id", None)
        # campaign_id splits one date+product/keyword into a row per contributing
        # campaign -- WITHOUT it in the key, two campaigns advertising the same
        # product on the same day would collide and only the last one would
        # survive, silently losing the other's spend.
        suffix = f"|{r['campaign_id']}" if r["campaign_id"] else ""
        r["upsert_key"] = f"{upsert_key(PLATFORM, tid, r['date'], r[key_field])}{suffix}"
    return await upsert(session, model, rows)


async def save_products_daily(session: AsyncSession, tenant_id: str, rows: list[dict],
                              scrape_job_id: uuid.UUID | None = None) -> int:
    return await _save_asset_daily(session, InstamartAdProductDaily, tenant_id, rows,
                                   "candidate_id", scrape_job_id)


async def save_keywords_daily(session: AsyncSession, tenant_id: str, rows: list[dict],
                              scrape_job_id: uuid.UUID | None = None) -> int:
    return await _save_asset_daily(session, InstamartAdKeywordDaily, tenant_id, rows,
                                   "keyword", scrape_job_id)


async def save_product_catalog(session: AsyncSession, tenant_id: str, rows: list[dict]) -> int:
    """Name + image per product. Keyed on (tenant_id, candidate_id), not an
    upsert_key, and only the three descriptive columns are updated."""
    if not rows:
        return 0
    tid = uuid.UUID(str(tenant_id))
    stamped = now_ist()
    for r in rows:
        r["tenant_id"] = tid
        r["scraped_at"] = stamped
    stmt = insert(InstamartProductCatalog).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "candidate_id"],
        set_={
            "product_name": stmt.excluded.product_name,
            "image_url": stmt.excluded.image_url,
            "scraped_at": stmt.excluded.scraped_at,
        },
    )
    await session.execute(stmt)
    return len(rows)
