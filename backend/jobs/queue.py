"""The job queue — DB operations for the `jobs` table.

The queue is just rows: `status='pending'` means "in the queue". Claiming is a
single atomic UPDATE with `FOR UPDATE SKIP LOCKED`, so two runners can never grab
the same job and lane slot counts are enforced by the database, not by hopeful
in-process state.

Distinct from `app/services/job_service.py`, which serves the existing `scrape_jobs`
table (internal scrape progress); this queue sits above it.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models.job import Job, JobStatus, Lane
from app.utils.time import now_ist
from jobs.types import spec_for


class DuplicateActiveJob(Exception):
    """A job of this (job_type, tenant_id) is already pending or running."""


async def enqueue(
    db,
    job_type: str,
    tenant_id: uuid.UUID | None = None,
    params: dict[str, Any] | None = None,
    priority: int = 100,
    scheduled_for: datetime | None = None,
    schedule_id: int | None = None,
) -> Job:
    """Insert a pending job. Lane is derived from the type. Raises
    DuplicateActiveJob if the overlap guard rejects it."""
    spec = spec_for(job_type)  # validates job_type
    if spec.needs_tenant and tenant_id is None:
        raise ValueError(f"{job_type} requires a tenant_id")

    job = Job(
        job_type=job_type,
        lane=spec.lane,
        tenant_id=tenant_id,
        params=params or {},
        priority=priority,
        scheduled_for=scheduled_for or now_ist(),
        schedule_id=schedule_id,
    )
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise DuplicateActiveJob(
            f"a {job_type} job for tenant {tenant_id} is already active"
        ) from None
    await db.refresh(job)
    return job


# Claim: flip the single oldest eligible pending job in a lane to running,
# atomically. SKIP LOCKED lets concurrent claims (or lanes) not block each other.
_CLAIM_SQL = text(
    """
    UPDATE jobs SET status = 'running', locked_at = :now, locked_by = :worker,
                    started_at = :now, attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'pending' AND lane = :lane AND scheduled_for <= :now
        ORDER BY priority, scheduled_for
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id
    """
)


async def claim_one(db, lane: Lane, worker_id: str) -> Job | None:
    """Claim the next eligible job in `lane`, or None if the lane is empty."""
    now = now_ist()
    row = (
        await db.execute(
            _CLAIM_SQL, {"now": now, "worker": worker_id, "lane": lane.value}
        )
    ).first()
    await db.commit()
    if row is None:
        return None
    return await db.get(Job, row[0])


async def mark_started(db, job_id: uuid.UUID, argv: str, log_path: str) -> None:
    job = await db.get(Job, job_id)
    job.argv = argv
    job.log_path = log_path
    await db.commit()


async def complete(
    db,
    job_id: uuid.UUID,
    status: JobStatus,
    exit_code: int | None = None,
    error: str | None = None,
    peak_rss_mb: int | None = None,
    ref_job_id: uuid.UUID | None = None,
) -> None:
    job = await db.get(Job, job_id)
    job.status = status
    job.exit_code = exit_code
    job.error = error
    job.peak_rss_mb = peak_rss_mb
    if ref_job_id is not None:
        job.ref_job_id = ref_job_id
    job.completed_at = now_ist()
    await db.commit()


async def reap_stale(db, hostname: str, pid_alive) -> int:
    """Fail any `running` job this host owns whose runner PID is gone.

    Called on runner startup. Without this, a crash mid-job leaves a row stuck at
    `running` forever — and the overlap guard would then reject every future run of
    that (job_type, tenant) as a duplicate, silently and permanently. `pid_alive`
    is a callable pid->bool (psutil.pid_exists).
    """
    prefix = f"{hostname}:"
    rows = (
        await db.execute(
            select(Job).where(
                Job.status == JobStatus.running, Job.locked_by.startswith(prefix)
            )
        )
    ).scalars().all()

    reaped = 0
    for job in rows:
        try:
            pid = int(job.locked_by.split(":", 1)[1])
        except (ValueError, IndexError):
            pid = -1
        if not pid_alive(pid):
            job.status = JobStatus.failed
            job.error = "runner_died"
            job.completed_at = now_ist()
            reaped += 1
    if reaped:
        await db.commit()
    return reaped


async def recent(db, limit: int = 20, lane: Lane | None = None) -> list[Job]:
    q = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if lane is not None:
        q = q.where(Job.lane == lane)
    return list((await db.execute(q)).scalars().all())
