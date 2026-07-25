"""Marketing / advertising data for a client (paid activity on the platform).

Metrics come from the per-campaign daily backbone (`BlinkitAdCampaignDaily`);
`BlinkitAdCampaign` supplies campaign metadata and `BlinkitAdCampaignDetail` the
keyword/asset breakdown. RoAS is always recomputed as ad_sales / spend over the
window (never an average of daily ratios). All queries are `tenant_id`-scoped and
optionally filtered to a set of marketplaces via the `platform` column (None =
every platform — today only Blinkit has ad data)."""
import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal

log = logging.getLogger(__name__)
_playwright_executor = ThreadPoolExecutor(max_workers=2)


def _run_in_new_loop(coro_factory):
    """Run a Playwright coroutine in a fresh ProactorEventLoop (Windows fix)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

_AD_CAMPAIGNS_DIR = Path(__file__).parent.parent.parent / "ad_campaigns"
_SCHEDULES_FILE = _AD_CAMPAIGNS_DIR / "schedules.json"
_LOG_FILE = _AD_CAMPAIGNS_DIR / "scheduler_log.json"
_BID_RULES_FILE = _AD_CAMPAIGNS_DIR / "bid_optimizer_rules.json"
_BID_LOG_FILE   = _AD_CAMPAIGNS_DIR / "bid_optimizer_log.json"

from app.dependencies import Pagination
from app.models.blinkit_marketing import (
    BlinkitAdCampaign,
    BlinkitAdCampaignDaily,
    BlinkitAdCampaignDetail,
    BlinkitBrandCollection,
    BlinkitSponsoredSOV,
    BlinkitVisibilityPlan,
)
from app.schemas.ads import CampaignRow, KeywordRow
from app.schemas.common import Page
from app.services import reference_service
# Shared window helpers — reused so ad aggregates stay identical to the Overview's.
from app.services.analytics_service import _ads_agg, _metric, _roas as _blended_roas

AdDaily = BlinkitAdCampaignDaily
Detail = BlinkitAdCampaignDetail

# Sort keys exposed by the campaign table -> the rollup field they order by.
_CAMPAIGN_SORTS = {
    "spend": "budget_consumed",
    "roas": "roas",
    "sales": "ad_sales",
    "impressions": "impressions",
}


def _roas(ad_sales: float, spend: float) -> float:
    """Display RoAS for table/chart rows — 0.0 (not None) when there's no spend."""
    return round(ad_sales / spend, 4) if spend else 0.0


def _acos(spend: float, ad_sales: float) -> float | None:
    """ACoS = spend / ad_sales (inverse of RoAS, lower is better). None when
    there's no ad-attributed revenue to divide by."""
    return round(float(spend) / float(ad_sales), 4) if ad_sales else None


def _ad_conds(tenant_id: uuid.UUID, start: date, end: date, marketplaces):
    conds = [
        AdDaily.tenant_id == tenant_id,
        AdDaily.date >= start,
        AdDaily.date <= end,
    ]
    if marketplaces is not None:
        conds.append(AdDaily.platform.in_(marketplaces))
    return conds


async def _summary_agg(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None,
) -> tuple:
    """(spend, impressions, ad_sales, atc, units, active_campaigns) for one window.
    Active campaigns = distinct campaigns with any daily row in the window."""
    return (
        await session.execute(
            select(
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
                func.coalesce(func.sum(AdDaily.atc), 0),
                func.coalesce(func.sum(AdDaily.quantities_sold), 0),
                func.count(distinct(AdDaily.campaign_id)),
            ).where(*_ad_conds(tenant_id, start, end, marketplaces))
        )
    ).one()


async def get_summary(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
    marketplaces: list[str] | None = None,
) -> dict:
    """KPI strip — each tile vs the equal-length previous window."""
    spend, impr, sales, atc, units, camps = await _summary_agg(
        session, tenant_id=tenant_id, start=start, end=end, marketplaces=marketplaces
    )
    p_spend, p_impr, p_sales, p_atc, p_units, p_camps = await _summary_agg(
        session,
        tenant_id=tenant_id,
        start=prev_start,
        end=prev_end,
        marketplaces=marketplaces,
    )
    return {
        "ad_spend": _metric(spend, p_spend),
        "ad_sales": _metric(sales, p_sales),
        "roas": _metric(_blended_roas(sales, spend), _blended_roas(p_sales, p_spend)),
        "acos": _metric(_acos(spend, sales), _acos(p_spend, p_sales)),
        "impressions": _metric(impr, p_impr),
        "atc": _metric(atc, p_atc),
        "units_sold": _metric(units, p_units),
        "active_campaigns": _metric(camps, p_camps),
    }


async def get_campaigns(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    status: str | None = None,
    sort: str = "spend",
    order: str = "desc",
    recent_only: bool = False,
) -> Page[CampaignRow]:
    # Per-campaign rollup of the daily backbone over the window.
    rollups = (
        await session.execute(
            select(
                AdDaily.campaign_id,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.atc), 0),
                func.coalesce(func.sum(AdDaily.quantities_sold), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(*_ad_conds(tenant_id, start, end, marketplaces))
            .group_by(AdDaily.campaign_id)
        )
    ).all()
    metrics = {
        cid: {
            "budget_consumed": round(float(b), 2),
            "impressions": int(i),
            "atc": int(a),
            "quantities_sold": int(q),
            "ad_sales": round(float(s), 2),
            "roas": _roas(float(s), float(b)),
        }
        for cid, b, i, a, q, s in rollups
    }

    # Campaign metadata (latest snapshot, one row per campaign).
    conds = [BlinkitAdCampaign.tenant_id == tenant_id]
    if marketplaces is not None:
        conds.append(BlinkitAdCampaign.platform.in_(marketplaces))
    if status:
        conds.append(BlinkitAdCampaign.status == status)
    if recent_only:
        latest_scraped_at = (
            await session.execute(
                select(func.max(BlinkitAdCampaign.scraped_at))
                .where(BlinkitAdCampaign.tenant_id == tenant_id)
            )
        ).scalar()
        if latest_scraped_at:
            conds.append(BlinkitAdCampaign.scraped_at >= latest_scraped_at - timedelta(hours=2))
    campaigns = (
        await session.execute(select(BlinkitAdCampaign).where(*conds))
    ).scalars().all()

    zeros = {
        "budget_consumed": 0.0,
        "impressions": 0,
        "atc": 0,
        "quantities_sold": 0,
        "ad_sales": 0.0,
        "roas": 0.0,
    }
    rows = [
        {
            "campaign_id": c.campaign_id,
            "name": c.name,
            "type": c.type,
            "status": c.status,
            "daily_budget": c.daily_budget,
            **metrics.get(c.campaign_id, zeros),
        }
        for c in campaigns
    ]

    # Campaign count per client is small -> rank + paginate in memory.
    sort_key = _CAMPAIGN_SORTS.get(sort, "budget_consumed")
    rows.sort(key=lambda r: r[sort_key], reverse=(order != "asc"))
    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    items = [CampaignRow.model_validate(r) for r in page]
    return Page.build(items, total, pagination)


async def get_performance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Daily account totals (summed across campaigns) with the day's RoAS."""
    rows = (
        await session.execute(
            select(
                AdDaily.date,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(*_ad_conds(tenant_id, start, end, marketplaces))
            .group_by(AdDaily.date)
            .order_by(AdDaily.date)
        )
    ).all()
    return [
        {
            "date": d,
            "budget_consumed": round(float(b), 2),
            "impressions": int(i),
            "ad_sales": round(float(s), 2),
            "roas": _roas(float(s), float(b)),
        }
        for d, b, i, s in rows
    ]


async def get_budget_split(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Spend + recomputed RoAS per campaign type (the denormalized `campaign_type`
    on the daily rows) — drives the budget-split donut and the by-type table."""
    rows = (
        await session.execute(
            select(
                AdDaily.campaign_type,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(*_ad_conds(tenant_id, start, end, marketplaces))
            .group_by(AdDaily.campaign_type)
        )
    ).all()
    out = [
        {
            "campaign_type": t,
            "budget_consumed": round(float(b), 2),
            "ad_sales": round(float(s), 2),
            "roas": _roas(float(s), float(b)),
        }
        for t, b, s in rows
    ]
    out.sort(key=lambda r: r["budget_consumed"], reverse=True)
    return out


async def get_keywords(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    campaign_id: int | None = None,
    marketplaces: list[str] | None = None,
    target_type: str | None = None,
    sort: str = "spend",
    order: str = "desc",
) -> Page[KeywordRow]:
    """Keyword / asset performance from the latest detail snapshot per campaign.

    `BlinkitAdCampaignDetail` is a range-aggregate snapshot (not daily), so we keep
    only each campaign's most recent `snapshot_date` rather than summing across
    snapshots."""
    conds = [Detail.tenant_id == tenant_id]
    if campaign_id is not None:
        conds.append(Detail.campaign_id == campaign_id)
    if marketplaces is not None:
        conds.append(Detail.platform.in_(marketplaces))
    if target_type:
        conds.append(Detail.target_type == target_type)
    rows = (
        await session.execute(select(Detail).where(*conds))
    ).scalars().all()

    # Keep only the latest snapshot per campaign.
    latest: dict[int, date] = {}
    for r in rows:
        if r.campaign_id not in latest or r.snapshot_date > latest[r.campaign_id]:
            latest[r.campaign_id] = r.snapshot_date
    rows = [r for r in rows if r.snapshot_date == latest[r.campaign_id]]

    sort_funcs = {
        "spend": lambda r: r.budget_consumed,
        "roas": lambda r: r.total_roas,
        "sales": lambda r: r.direct_sales + r.indirect_sales,
        "impressions": lambda r: r.impressions,
    }
    rows.sort(key=sort_funcs.get(sort, sort_funcs["spend"]), reverse=(order != "asc"))

    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    items = [KeywordRow.model_validate(r) for r in page]
    return Page.build(items, total, pagination)


async def get_sponsored_sov(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[BlinkitSponsoredSOV]:
    conds = [
        BlinkitSponsoredSOV.tenant_id == tenant_id,
        BlinkitSponsoredSOV.date >= start,
        BlinkitSponsoredSOV.date <= end,
    ]
    if marketplaces is not None:
        conds.append(BlinkitSponsoredSOV.platform.in_(marketplaces))
    rows = (
        await session.execute(
            select(BlinkitSponsoredSOV)
            .where(*conds)
            .order_by(BlinkitSponsoredSOV.keyword, BlinkitSponsoredSOV.date.desc())
            .distinct(BlinkitSponsoredSOV.keyword)
        )
    ).scalars().all()
    rows.sort(key=lambda r: r.sov, reverse=True)
    return rows


async def get_visibility_plans(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[BlinkitVisibilityPlan]:
    return (
        await session.execute(
            select(BlinkitVisibilityPlan)
            .where(BlinkitVisibilityPlan.tenant_id == tenant_id)
            .order_by(BlinkitVisibilityPlan.budget.desc())
        )
    ).scalars().all()


async def get_collections(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[BlinkitBrandCollection]:
    return (
        await session.execute(
            select(BlinkitBrandCollection)
            .where(BlinkitBrandCollection.tenant_id == tenant_id)
            .order_by(BlinkitBrandCollection.number_of_products.desc())
        )
    ).scalars().all()


# ── Budget scheduling (DB-backed) ─────────────────────────────────────────────

async def get_budget_schedules(session: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    from app.models.campaign_manager import BudgetScheduleDB, BudgetScheduleRuleDB
    rows = (await session.execute(
        select(BudgetScheduleDB).where(BudgetScheduleDB.tenant_id == tenant_id)
    )).scalars().all()
    result = []
    for s in rows:
        rules = (await session.execute(
            select(BudgetScheduleRuleDB).where(BudgetScheduleRuleDB.schedule_id == s.id)
        )).scalars().all()
        result.append({
            "campaign_id": s.campaign_id,
            "campaign_name": s.campaign_name,
            "name": s.name,
            "default_budget": s.default_budget,
            "enabled": s.enabled,
            "rules": [
                {
                    "type": r.type, "days": r.days or [], "time_slots": r.time_slots or [],
                    "budget": r.budget, "date": r.date,
                    "start_date": r.start_date, "end_date": r.end_date,
                    "start_time": r.start_time, "end_time": r.end_time,
                }
                for r in rules
            ],
        })
    return result


async def add_budget_schedule(session: AsyncSession, tenant_id: uuid.UUID, schedule: dict) -> dict:
    from app.models.campaign_manager import BudgetScheduleDB, BudgetScheduleRuleDB
    # Upsert: remove existing schedule + rules for this campaign
    existing = (await session.execute(
        select(BudgetScheduleDB).where(
            BudgetScheduleDB.tenant_id == tenant_id,
            BudgetScheduleDB.campaign_id == schedule["campaign_id"],
        )
    )).scalar_one_or_none()
    if existing:
        await session.execute(
            select(BudgetScheduleRuleDB).where(BudgetScheduleRuleDB.schedule_id == existing.id)
        )
        rules_to_del = (await session.execute(
            select(BudgetScheduleRuleDB).where(BudgetScheduleRuleDB.schedule_id == existing.id)
        )).scalars().all()
        for r in rules_to_del:
            await session.delete(r)
        await session.delete(existing)
        await session.flush()

    db_sched = BudgetScheduleDB(
        tenant_id=tenant_id,
        campaign_id=schedule["campaign_id"],
        campaign_name=schedule["campaign_name"],
        name=schedule.get("name"),
        default_budget=schedule["default_budget"],
        enabled=schedule.get("enabled", True),
    )
    session.add(db_sched)
    await session.flush()

    for rule in schedule.get("rules", []):
        session.add(BudgetScheduleRuleDB(
            schedule_id=db_sched.id,
            type=rule.get("type", "recurring"),
            days=rule.get("days", []),
            time_slots=rule.get("time_slots", []),
            budget=rule["budget"],
            date=rule.get("date"),
            start_date=rule.get("start_date"),
            end_date=rule.get("end_date"),
            start_time=rule.get("start_time"),
            end_time=rule.get("end_time"),
        ))

    await session.commit()
    schedule["enabled"] = db_sched.enabled
    return schedule


async def toggle_budget_schedule(session: AsyncSession, tenant_id: uuid.UUID, campaign_id: int) -> dict | None:
    from app.models.campaign_manager import BudgetScheduleDB
    s = (await session.execute(
        select(BudgetScheduleDB).where(
            BudgetScheduleDB.tenant_id == tenant_id,
            BudgetScheduleDB.campaign_id == campaign_id,
        )
    )).scalar_one_or_none()
    if not s:
        return None
    s.enabled = not s.enabled
    await session.commit()
    schedules = await get_budget_schedules(session, tenant_id)
    return next((x for x in schedules if x["campaign_id"] == campaign_id), None)


async def remove_budget_schedule(session: AsyncSession, tenant_id: uuid.UUID, campaign_id: int) -> bool:
    from app.models.campaign_manager import BudgetScheduleDB
    s = (await session.execute(
        select(BudgetScheduleDB).where(
            BudgetScheduleDB.tenant_id == tenant_id,
            BudgetScheduleDB.campaign_id == campaign_id,
        )
    )).scalar_one_or_none()
    if not s:
        return False
    await session.delete(s)
    await session.commit()
    return True


async def get_scheduler_log(session: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    from app.models.campaign_manager import BudgetSchedulerLogDB, BudgetScheduleDB
    rows = (await session.execute(
        select(BudgetSchedulerLogDB)
        .where(BudgetSchedulerLogDB.tenant_id == tenant_id)
        .order_by(BudgetSchedulerLogDB.timestamp.desc())
        .limit(50)
    )).scalars().all()

    # Build campaign_id -> schedule_name map
    schedules = (await session.execute(
        select(BudgetScheduleDB).where(BudgetScheduleDB.tenant_id == tenant_id)
    )).scalars().all()
    name_map = {s.campaign_id: s.name for s in schedules}

    return [
        {
            "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M IST"),
            "campaign_id": r.campaign_id,
            "campaign_name": r.campaign_name,
            "schedule_name": name_map.get(r.campaign_id),
            "budget_applied": r.budget_applied,
            "rule": r.rule,
            "success": r.success,
        }
        for r in rows
    ]


async def _write_scheduler_log(tenant_id: uuid.UUID, entries: list[dict]) -> None:
    if not entries:
        return
    from app.models.campaign_manager import BudgetSchedulerLogDB
    async with AsyncSessionLocal() as db:
        for e in entries:
            db.add(BudgetSchedulerLogDB(
                tenant_id=tenant_id,
                campaign_id=e.get("campaign_id"),
                campaign_name=e["campaign_name"],
                budget_applied=e["budget_applied"],
                rule=e["rule"],
                success=e["success"],
            ))
        await db.commit()


async def run_scheduler_inprocess(tenant_id: uuid.UUID) -> None:
    """Run the budget scheduler in-process (avoids Python 3.14 asyncpg SSL bug on Windows)."""
    from scraper.utils.session import load_session

    async with AsyncSessionLocal() as db:
        storage_state = await load_session(db, str(tenant_id), "blinkit")
        schedules = await get_budget_schedules(db, tenant_id)

    if not storage_state:
        return

    log_entries: list[dict] = []

    def _run():
        from ad_campaigns.scheduler import run_with_state

        async def _inner():
            return await run_with_state(storage_state, schedules=schedules)

        return _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    log_entries = await loop.run_in_executor(_playwright_executor, _run) or []
    await _write_scheduler_log(tenant_id, log_entries)


async def run_scheduler_all_tenants() -> None:
    from app.models.job import PlatformSession
    from sqlmodel import select as sql_select
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sql_select(PlatformSession).where(PlatformSession.platform == "blinkit")
        )
        sessions = result.scalars().all()

    for ps in sessions:
        try:
            await run_scheduler_inprocess(ps.tenant_id)
        except Exception as e:
            log.error("[budget_scheduler] auto-run failed tenant=%s: %s", ps.tenant_id, e)


# ── Bid Optimizer ────────────────────────────────────────────────────────────

async def get_bid_optimizer_rules(session: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    from app.models.campaign_manager import BidOptimizerRuleDB
    rows = (await session.execute(
        select(BidOptimizerRuleDB).where(BidOptimizerRuleDB.tenant_id == tenant_id)
    )).scalars().all()
    return [r.model_dump(mode="json") for r in rows]


async def add_bid_optimizer_rule(session: AsyncSession, tenant_id: uuid.UUID, rule: dict) -> dict:
    from app.models.campaign_manager import BidOptimizerRuleDB
    if not rule.get("id"):
        rule["id"] = str(uuid.uuid4())
    # Remove existing rule for same campaign + keyword
    existing = (await session.execute(
        select(BidOptimizerRuleDB).where(
            BidOptimizerRuleDB.tenant_id == tenant_id,
            BidOptimizerRuleDB.campaign_id == rule["campaign_id"],
            BidOptimizerRuleDB.keyword == rule["keyword"],
        )
    )).scalar_one_or_none()
    if existing:
        await session.delete(existing)
        await session.flush()
    db_rule = BidOptimizerRuleDB(tenant_id=tenant_id, **{
        k: v for k, v in rule.items()
        if k in BidOptimizerRuleDB.model_fields and k != "tenant_id"
    })
    session.add(db_rule)
    await session.commit()
    # Sync JSON cache for bid_optimizer.py runtime use
    await _sync_bid_rules_to_json(session, tenant_id)
    return rule


async def remove_bid_optimizer_rule(session: AsyncSession, tenant_id: uuid.UUID, rule_id: str) -> bool:
    from app.models.campaign_manager import BidOptimizerRuleDB
    r = (await session.execute(
        select(BidOptimizerRuleDB).where(
            BidOptimizerRuleDB.tenant_id == tenant_id,
            BidOptimizerRuleDB.id == rule_id,
        )
    )).scalar_one_or_none()
    if not r:
        return False
    await session.delete(r)
    await session.commit()
    await _sync_bid_rules_to_json(session, tenant_id)
    return True


async def toggle_bid_optimizer_rule(session: AsyncSession, tenant_id: uuid.UUID, rule_id: str) -> dict | None:
    from app.models.campaign_manager import BidOptimizerRuleDB
    r = (await session.execute(
        select(BidOptimizerRuleDB).where(
            BidOptimizerRuleDB.tenant_id == tenant_id,
            BidOptimizerRuleDB.id == rule_id,
        )
    )).scalar_one_or_none()
    if not r:
        return None
    r.active = not r.active
    await session.commit()
    await _sync_bid_rules_to_json(session, tenant_id)
    return r.model_dump(mode="json")


async def get_bid_optimizer_log(session: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    from app.models.campaign_manager import BidOptimizerLogDB
    rows = (await session.execute(
        select(BidOptimizerLogDB)
        .where(BidOptimizerLogDB.tenant_id == tenant_id)
        .order_by(BidOptimizerLogDB.timestamp.desc())
        .limit(100)
    )).scalars().all()
    return [
        {
            "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M:%S IST"),
            "campaign_id": r.campaign_id,
            "campaign_name": r.campaign_name,
            "keyword": r.keyword,
            "action": r.action,
            "old_cpm": r.old_cpm,
            "new_cpm": r.new_cpm,
            "position": r.position,
            "target_position": r.target_position,
            "impressions": r.impressions,
            "detail": r.detail,
            "success": r.success,
        }
        for r in rows
    ]


async def _sync_bid_rules_to_json(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Keep JSON cache in sync for bid_optimizer.py runtime use."""
    rules = await get_bid_optimizer_rules(session, tenant_id)
    _BID_RULES_FILE.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")


async def _write_bid_optimizer_log(tenant_id: uuid.UUID, entries: list[dict]) -> None:
    if not entries:
        return
    from app.models.campaign_manager import BidOptimizerLogDB
    async with AsyncSessionLocal() as db:
        for e in entries:
            db.add(BidOptimizerLogDB(
                tenant_id=tenant_id,
                campaign_id=e.get("campaign_id"),
                campaign_name=e.get("campaign_name", ""),
                keyword=e.get("keyword"),
                action=e.get("action", ""),
                old_cpm=e.get("old_cpm"),
                new_cpm=e.get("new_cpm"),
                position=e.get("position"),
                target_position=e.get("target_position"),
                impressions=e.get("impressions"),
                detail=e.get("detail"),
                success=e.get("success", False),
            ))
        await db.commit()


async def run_bid_optimizer_inprocess(tenant_id: uuid.UUID) -> None:
    from scraper.utils.session import load_session
    async with AsyncSessionLocal() as db:
        storage_state = await load_session(db, str(tenant_id), "blinkit")
        # Sync rules from DB to JSON so bid_optimizer.py can read them
        await _sync_bid_rules_to_json(db, tenant_id)

    if not storage_state:
        return

    log_entries: list[dict] = []

    def _run():
        from ad_campaigns.bid_optimizer import run_with_state
        async def _inner():
            return await run_with_state(storage_state)
        return _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    log_entries = await loop.run_in_executor(_playwright_executor, _run) or []
    await _write_bid_optimizer_log(tenant_id, log_entries)

    # Persist runtime fields back to DB so they survive the next _sync_bid_rules_to_json call
    import json as _json
    from app.models.campaign_manager import BidOptimizerRuleDB
    if _BID_RULES_FILE.exists():
        updated_rules = _json.loads(_BID_RULES_FILE.read_text(encoding="utf-8"))
        async with AsyncSessionLocal() as db:
            for r in updated_rules:
                rule_id = r.get("id")
                if not rule_id:
                    continue
                values: dict = {}
                if r.get("last_position") is not None:
                    values["last_position"] = r["last_position"]
                if r.get("last_bid_updated_at") is not None:
                    values["last_bid_updated_at"] = r["last_bid_updated_at"]
                if r.get("last_cpm") is not None:
                    values["last_cpm"] = r["last_cpm"]
                if values:
                    await db.execute(
                        update(BidOptimizerRuleDB)
                        .where(BidOptimizerRuleDB.id == rule_id)
                        .values(**values)
                    )
            await db.commit()


async def run_bid_optimizer_all_tenants() -> None:
    from app.models.job import PlatformSession
    from sqlmodel import select as sql_select
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sql_select(PlatformSession).where(PlatformSession.platform == "blinkit")
        )
        sessions = result.scalars().all()

    for ps in sessions:
        try:
            await run_bid_optimizer_inprocess(ps.tenant_id)
        except Exception as e:
            log.error("[bid_optimizer] auto-run failed tenant=%s: %s", ps.tenant_id, e)


# ── Campaign keywords ─────────────────────────────────────────────────────────

async def get_campaign_keywords(tenant_id: uuid.UUID, campaign_id: int) -> list[dict]:
    """Return cached campaign keywords from DB (populated by ads.sync_campaign_data VM job)."""
    from app.models.campaign_manager import CampaignDataCache
    from sqlmodel import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CampaignDataCache).where(
                CampaignDataCache.tenant_id == tenant_id,
                CampaignDataCache.campaign_id == campaign_id,
            )
        )
        cache = result.scalars().first()

    return cache.keywords if cache else []


# ── Campaign products ─────────────────────────────────────────────────────────

async def get_campaign_products(tenant_id: uuid.UUID, campaign_id: int) -> list[dict]:
    """Return cached campaign products from DB (populated by ads.sync_campaign_data VM job)."""
    from app.models.campaign_manager import CampaignDataCache
    from sqlmodel import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CampaignDataCache).where(
                CampaignDataCache.tenant_id == tenant_id,
                CampaignDataCache.campaign_id == campaign_id,
            )
        )
        cache = result.scalars().first()

    products = cache.products if cache else []

    # Enrich stub names using sku_map (platform_product_id = campaign PID)
    pids = [p["pid"] for p in products if p.get("pid")]
    if pids:
        from app.models.search import SkuMap
        from sqlalchemy import select as _select
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                _select(SkuMap.platform_product_id, SkuMap.product_name)
                .where(SkuMap.tenant_id == tenant_id)
                .where(SkuMap.platform_product_id.in_(pids))
            )).all()
        pid_to_name = {r.platform_product_id: r.product_name for r in rows if r.product_name}
        for p in products:
            sku_name = pid_to_name.get(p.get("pid", ""))
            if sku_name and (not p["name"] or p["name"].startswith("Product (ID:")):
                p["name"] = sku_name

    return products


# ── Live position (consumer scraper) ─────────────────────────────────────────

async def get_live_positions(keyword: str, lat: float = 12.9767, lon: float = 77.5713) -> list[dict]:
    """Scrape blinkit.com consumer search for real-time product positions."""
    from ad_campaigns.live_position import get_live_positions as _scrape

    result: dict = {}

    def _run():
        async def _inner():
            result["positions"] = await _scrape(keyword, lat=lat, lon=lon)

        _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_playwright_executor, _run)
    return result.get("positions", [])


# ── Live budget fetch ─────────────────────────────────────────────────────────

async def get_live_campaign_budget(tenant_id: uuid.UUID, campaign_id: int) -> int | None:
    """Fetch campaign_budget live from Blinkit API and cache it in daily_budget column."""
    from scraper.utils.session import load_session

    async with AsyncSessionLocal() as db:
        storage_state = await load_session(db, str(tenant_id), "blinkit")
    if not storage_state:
        raise RuntimeError("No Blinkit session found. Please reconnect via the Blinkit Connection card.")

    result: dict = {}

    def _run():
        from ad_campaigns.client import setup_with_state

        async def _inner():
            pw, browser, client = await setup_with_state(storage_state)
            try:
                detail, _ = await client.get_campaign_detail(campaign_id)
                result["budget"] = detail.get("campaign_budget")
            finally:
                await browser.close()
                await pw.stop()

        _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_playwright_executor, _run)

    budget = result.get("budget")
    if budget is not None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(BlinkitAdCampaign)
                .where(
                    BlinkitAdCampaign.campaign_id == campaign_id,
                    BlinkitAdCampaign.tenant_id == str(tenant_id),
                )
                .values(daily_budget=int(budget))
            )
            await db.commit()

    return int(budget) if budget is not None else None


# ── Direct budget update ──────────────────────────────────────────────────────

async def set_campaign_budget(tenant_id: uuid.UUID, campaign_id: int, budget: float) -> None:
    """Open browser, fetch campaign detail, set daily budget immediately."""
    from scraper.utils.session import load_session

    # Load session in the main event loop (DB stays on the main loop).
    async with AsyncSessionLocal() as db:
        storage_state = await load_session(db, str(tenant_id), "blinkit")
    if not storage_state:
        raise RuntimeError("No Blinkit session found. Please reconnect via the Blinkit Connection card.")

    # Run Playwright in a separate thread with its own event loop (Windows fix).
    def _run():
        from ad_campaigns.client import setup_with_state

        async def _inner():
            pw, browser, client = await setup_with_state(storage_state)
            try:
                detail, _ = await client.get_campaign_detail(campaign_id)
                if not detail:
                    raise RuntimeError(f"Campaign {campaign_id} not found.")
                pacing = detail.get("pacing_type", "DAILY")
                changes = {"bidding_strategy": {"total_budget": float(budget), "pacing_type": pacing}}

                # Attempt 1: full payload with actual PIDs
                resp = await client.update_campaign(campaign_id, changes)
                if resp.get("status") or resp.get("success"):
                    return

                # Attempt 2: empty pids — handles delisted/invalid catalog products
                api_msg = resp.get("message", str(resp))
                log.warning("[set_campaign_budget] attempt 1 failed (%s) — retrying with empty pids", api_msg)
                resp = await client.update_campaign(campaign_id, changes, empty_pids=True)
                if not (resp.get("status") or resp.get("success")):
                    raise RuntimeError(f"Blinkit rejected: {resp.get('message', resp)}")
            finally:
                await browser.close()
                await pw.stop()

        _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_playwright_executor, _run)


# ── Blinkit reconnect ─────────────────────────────────────────────────────────

async def reconnect_blinkit(db_session: AsyncSession, tenant_id: uuid.UUID, magic_link: str, email: str = "") -> None:
    """Navigate to magic link in headless browser, capture session, save to DB."""
    result: dict = {}

    def _run():
        from playwright.async_api import async_playwright
        from scraper.platforms.blinkit.auth import _capture_session
        from scraper.platforms.blinkit.dashboard_data.marketing.endpoints import BASE_URL
        from scraper.utils.browser import create_browser_context

        async def _inner():
            async with async_playwright() as pw:
                browser, context = await create_browser_context(pw, headless=True)
                page = await context.new_page()
                try:
                    # Set email in localStorage so Firebase signInWithEmailLink can complete
                    if email:
                        await page.goto("https://brands.blinkit.com", wait_until="domcontentloaded", timeout=15_000)
                        await page.evaluate(f"localStorage.setItem('emailForSignIn', '{email}')")
                    await page.goto(magic_link.strip(), wait_until="networkidle", timeout=45_000)
                    # Firebase auth action page redirects to /dashboard via JS — wait for it
                    if "/diy/" not in page.url and "/dashboard" not in page.url:
                        try:
                            await page.wait_for_url("**/dashboard**", timeout=20_000)
                        except Exception:
                            pass
                    if "/diy/" not in page.url and "/dashboard" not in page.url:
                        raise RuntimeError(
                            f"Magic link did not land on Blinkit dashboard (landed on {page.url}). "
                            "Link may be expired or already used."
                        )
                    result["storage_state"] = await _capture_session(page, context, BASE_URL)
                finally:
                    await browser.close()

        _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_playwright_executor, _run)

    from scraper.utils.session import save_session
    await save_session(db_session, str(tenant_id), "blinkit", result["storage_state"])


async def _mp_ad_metrics(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    slug: str,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> dict:
    """Ad metric set for a single marketplace, current vs previous window."""
    mp = [slug]
    spend, impr, sales = await _ads_agg(
        session, tenant_id=tenant_id, start=start, end=end, marketplaces=mp
    )
    p_spend, p_impr, p_sales = await _ads_agg(
        session, tenant_id=tenant_id, start=prev_start, end=prev_end, marketplaces=mp
    )
    return {
        "ad_spend": _metric(spend, p_spend),
        "ad_sales": _metric(sales, p_sales),
        "roas": _metric(_blended_roas(sales, spend), _blended_roas(p_sales, p_spend)),
        "impressions": _metric(impr, p_impr),
    }


async def get_marketplace_breakdown(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> list[dict]:
    """One row per marketplace with its ad slice. Connected marketplaces carry
    metrics; unconnected ones are bare (connected=False) so the UI shows a 'Not
    connected' card instead of faking data. Lets 'All' be visibly split per MP
    rather than only a combined total."""
    marketplaces = await reference_service.list_marketplaces(session)
    rows: list[dict] = []
    for mp in marketplaces:
        row = {
            "slug": mp["slug"],
            "name": mp["name"],
            "color": mp["color"],
            "connected": mp["connected"],
        }
        if mp["connected"]:
            row.update(
                await _mp_ad_metrics(
                    session,
                    tenant_id=tenant_id,
                    slug=mp["slug"],
                    start=start,
                    end=end,
                    prev_start=prev_start,
                    prev_end=prev_end,
                )
            )
        rows.append(row)
    return rows
