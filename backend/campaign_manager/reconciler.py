"""Reconciler — compile a tenant's rules into `job_schedules` rows (MP-agnostic).

Runner-owned: the API enqueues a `cm.reconcile` job on any rule change; this reads
the current rules and makes `job_schedules` match them, idempotently (deterministic
names → create missing / update changed / delete no-longer-wanted). It NEVER touches
Blinkit — it only writes rows into our own `job_schedules` table. Schedules are
written at edit time and stay dormant until they fire:

  - **Budget boundaries** → one recurring cron `cm.budget_scheduler` per distinct
    transition time (a rule's start_time / end_time) across all of a tenant's enabled
    schedules. The job is dumb — at each fire it re-evaluates every schedule and
    applies the budget that matches *now* (or `default_budget` when nothing matches),
    so an end_time boundary naturally reverts to default.
  - **Safety poll** → one recurring hourly `cm.budget_scheduler`, catching drift and
    fires missed while the runner was down.
  - **`once` budget rules** → two one-shot `cm.budget_scheduler` rows: one at the
    rule's start (applies it) and one at its end (reverts to default).
  - **Expiry** (a recurring rule's end_date) → a one-shot `cm.budget_scheduler` the
    morning after the last active day, so the campaign is reset to default promptly.
  - **Bid windows** → one recurring `*/15`-within-window `cm.bid_optimizer` per merged
    active window across the tenant's active bid rules.

The scheduled jobs run **dry-run** in V3 (empty params → no `--live`); arming them to
write Blinkit for real is a deliberate cutover step (V5/V6), NOT something reconcile
does. `dry_run` on reconcile itself means "compute + log the diff but don't write
`job_schedules`" (a preview) — distinct from the budget/bid jobs' Blinkit dry-run.

The planning functions (`budget_boundaries` / `bid_windows` / `desired_schedules` …)
are pure and unit-testable without the DB (tests land in V3.5).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.job import JobSchedule
from app.utils.time import now_ist
from campaign_manager import config, logs, repo
from jobs.scheduler import initial_next_run

# Deterministic name prefix for reconciler-owned rows. Format:
#   auto:cm:<kind>:<tenant>:<platform>:<rest>
# Only rows matching this prefix AND the current platform are ever touched — manual
# `schedules add` rows and other marketplaces are never deleted.
_PREFIX = "auto:cm:"

BUDGET_JOB = "cm.budget_scheduler"
BID_JOB = "cm.bid_optimizer"

_SAFETY_POLL_CRON = "0 * * * *"      # hourly drift/missed-fire catch (§7.3)
_BID_STEP_MIN = 15                   # bid optimizer cadence within an active window


# ── Pure planning (unit-tested, no DB) ───────────────────────────────────────

@dataclass
class Desired:
    """One schedule the rules imply. `cron`+`repeat=True` = recurring; `next_run_at`
    + `repeat=False` = one-shot (cron None)."""
    name: str
    job_type: str
    cron: str | None
    repeat: bool
    next_run_at: datetime | None
    params: dict = field(default_factory=dict)
    priority: int = 100
    catchup: bool = False


def _parse_hhmm(s: str | None) -> tuple[int, int] | None:
    """'HH:MM' → (hour, minute); None if unparseable/empty."""
    if not s:
        return None
    try:
        parts = s.split(":")
        h, m = int(parts[0]), int(parts[1])
    except (ValueError, IndexError, AttributeError):
        return None
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h, m
    return None


def _parse_date(s: str | None) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def budget_boundaries(schedules) -> set[tuple[int, int]]:
    """Distinct (hour, minute) transition times across the recurring rules of all
    ENABLED schedules — the moments a budget can change, one browser handling all
    campaigns changing then."""
    out: set[tuple[int, int]] = set()
    for sched, rules in schedules:
        if not sched.enabled:
            continue
        for r in rules:
            if r.type == "once":
                continue
            for t in (r.start_time, r.end_time):
                hm = _parse_hhmm(t)
                if hm:
                    out.add(hm)
    return out


def _once_fires(schedules, tenant: str, platform: str, now: datetime) -> list[Desired]:
    """One-shot apply+revert fires for each `once` budget rule (future only)."""
    out: list[Desired] = []
    for sched, rules in schedules:
        if not sched.enabled:
            continue
        for r in rules:
            if r.type != "once":
                continue
            base = _parse_date(r.date)
            if base is None:
                continue
            sh = _parse_hhmm(r.start_time) or (0, 0)
            on_at = base.replace(hour=sh[0], minute=sh[1])
            eh = _parse_hhmm(r.end_time)
            if eh is None:
                off_at = base + timedelta(days=1)               # all-day → revert next midnight
            elif eh <= sh:
                off_at = (base + timedelta(days=1)).replace(hour=eh[0], minute=eh[1])  # midnight-crossing
            else:
                off_at = base.replace(hour=eh[0], minute=eh[1])
            for tag, at in (("on", on_at), ("off", off_at)):
                if at > now:
                    out.append(Desired(
                        f"{_PREFIX}budget:{tenant}:{platform}:once:{r.id}:{tag}",
                        BUDGET_JOB, None, False, at))
    return out


def _expiry_fires(schedules, tenant: str, platform: str, now: datetime) -> list[Desired]:
    """One-shot reset-to-default the morning after each recurring rule's end_date."""
    out: list[Desired] = []
    for sched, rules in schedules:
        if not sched.enabled:
            continue
        for r in rules:
            if r.type == "once" or not r.end_date:
                continue
            base = _parse_date(r.end_date)
            if base is None:
                continue
            at = (base + timedelta(days=1)).replace(hour=0, minute=5)
            if at > now:
                out.append(Desired(
                    f"{_PREFIX}budget:{tenant}:{platform}:expire:{r.id}",
                    BUDGET_JOB, None, False, at))
    return out


def _rule_hours(start_time: str | None, stop_time: str | None) -> set[int]:
    """Active clock-hours (0–23) for a time window; wraps past midnight when stop ≤ start
    (e.g. 18:00–02:00 → {18..23, 0..1}). No window → all 24. Hour granularity (minute
    precision deferred — see backlog)."""
    sh = _parse_hhmm(start_time)
    eh = _parse_hhmm(stop_time)
    if not (sh or eh):
        return set(range(24))
    start_h = sh[0] if sh else 0
    if eh is None:
        return set(range(start_h, 24))
    end_h = max(0, min(eh[0] - 1 if eh[1] == 0 else eh[0], 23))   # last hour needing a run
    if sh and eh <= sh:                                          # crosses midnight
        return set(range(start_h, 24)) | set(range(0, end_h + 1))
    return set(range(start_h, end_h + 1)) if end_h >= start_h else set()


def bid_active_hours(bid_rules, now: datetime) -> set[int]:
    """Union of active clock-hours across active, non-expired bid rules. A `once` rule
    whose date has passed (or a recurring rule past its stop_date) drops out, so its
    hours stop keeping the optimizer cron alive."""
    today = now.strftime("%Y-%m-%d")
    hours: set[int] = set()
    for r in bid_rules:
        if not r.active:
            continue
        if getattr(r, "type", "recurring") == "once":
            if r.date and today > r.date:
                continue
        elif r.stop_date and today > r.stop_date:
            continue
        hours |= _rule_hours(r.start_time, r.stop_time)
    return hours


def _hours_to_cron_field(hours: set[int]) -> str:
    """Compress a set of hours into a cron hour field: {0,1,2,9,18..23} → '0-2,9,18-23'."""
    if len(hours) == 24:
        return "*"
    parts, s = [], sorted(hours)
    lo = prev = s[0]
    for h in s[1:]:
        if h == prev + 1:
            prev = h
            continue
        parts.append(f"{lo}-{prev}" if lo != prev else f"{lo}")
        lo = prev = h
    parts.append(f"{lo}-{prev}" if lo != prev else f"{lo}")
    return ",".join(parts)


def desired_schedules(tenant: str, platform: str, budget_schedules, bid_rules,
                      now: datetime) -> list[Desired]:
    """The full set of `job_schedules` the current rules imply."""
    d: list[Desired] = []

    for h, m in sorted(budget_boundaries(budget_schedules)):
        cron = f"{m} {h} * * *"
        d.append(Desired(f"{_PREFIX}budget:{tenant}:{platform}:{h:02d}{m:02d}",
                         BUDGET_JOB, cron, True, initial_next_run(cron)))

    if any(s.enabled for s, _ in budget_schedules):
        d.append(Desired(f"{_PREFIX}budget:{tenant}:{platform}:poll",
                         BUDGET_JOB, _SAFETY_POLL_CRON, True, initial_next_run(_SAFETY_POLL_CRON)))

    d += _once_fires(budget_schedules, tenant, platform, now)
    d += _expiry_fires(budget_schedules, tenant, platform, now)

    # One optimizer cron covering the union of all active bid windows (overnight-aware).
    # The job re-checks each rule's own window/date via `_in_window`, so a single cron is
    # enough — the lane is serial anyway.
    hours = bid_active_hours(bid_rules, now)
    if hours:
        cron = f"*/{_BID_STEP_MIN} {_hours_to_cron_field(hours)} * * *"
        d.append(Desired(f"{_PREFIX}bid:{tenant}:{platform}:opt",
                         BID_JOB, cron, True, initial_next_run(cron)))

    return d


# ── Idempotent apply (DB) ────────────────────────────────────────────────────

def _is_managed(name: str | None, platform: str) -> bool:
    """A reconciler-owned row for THIS platform (never a manual or other-MP row)."""
    if not name or not name.startswith(_PREFIX):
        return False
    parts = name.split(":")                                     # auto:cm:<kind>:<tenant>:<platform>:…
    return len(parts) >= 5 and parts[4] == platform


def _differs(cur: JobSchedule, d: Desired) -> bool:
    if (cur.job_type != d.job_type or cur.cron != d.cron or cur.repeat != d.repeat
            or cur.priority != d.priority or cur.catchup != d.catchup
            or (cur.params or {}) != d.params or not cur.enabled):
        return True
    # A one-shot's fire time is part of its identity; a recurring row's next_run_at
    # drifts as it fires, so we never diff on it (would churn every reconcile).
    return (not d.repeat) and cur.next_run_at != d.next_run_at


async def _apply(db, tenant_id: uuid.UUID, platform: str, desired: list[Desired],
                 dry_run: bool, run_id: str) -> tuple[int, int, int]:
    rows = (await db.execute(
        select(JobSchedule).where(JobSchedule.tenant_id == tenant_id)
    )).scalars().all()
    existing = {r.name: r for r in rows if _is_managed(r.name, platform)}
    wanted = {d.name: d for d in desired}
    created = updated = deleted = 0

    for name, d in wanted.items():
        detail = d.cron if d.repeat else f"once@{d.next_run_at:%Y-%m-%d %H:%M}"
        cur = existing.get(name)
        if cur is None:
            logs.reconcile_change(run_id, dry_run=dry_run, action="create", name=name, detail=detail)
            if not dry_run:
                db.add(JobSchedule(
                    name=d.name, job_type=d.job_type, tenant_id=tenant_id, params=d.params,
                    cron=d.cron, repeat=d.repeat, priority=d.priority, catchup=d.catchup,
                    enabled=True, next_run_at=d.next_run_at,
                ))
            created += 1
        elif _differs(cur, d):
            logs.reconcile_change(run_id, dry_run=dry_run, action="update", name=name, detail=detail)
            if not dry_run:
                cur.job_type, cur.params = d.job_type, d.params
                cur.repeat, cur.priority, cur.catchup, cur.enabled = d.repeat, d.priority, d.catchup, True
                if cur.cron != d.cron:                          # re-arm a recurring row on cron change
                    cur.cron, cur.next_run_at = d.cron, d.next_run_at
                if not d.repeat:                                # one-shot: fire time is authoritative
                    cur.next_run_at = d.next_run_at
            updated += 1

    for name, cur in existing.items():
        if name not in wanted:
            logs.reconcile_change(run_id, dry_run=dry_run, action="delete", name=name,
                                  detail="(no longer wanted)")
            if not dry_run:
                await db.delete(cur)
            deleted += 1

    if not dry_run:
        await db.commit()
    return created, updated, deleted


# ── Orchestration ────────────────────────────────────────────────────────────

async def reconcile(tenant_id: uuid.UUID, *, dry_run: bool | None = None,
                    platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    logs.run_start(run_id, "reconcile", tenant_id, dry_run=dry_run, platform=platform)

    budget_schedules = await repo.get_budget_schedules(tenant_id, platform)
    bid_rules = [r for r, _ in await repo.get_bid_rules(tenant_id, platform)]

    now = now_ist()
    desired = desired_schedules(str(tenant_id), platform, budget_schedules, bid_rules, now)

    async with AsyncSessionLocal() as db:
        created, updated, deleted = await _apply(db, tenant_id, platform, desired, dry_run, run_id)

    logs.run_summary(run_id, "reconcile", dry_run=dry_run,
                     processed=created + updated + deleted, applied=created + updated,
                     skipped=deleted, errors=0)
    return {"created": created, "updated": updated, "deleted": deleted}
