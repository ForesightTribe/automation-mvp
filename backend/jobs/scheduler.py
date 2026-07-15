"""The scheduler — the PRODUCER half of the runner.

It reads `job_schedules`, and when a schedule's `next_run_at` is due it ENQUEUES a
job (a `pending` row) — it never executes anything itself; the consumer does that.
Because it re-reads the table every tick, editing/adding/disabling a schedule takes
effect within one tick with no restart. Schedules live in the DB, not a crontab, so
the future UI can manage them without SSH. See docs/jobs.md.

Cron is a standard 5-field crontab string interpreted in Asia/Kolkata. Next-fire
times are computed with APScheduler's CronTrigger (already a dependency) against the
fixed-offset IST — no extra timezone package needed. Times are stored as naive IST,
matching `now_ist()` everywhere else.
"""

import asyncio
from datetime import datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import JobSchedule
from app.utils.logger import logger
from app.utils.time import IST, now_ist
from jobs.queue import DuplicateActiveJob, enqueue


def validate_cron(cron_expr: str) -> None:
    """Raise ValueError if `cron_expr` isn't a valid 5-field crontab string."""
    CronTrigger.from_crontab(cron_expr, timezone=IST)


def next_fire_after(cron_expr: str, after: datetime) -> datetime:
    """The first fire time strictly at/after `after` (naive IST in, naive IST out)."""
    trigger = CronTrigger.from_crontab(cron_expr, timezone=IST)
    nxt = trigger.get_next_fire_time(None, after.replace(tzinfo=IST))
    return nxt.replace(tzinfo=None)


def initial_next_run(cron_expr: str) -> datetime:
    """The first fire from now — used when a schedule is created."""
    return next_fire_after(cron_expr, now_ist())


async def _fire(sched: JobSchedule, now: datetime) -> bool:
    """Enqueue one run of a due schedule. Returns True if a job was queued."""
    async with AsyncSessionLocal() as edb:
        try:
            job = await enqueue(
                edb,
                job_type=sched.job_type,
                tenant_id=sched.tenant_id,
                params=sched.params or {},
                priority=sched.priority,
                schedule_id=sched.id,
            )
        except DuplicateActiveJob:
            # The previous run of this schedule is still pending/running — don't
            # pile up. This is expected for a slow scrape vs a frequent cron.
            logger.warning(f"schedule '{sched.name}': previous run still active — skipped")
            return False
        except Exception as e:
            logger.error(f"schedule '{sched.name}': enqueue failed: {e}")
            return False
    logger.info(f"schedule '{sched.name}' → queued job {str(job.id)[:8]} [{job.lane.value}]")
    return True


async def tick(now: datetime | None = None) -> None:
    """One producer pass: fire every due, enabled schedule and advance its next run."""
    now = now or now_ist()
    grace = settings.SCHEDULER_MISFIRE_GRACE_SECONDS
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(JobSchedule).where(JobSchedule.enabled == True))  # noqa: E712
        ).scalars().all()

        for s in rows:
            if s.next_run_at is None:            # first sight — seed it, don't fire yet
                s.next_run_at = next_fire_after(s.cron, now)
                continue
            if s.next_run_at > now:              # not due
                continue

            late = (now - s.next_run_at).total_seconds()
            if late > grace and not s.catchup:
                logger.info(
                    f"schedule '{s.name}': missed run due {s.next_run_at} skipped (catchup off)"
                )
            elif await _fire(s, now):
                s.last_enqueued_at = now

            # Advance past the current minute so we never re-fire the same slot.
            s.next_run_at = next_fire_after(s.cron, now + timedelta(minutes=1))

        await db.commit()


async def run_producer(shutdown: asyncio.Event) -> None:
    """Poll `job_schedules` on an interval until shutdown. Runs alongside the
    consumer inside the runner process."""
    if not settings.SCHEDULER_ENABLED:
        logger.info("scheduler disabled (SCHEDULER_ENABLED=false) — consumer only")
        return
    logger.info(f"scheduler producer started · tick={settings.SCHEDULER_TICK_SECONDS}s")
    while not shutdown.is_set():
        try:
            await tick()
        except Exception as e:
            logger.error(f"scheduler tick failed: {e}")
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=settings.SCHEDULER_TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("scheduler producer stopped")
