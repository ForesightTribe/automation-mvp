from app.core.database import AsyncSessionLocal
from app.utils.logger import logger
from scraper.public import orchestrator


async def run_public_scrapes():
    """Daily public scrape for every active tenant (Blinkit), driven by each
    tenant's watchlist + selected locations. One scrape_job per tenant."""
    async with AsyncSessionLocal() as db:
        summaries = await orchestrator.run_all(db)
    total_rows = sum(s["rows"] for s in summaries)
    logger.info(
        f"scheduled public scrape: {len(summaries)} tenant(s), {total_rows} rows"
    )
    return summaries
