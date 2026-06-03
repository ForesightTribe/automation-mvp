from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.utils.logger import logger

scheduler = AsyncIOScheduler()


def start_scheduler():
    # Add platform jobs here as scrapers are implemented, e.g.:
    # scheduler.add_job(scrape_blinkit_job, "interval", hours=6, id="blinkit_scrape")
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler():
    scheduler.shutdown()
    logger.info("Scheduler stopped")
