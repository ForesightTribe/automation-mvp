from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.utils.logger import logger
from scraper.scheduler.jobs import run_public_scrapes

scheduler = AsyncIOScheduler()


def start_scheduler():
    """Register jobs and start the scheduler. Not called at app startup yet —
    wire it into the FastAPI lifespan (or a worker) to enable automated runs.
    Kept opt-in so dev servers don't fire browser scrapes unexpectedly."""
    scheduler.add_job(
        run_public_scrapes,
        CronTrigger(hour=3, minute=0),  # daily 03:00 IST
        id="public_scrape_daily",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — public scrape daily @ 03:00")


def stop_scheduler():
    scheduler.shutdown()
    logger.info("Scheduler stopped")
