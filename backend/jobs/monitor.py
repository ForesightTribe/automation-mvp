"""Deadman / heartbeat monitoring — the `monitor.heartbeat` job.

The alert that matters isn't CPU — it's "the 3am scrape silently didn't run." This
checks, for every enabled schedule, that a job of its (job_type, tenant) has SUCCEEDED
since the schedule was last DUE (`missed_fire`), and that the disk isn't filling up. Any
problem is logged at ERROR — which a Cloud Logging alert turns into an email. Run it on
its own schedule (e.g. hourly). See docs/jobs.md.
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus, JobSchedule
from app.models.tenant import Tenant
from app.utils.logger import logger
from app.utils.time import now_ist
from jobs.scheduler import previous_fire_before
from jobs.types import schedule_label

try:
    import psutil
except ImportError:
    psutil = None


# The heartbeat must NOT monitor itself. Its check gates on its own past success, so
# a single failure could never recover: a failing heartbeat records no success, which
# is precisely the condition it reports — a self-perpetuating failure loop. (Observed
# for real on the VM, 2026-07-16.) "Who watches the watchman" is answered OUTSIDE this
# system, by a Cloud Monitoring uptime / log-absence alert — see
# deploy/ops-agent-logging.yaml.
_SELF_MONITORING_TYPES = {"monitor.heartbeat"}


def missed_fire(cron: str, *, last_success: datetime | None, created_at: datetime,
                now: datetime, grace_seconds: float) -> datetime | None:
    """The most recent fire this schedule should have completed but hasn't → None if healthy.

    Asks "has it succeeded since the last time it was DUE?" rather than "has it succeeded
    within one cadence?". The old cadence test derived the gap from the next two fires,
    which for an hour-restricted cron is the in-window step: `*/15 15-17 * * *` was held to
    a success every 16 minutes around the clock, so from 18:00 until 15:00 the next day it
    was always "overdue". That fired every hour, every night, from 2026-09-07 (the Dobra bid
    optimiser) — a false alarm that also buried the real ones.

    `grace_seconds` is the scheduler's own misfire window: a fire that recent has not had
    time to finish, so it is not counted as missed yet. A schedule cannot miss a fire that
    was due before it existed.
    """
    due = previous_fire_before(cron, now - timedelta(seconds=grace_seconds))
    if due is None or due <= created_at:
        return None
    if last_success is not None and last_success >= due:
        return None
    return due


def _ago(delta: timedelta) -> str:
    """'40 min' / '16h' — an alert reads better without six decimal places of precision."""
    mins = delta.total_seconds() / 60
    return f"{mins:.0f} min" if mins < 90 else f"{mins / 60:.0f}h"


async def check_deadman(now: datetime | None = None) -> list[str]:
    """One issue string per enabled schedule with no success since it was last due.

    A recurring row is judged against its own cron (`missed_fire`), so a schedule that only
    fires in a window is silent between windows. A one-shot is overdue once its single fire
    time plus the misfire grace has passed while it is still enabled.
    """
    now = now or now_ist()
    issues: list[str] = []
    async with AsyncSessionLocal() as db:
        scheds = (
            await db.execute(select(JobSchedule).where(JobSchedule.enabled == True))  # noqa: E712
        ).scalars().all()
        # One lookup for the run: an alert must say WHOSE schedule is overdue, and the
        # reconciler's names carry only a tenant UUID.
        tenants = dict((await db.execute(select(Tenant.id, Tenant.name))).all())

        grace = settings.SCHEDULER_MISFIRE_GRACE_SECONDS
        for s in scheds:
            if s.job_type in _SELF_MONITORING_TYPES:
                continue

            # One-shots have no cron to look back over. They are not overdue until their
            # single fire time passes; a fired one-shot disables itself, so any one-shot
            # still enabled past its next_run_at genuinely failed to fire.
            recurring = bool(s.repeat and s.cron)
            if not recurring and (s.next_run_at is None
                                  or now - s.next_run_at <= timedelta(seconds=grace)):
                continue

            q = select(func.max(Job.completed_at)).where(
                Job.job_type == s.job_type, Job.status == JobStatus.success
            )
            q = q.where(Job.tenant_id.is_(None) if s.tenant_id is None
                        else Job.tenant_id == s.tenant_id)
            last = (await db.execute(q)).scalar()

            if recurring:
                due = missed_fire(s.cron, last_success=last, created_at=s.created_at,
                                  now=now, grace_seconds=grace)
                if due is None:
                    continue
            else:
                due = s.next_run_at

            # Read the SCHEDULE's label, not its raw name: a reconciler-owned row is
            # named `auto:cm:budget:<uuid>:blinkit:0200`, and an alert is the worst
            # possible place to make someone decode one.
            who = schedule_label(s.name, tenants.get(s.tenant_id))
            late = _ago(now - due)
            if last is None:
                issues.append(
                    f"'{who}' ({s.job_type}): has never succeeded — the run due "
                    f"{due:%Y-%m-%d %H:%M} ({late} ago) did not complete"
                )
            else:
                issues.append(
                    f"'{who}' ({s.job_type}): the run due {due:%Y-%m-%d %H:%M} "
                    f"({late} ago) did not complete — last success {last:%Y-%m-%d %H:%M}"
                )
    return issues


def check_disk(threshold_pct: int) -> list[str]:
    """One issue string if the LOG_DIR partition is at/over the threshold."""
    if psutil is None:
        return []
    try:
        usage = psutil.disk_usage(settings.LOG_DIR)
    except OSError:
        return []
    if usage.percent >= threshold_pct:
        return [f"disk at {usage.percent:.0f}% (>= {threshold_pct}%) on {settings.LOG_DIR}"]
    return []


async def heartbeat(disk_pct: int = 80) -> list[str]:
    """Run all checks, log each problem at ERROR, return the issues. Empty = healthy."""
    issues = await check_deadman()
    issues += check_disk(disk_pct)
    for i in issues:
        logger.error(f"HEARTBEAT: {i}")
    if not issues:
        logger.info("heartbeat: all healthy")
    return issues
