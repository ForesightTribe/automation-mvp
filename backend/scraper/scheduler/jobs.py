from app.utils.logger import logger


async def scrape_blinkit(tenant_id: str, credentials: dict):
    from scraper.platforms.blinkit.scraper import BlinkitScraper
    scraper = BlinkitScraper(tenant_id=tenant_id, credentials=credentials)
    data = await scraper.run_all()
    logger.info(f"Blinkit scrape complete for tenant {tenant_id}")
    return data
