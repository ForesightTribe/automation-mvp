from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search import SearchResult
from app.utils.logger import logger
from scraper.utils.storage import ensure_refs


async def save(session: AsyncSession, result: dict) -> None:
    await ensure_refs(session, result["brand_slug"], "instamart")
    sr = SearchResult(
        brand_slug=result["brand_slug"],
        mp_slug="instamart",
        city=result.get("city", ""),
        zone=result.get("zone", ""),
        pincode=result.get("pincode", ""),
        keyword=result["keyword"],
        brand_rank=result.get("brand_rank"),
        brand_sov=result.get("brand_sov_pct"),
        total_results=result.get("total_results"),
        products=result.get("brand_products"),
        competitors=result.get("competitors"),
        raw={k: v for k, v in result.items() if k not in {"brand_products", "competitors"}},
    )
    session.add(sr)
    await session.commit()
    logger.info(
        f"instamart public | saved {result['brand_slug']} / {result['keyword']} "
        f"city={result.get('city')} zone={result.get('zone')} rank={result.get('brand_rank')}"
    )
