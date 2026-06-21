"""Client-scoped scrape-job history. Mounted under /clients/{client_id}/jobs."""
import uuid

from fastapi import APIRouter, HTTPException, status

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.common import Page
from app.schemas.job import JobOut
from app.services import job_service

router = APIRouter()


@router.get("", response_model=Page[JobOut])
async def list_jobs(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    status: str | None = None,
):
    return await job_service.list_jobs(
        session, tenant_id=client.id, pagination=pagination, status=status
    )


@router.get("/{job_id}", response_model=JobOut)
async def job_detail(session: SessionDep, client: ClientDep, job_id: uuid.UUID):
    job = await job_service.get_job_for_client(
        session, job_id=job_id, tenant_id=client.id
    )
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    return job
