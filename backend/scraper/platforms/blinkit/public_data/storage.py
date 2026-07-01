import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search import SearchSnapshot, SearchListing
from app.utils.logger import logger
from app.utils.time import now_ist
from scraper.utils.storage import ensure_refs


def _as_uuid(value) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


async def save(session: AsyncSession, result: dict, tenant_id, job_id=None) -> int:
    """Persist one search as a header (`search_snapshots`) + N detail rows
    (`search_listings`), tagged with `tenant_id` + `job_id`. Returns rows written.

    Append-only (public data is never upserted). `ensure_refs` upserts the brand
    rows for the own brand and every competitor slug so the FKs resolve.
    """
    tid = _as_uuid(tenant_id)
    jid = _as_uuid(job_id)
    listings = result.get("listings", [])
    scraped_at = now_ist()

    slugs = {result["brand_slug"]} | {
        l["brand_slug"] for l in listings if l.get("brand_slug")
    }
    for slug in slugs:
        await ensure_refs(session, slug, "blinkit")

    snapshot = SearchSnapshot(
        tenant_id=tid,
        job_id=jid,
        brand_slug=result["brand_slug"],
        mp_slug="blinkit",
        keyword=result["keyword"],
        city=result.get("city", ""),
        zone=result.get("zone", ""),
        pincode=result.get("pincode", ""),
        lat=result.get("lat"),
        lon=result.get("lon"),
        scraped_at=scraped_at,
        brand_rank=result.get("brand_rank"),
        brand_sov=result.get("brand_sov_pct"),
        total_results=result.get("total_results"),
    )
    session.add(snapshot)
    await session.flush()  # assign snapshot.id for the FK below

    for l in listings:
        session.add(
            SearchListing(
                snapshot_id=snapshot.id,
                tenant_id=tid,
                job_id=jid,
                mp_slug="blinkit",
                brand_slug=l.get("brand_slug"),
                keyword=result["keyword"],
                city=result.get("city", ""),
                zone=result.get("zone", ""),
                pincode=result.get("pincode", ""),
                scraped_at=scraped_at,
                position=l.get("position"),
                product_name=l.get("name", ""),
                is_brand=l.get("is_brand", False),
                price=l.get("price"),
                mrp=l.get("mrp"),
                discount_pct=l.get("discount_pct"),
                in_stock=l.get("in_stock", True),
                inventory=l.get("inventory"),
                platform_product_id=l.get("product_id") or None,
                extra={
                    "group_id": l.get("group_id"),
                    "merchant_id": l.get("merchant_id"),
                    "merchant_type": l.get("merchant_type"),
                    "unit": l.get("unit"),
                    "ptype": l.get("ptype"),
                    "category": l.get("category"),
                    "match_reason": l.get("match_reason"),
                    "image_url": l.get("image_url"),
                },
            )
        )

    await session.commit()
    written = 1 + len(listings)
    logger.info(
        f"blinkit public | saved snapshot + {len(listings)} listings "
        f"tenant={tid} kw='{result['keyword']}' "
        f"rank={result.get('brand_rank')} sov={result.get('brand_sov_pct')}%"
    )
    return written
