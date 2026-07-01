from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger import logger


async def save(session: AsyncSession, result: dict, tenant_id=None, job_id=None) -> int:
    """No-op. Instamart public scraping is out of scope for now (Blinkit-only);
    kept signature-compatible with the Blinkit writer so the CLI loop is uniform."""
    logger.warning(
        "instamart public | save skipped — Blinkit-only for now; "
        f"keyword={result.get('keyword')} brand={result.get('brand_slug')}"
    )
    return 0
