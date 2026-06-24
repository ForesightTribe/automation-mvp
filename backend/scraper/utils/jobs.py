import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.job import ScrapeJob, JobStatus
from app.utils.logger import logger
from app.utils.time import now_ist


async def create_scrape_job(session: AsyncSession, tenant_id: str, dashboard: str, platform: str = "blinkit") -> str:
    job = ScrapeJob(
        tenant_id=uuid.UUID(tenant_id),
        platform=platform,
        dashboard=dashboard,
        status=JobStatus.running,
        started_at=now_ist(),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    logger.info(f"Scrape job created: {job.id} tenant={tenant_id} dashboard={dashboard}")
    return str(job.id)


async def complete_scrape_job(session: AsyncSession, job_id: str, records_written: int = 0) -> None:
    result = await session.execute(select(ScrapeJob).where(ScrapeJob.id == uuid.UUID(job_id)))
    job = result.scalars().first()
    if job:
        job.status = JobStatus.success
        job.completed_at = now_ist()
        job.records_written = records_written
        await session.commit()
    logger.info(f"Scrape job completed: {job_id} records={records_written}")


async def fail_scrape_job(session: AsyncSession, job_id: str, error: str) -> None:
    # The failure may have aborted the current transaction (e.g. a bad INSERT);
    # roll back so we can still record the failure instead of masking the real
    # error with InFailedSQLTransactionError.
    await session.rollback()
    result = await session.execute(select(ScrapeJob).where(ScrapeJob.id == uuid.UUID(job_id)))
    job = result.scalars().first()
    if job:
        job.status = JobStatus.failed
        job.completed_at = now_ist()
        job.error = error
        await session.commit()
    logger.error(f"Scrape job failed: {job_id} — {error}")
