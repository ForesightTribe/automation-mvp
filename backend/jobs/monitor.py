"""Deadman / heartbeat monitoring — the `monitor.heartbeat` job.

The alert that matters isn't CPU — it's "the 3am scrape silently didn't run." This
checks, for every enabled schedule, that a job of its (job_type, tenant) has
SUCCEEDED within its expected window (derived from the cron period), and that the
disk isn't filling up. Any problem is logged at ERROR — which a Cloud Logging alert
turns into an email. Run it on its own schedule (e.g. hourly). See docs/jobs.md.
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus, JobSchedule
from app.utils.logger import logger
from app.utils.time import now_ist
from jobs.scheduler import next_fire_after

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


def _cron_period(cron: str, now: datetime) -> timedelta:
    """The gap between two consecutive fires — the schedule's expected cadence."""
    n1 = next_fire_after(cron, now)
    n2 = next_fire_after(cron, n1 + timedelta(minutes=1))
    return n2 - n1


async def check_deadman(now: datetime | None = None) -> list[str]:
    """One issue string per enabled schedule that hasn't succeeded within its window
    (the cron period + 10% slack — ~26h for a daily, ~8d for a weekly)."""
    now = now or now_ist()
    issues: list[str] = []
    async with AsyncSessionLocal() as db:
        scheds = (
            await db.execute(select(JobSchedule).where(JobSchedule.enabled == True))  # noqa: E712
        ).scalars().all()

        for s in scheds:
            if s.job_type in _SELF_MONITORING_TYPES:
                continue

            # One-shots have no cron period. They are not overdue until their single
            # fire time passes; a fired one-shot disables itself, so any one-shot still
            # enabled past its next_run_at genuinely failed to fire. (A recurring row
            # gets its expected cadence from the cron.)
            if not (s.repeat and s.cron):
                if s.next_run_at is None or now <= s.next_run_at:
                    continue
                window = timedelta(seconds=settings.SCHEDULER_MISFIRE_GRACE_SECONDS)
            else:
                window = _cron_period(s.cron, now) * 1.1

            q = select(func.max(Job.completed_at)).where(
                Job.job_type == s.job_type, Job.status == JobStatus.success
            )
            q = q.where(Job.tenant_id.is_(None) if s.tenant_id is None
                        else Job.tenant_id == s.tenant_id)
            last = (await db.execute(q)).scalar()

            # A schedule cannot be overdue before it existed. Measure from its last
            # success, or from creation if it has never succeeded — otherwise a
            # brand-new weekly schedule is flagged instantly, days before its first
            # run is even due. (Observed on the VM, 2026-07-16.) For a one-shot,
            # measure from its fire time — that is when it should have completed.
            if s.repeat and s.cron:
                age = now - (last or s.created_at)
            else:
                age = now - s.next_run_at
            if age <= window:
                continue

            hrs = age.total_seconds() / 3600
            win_hrs = window.total_seconds() / 3600
            if last is None:
                issues.append(
                    f"'{s.name}' ({s.job_type}): never succeeded since it was created "
                    f"{hrs:.0f}h ago (expected every {win_hrs:.0f}h)"
                )
            else:
                issues.append(
                    f"'{s.name}' ({s.job_type}): last success {last:%Y-%m-%d %H:%M} "
                    f"({hrs:.0f}h ago) exceeds window {win_hrs:.0f}h"
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
