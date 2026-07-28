"""Tenant-scoped DB access for the campaign manager — cm_* tables, NO JSON files.

Reads rules, writes the slim run-log, and (V2+) persists bid runtime. Everything is
scoped by tenant_id (+ platform). Kept thin: the orchestration decides *what*, this
only reads/writes rows.
"""
import uuid
from datetime import timedelta

from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.utils.time import now_ist


async def get_budget_schedules(tenant_id: uuid.UUID, platform: str = "blinkit"):
    """Return [(schedule, [rules])] for a tenant. Empty until rules are created."""
    from app.models.campaign_manager_v2 import CmBudgetSchedule, CmBudgetRule

    async with AsyncSessionLocal() as db:
        schedules = (await db.execute(
            select(CmBudgetSchedule).where(
                CmBudgetSchedule.tenant_id == tenant_id,
                CmBudgetSchedule.platform == platform,
            )
        )).scalars().all()
        out = []
        for s in schedules:
            rules = (await db.execute(
                select(CmBudgetRule).where(CmBudgetRule.schedule_id == s.id)
            )).scalars().all()
            out.append((s, list(rules)))
        return out


async def get_bid_rules(tenant_id: uuid.UUID, platform: str = "blinkit"):
    """Return [(rule, runtime_or_None)] for a tenant. Empty until rules are created."""
    from app.models.campaign_manager_v2 import CmBidRule, CmBidRuntime

    async with AsyncSessionLocal() as db:
        rules = (await db.execute(
            select(CmBidRule).where(
                CmBidRule.tenant_id == tenant_id,
                CmBidRule.platform == platform,
            )
        )).scalars().all()
        out = []
        for r in rules:
            runtime = (await db.execute(
                select(CmBidRuntime).where(CmBidRuntime.rule_id == r.id)
            )).scalars().first()
            out.append((r, runtime))
        return out


async def recent_write_count(tenant_id: uuid.UUID, campaign_id: int, *,
                             window_minutes: int, kind: str) -> int:
    """How many successful writes this campaign got within the window (rate limit)."""
    from sqlalchemy import func
    from app.models.campaign_manager_v2 import CmRunLog

    cutoff = now_ist() - timedelta(minutes=window_minutes)
    async with AsyncSessionLocal() as db:
        n = (await db.execute(
            select(func.count()).select_from(CmRunLog).where(
                CmRunLog.tenant_id == tenant_id,
                CmRunLog.campaign_id == campaign_id,
                CmRunLog.kind == kind,
                CmRunLog.action == "apply",
                CmRunLog.dry_run == False,  # noqa: E712 — only real writes count
                CmRunLog.timestamp >= cutoff,
            )
        )).scalar()
        return int(n or 0)


async def write_run_log(rows: list[dict]) -> None:
    """Append slim history rows for the UI. No-op on empty."""
    if not rows:
        return
    from app.models.campaign_manager_v2 import CmRunLog

    async with AsyncSessionLocal() as db:
        for r in rows:
            db.add(CmRunLog(**r))
        await db.commit()
