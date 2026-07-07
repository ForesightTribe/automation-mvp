"""Targeted own-SKU storage — writes `sku_snapshots` (append-only).

One row per own product at one store, keyed on `platform_product_id`. Fed by the
brand-query scrape (own-brand listings from `classify_products`). Unlike the
keyword scrape's header+detail, this is a single flat fact table: ids + name +
the volatile metrics (price, mrp, discount, stock, inventory, rating).
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search import SkuSnapshot
from app.utils.logger import logger
from app.utils.time import now_ist
from scraper.utils.search_result import is_combo_name
from scraper.utils.storage import ensure_refs

MP = "blinkit"


def _as_uuid(value) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


async def save_skus(
    session: AsyncSession,
    listings: list[dict],
    brand_slug: str,
    tenant_id,
    job_id=None,
    *,
    merchant_id: str = "",
    city: str = "",
    lat: float | None = None,
    lon: float | None = None,
    ensured: set | None = None,
) -> int:
    """Persist one store's own-brand listings as `sku_snapshots` rows. Returns rows
    written. `ensured` is a per-run cache so `ensure_refs` runs once per brand."""
    tid = _as_uuid(tenant_id)
    jid = _as_uuid(job_id)

    if ensured is None or brand_slug not in ensured:
        await ensure_refs(session, brand_slug, MP)
        if ensured is not None:
            ensured.add(brand_slug)

    scraped_at = now_ist()
    for l in listings:
        name = l.get("name", "")
        session.add(
            SkuSnapshot(
                tenant_id=tid,
                job_id=jid,
                mp_slug=MP,
                brand_slug=brand_slug,
                platform_product_id=(l.get("product_id") or ""),
                product_name=name,
                is_combo=is_combo_name(name),
                merchant_id=(l.get("merchant_id") or merchant_id),
                city=city,
                lat=lat,
                lon=lon,
                scraped_at=scraped_at,
                price=l.get("price"),
                mrp=l.get("mrp"),
                discount_pct=l.get("discount_pct"),
                in_stock=l.get("in_stock", True),
                inventory=l.get("inventory"),
                rating=l.get("rating"),
            )
        )

    await session.commit()
    logger.debug(
        f"blinkit skus | saved {len(listings)} rows tenant={tid} "
        f"brand={brand_slug} store={merchant_id or lat}"
    )
    return len(listings)
