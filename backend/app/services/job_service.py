"""Client-scoped scrape-job history (data freshness / failures)."""
import uuid

from sqlalchemy import func
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.job import ScrapeJob
from app.schemas.common import Page
from app.schemas.job import JobOut


async def list_jobs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    status: str | None = None,
) -> Page[JobOut]:
    cond = [ScrapeJob.tenant_id == tenant_id]
    if status:
        cond.append(ScrapeJob.status == status)

    total = (
        await session.execute(
            select(func.count()).select_from(ScrapeJob).where(*cond)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(ScrapeJob)
            .where(*cond)
            .order_by(ScrapeJob.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()
    return Page.build([JobOut.model_validate(r) for r in rows], total, pagination)


async def get_job_for_client(
    session: AsyncSession, *, job_id: uuid.UUID, tenant_id: uuid.UUID
) -> ScrapeJob | None:
    job = await session.get(ScrapeJob, job_id)
    if not job or job.tenant_id != tenant_id:
        return None
    return job
