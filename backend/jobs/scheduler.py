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
import time
from collections import Counter
from datetime import datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import JobSchedule
from app.utils.logger import logger
from app.utils.time import IST, now_ist
from jobs.queue import DuplicateActiveJob, enqueue

log = logger.bind(tag="sched")          # every scheduler line carries the "sched" tag
_HEARTBEAT_SECONDS = 15 * 60            # a quiet "still alive" line when nothing fires


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


async def _fire(sched: JobSchedule, now: datetime) -> str | None:
    """Enqueue one run of a due schedule. Returns the job's lane on success, or None if
    skipped (previous run still active) or errored — `tick` aggregates these into one
    summary line instead of a line per schedule."""
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
            log.warning(f"'{sched.name}': previous run still active — skipped")
            return None
        except Exception as e:
            log.error(f"'{sched.name}': enqueue failed: {e}")
            return None
    log.debug(f"'{sched.name}' → job {str(job.id)[:8]} [{job.lane.value}]")
    return job.lane.value


async def tick(now: datetime | None = None, job_type_prefix: str | None = None) -> None:
    """One producer pass: fire every due, enabled schedule and advance its next run.

    `job_type_prefix` scopes the pass to schedules whose job_type starts with it (e.g.
    "cm." for a local campaign-manager-only test) — every other schedule is left
    completely untouched, next_run_at included, so a scoped producer never fires or
    perturbs another tenant's scrapes.
    """
    now = now or now_ist()
    grace = settings.SCHEDULER_MISFIRE_GRACE_SECONDS
    fired_lanes: Counter[str] = Counter()
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(JobSchedule).where(JobSchedule.enabled == True))  # noqa: E712
        ).scalars().all()

        for s in rows:
            if job_type_prefix and not s.job_type.startswith(job_type_prefix):
                continue                         # out of scope — don't seed, fire, or advance
            if s.next_run_at is None:            # first sight — seed it, don't fire yet
                if s.cron:                       # recurring: compute the first fire from the cron
                    s.next_run_at = next_fire_after(s.cron, now)
                else:                            # one-shot with no fire time is malformed — retire it
                    log.error(f"'{s.name}': one-shot has no next_run_at — disabling")
                    s.enabled = False
                continue
            if s.next_run_at > now:              # not due
                continue

            late = (now - s.next_run_at).total_seconds()
            if late > grace and not s.catchup:
                log.warning(f"'{s.name}': missed run due {s.next_run_at} skipped (catchup off)")
                retire = True                    # its slot has passed; a one-shot is now done
            else:
                lane = await _fire(s, now)
                if lane:
                    s.last_enqueued_at = now
                    fired_lanes[lane] += 1
                # If the enqueue was skipped as a duplicate, keep a one-shot armed so it
                # retries next tick rather than silently losing its single run.
                retire = bool(lane)

            if s.repeat and s.cron:
                # Advance past the current minute so we never re-fire the same slot.
                s.next_run_at = next_fire_after(s.cron, now + timedelta(minutes=1))
            elif retire:
                s.enabled = False                # one-shot: fire once, then disable
                log.debug(f"'{s.name}': one-shot fired → disabled")

        await db.commit()

    if fired_lanes:                              # one summary line per tick that did something
        total = sum(fired_lanes.values())
        breakdown = ", ".join(f"{lane}×{n}" for lane, n in sorted(fired_lanes.items()))
        log.info(f"fired {total} due → {breakdown}")


async def run_producer(
    shutdown: asyncio.Event, job_type_prefix: str | None = None, force: bool = False
) -> None:
    """Poll `job_schedules` on an interval until shutdown. Runs alongside the
    consumer inside the runner process.

    `job_type_prefix` scopes every tick to matching schedules (see `tick`). `force`
    runs the producer even when SCHEDULER_ENABLED is false — used by the scoped
    `--only-cm` local runner, where firing only cm.* schedules is safe by construction.
    """
    if not force and not settings.SCHEDULER_ENABLED:
        log.info("disabled (SCHEDULER_ENABLED=false) — consumer only")
        return
    scope = f" · scope={job_type_prefix}*" if job_type_prefix else ""
    log.info(f"producer started · tick={settings.SCHEDULER_TICK_SECONDS}s{scope}")
    last_hb = time.monotonic()
    while not shutdown.is_set():
        try:
            await tick(job_type_prefix=job_type_prefix)
        except Exception as e:
            log.error(f"tick failed: {e}")
        if time.monotonic() - last_hb >= _HEARTBEAT_SECONDS:
            last_hb = time.monotonic()
            await _heartbeat(job_type_prefix)
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=settings.SCHEDULER_TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
    log.info("producer stopped")


async def _heartbeat(job_type_prefix: str | None) -> None:
    """A quiet 'still alive' line on idle: how many schedules are armed and the next fire.
    Keeps the log from going silent for hours without drowning it in per-tick chatter."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(JobSchedule).where(JobSchedule.enabled == True))  # noqa: E712
        ).scalars().all()
    if job_type_prefix:
        rows = [r for r in rows if r.job_type.startswith(job_type_prefix)]
    nexts = [r.next_run_at for r in rows if r.next_run_at]
    nxt = min(nexts).strftime("%H:%M") if nexts else "—"
    log.info(f"heartbeat · {len(rows)} enabled, next fire {nxt}")
