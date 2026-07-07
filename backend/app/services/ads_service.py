"""Marketing / advertising data for a client (paid activity on the platform).

Metrics come from the per-campaign daily backbone (`BlinkitAdCampaignDaily`);
`BlinkitAdCampaign` supplies campaign metadata. RoAS is always recomputed as
ad_sales / spend over the window (never an average of daily ratios)."""
import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, select
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
    BlinkitBrandCollection,
    BlinkitSponsoredSOV,
    BlinkitVisibilityPlan,
)
from app.schemas.ads import CampaignRow
from app.schemas.common import Page

AdDaily = BlinkitAdCampaignDaily


def _roas(ad_sales: float, spend: float) -> float:
    return round(ad_sales / spend, 4) if spend else 0.0


async def get_campaigns(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    days: int = 30,
    status: str | None = None,
) -> Page[CampaignRow]:
    since = date.today() - timedelta(days=days)

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
            .where(AdDaily.tenant_id == tenant_id, AdDaily.date >= since)
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
    if status:
        conds.append(BlinkitAdCampaign.status == status)
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
    rows.sort(key=lambda r: r["budget_consumed"], reverse=True)
    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    items = [CampaignRow.model_validate(r) for r in page]
    return Page.build(items, total, pagination)


async def get_performance(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> list[dict]:
    """Daily account totals (summed across campaigns) — replaces the old
    performance-summary table."""
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                AdDaily.date,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(AdDaily.tenant_id == tenant_id, AdDaily.date >= since)
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
        }
        for d, b, i, s in rows
    ]


async def get_sponsored_sov(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> list[BlinkitSponsoredSOV]:
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(BlinkitSponsoredSOV)
            .where(
                BlinkitSponsoredSOV.tenant_id == tenant_id,
                BlinkitSponsoredSOV.date >= since,
            )
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


# ── Budget scheduling (file-based, no DB) ────────────────────────────────────

def get_budget_schedules() -> list[dict]:
    if not _SCHEDULES_FILE.exists():
        return []
    return json.loads(_SCHEDULES_FILE.read_text(encoding="utf-8"))


def add_budget_schedule(schedule: dict) -> dict:
    schedules = get_budget_schedules()
    schedules = [s for s in schedules if s["campaign_id"] != schedule["campaign_id"]]
    schedules.append(schedule)
    _SCHEDULES_FILE.write_text(json.dumps(schedules, indent=2, ensure_ascii=False), encoding="utf-8")
    return schedule


def toggle_budget_schedule(campaign_id: int) -> dict | None:
    schedules = get_budget_schedules()
    for s in schedules:
        if s["campaign_id"] == campaign_id:
            s["enabled"] = not s.get("enabled", True)
            _SCHEDULES_FILE.write_text(json.dumps(schedules, indent=2, ensure_ascii=False), encoding="utf-8")
            return s
    return None


def remove_budget_schedule(campaign_id: int) -> bool:
    schedules = get_budget_schedules()
    filtered = [s for s in schedules if s["campaign_id"] != campaign_id]
    if len(filtered) == len(schedules):
        return False
    _SCHEDULES_FILE.write_text(json.dumps(filtered, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def get_scheduler_log() -> list[dict]:
    if not _LOG_FILE.exists():
        return []
    log = json.loads(_LOG_FILE.read_text(encoding="utf-8"))
    return list(reversed(log[-50:]))


async def run_scheduler_inprocess(tenant_id: uuid.UUID) -> None:
    """Run the budget scheduler in-process (avoids Python 3.14 asyncpg SSL bug on Windows)."""
    from scraper.utils.session import load_session

    async with AsyncSessionLocal() as db:
        storage_state = await load_session(db, str(tenant_id), "blinkit")
    if not storage_state:
        return  # No session — skip silently, don't crash the background task

    def _run():
        from ad_campaigns.scheduler import run_with_state

        async def _inner():
            await run_with_state(storage_state)

        _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_playwright_executor, _run)


# ── Bid Optimizer ────────────────────────────────────────────────────────────

def get_bid_optimizer_rules() -> list[dict]:
    if not _BID_RULES_FILE.exists():
        return []
    return json.loads(_BID_RULES_FILE.read_text(encoding="utf-8"))


def add_bid_optimizer_rule(rule: dict) -> dict:
    import uuid as _uuid
    if not rule.get("id"):
        rule["id"] = str(_uuid.uuid4())
    rules = get_bid_optimizer_rules()
    # Replace if same campaign + keyword already exists
    rules = [r for r in rules if not (
        r["campaign_id"] == rule["campaign_id"] and r["keyword"] == rule["keyword"]
    )]
    rules.append(rule)
    _BID_RULES_FILE.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")
    return rule


def remove_bid_optimizer_rule(rule_id: str) -> bool:
    rules = get_bid_optimizer_rules()
    filtered = [r for r in rules if r.get("id") != rule_id]
    if len(filtered) == len(rules):
        return False
    _BID_RULES_FILE.write_text(json.dumps(filtered, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def toggle_bid_optimizer_rule(rule_id: str) -> dict | None:
    rules = get_bid_optimizer_rules()
    for r in rules:
        if r.get("id") == rule_id:
            r["active"] = not r.get("active", True)
            _BID_RULES_FILE.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")
            return r
    return None


def get_bid_optimizer_log() -> list[dict]:
    if not _BID_LOG_FILE.exists():
        return []
    entries = json.loads(_BID_LOG_FILE.read_text(encoding="utf-8"))
    return list(reversed(entries[-100:]))


async def run_bid_optimizer_inprocess(tenant_id: uuid.UUID) -> None:
    from scraper.utils.session import load_session
    async with AsyncSessionLocal() as db:
        storage_state = await load_session(db, str(tenant_id), "blinkit")
    if not storage_state:
        return

    def _run():
        from ad_campaigns.bid_optimizer import run_with_state
        async def _inner():
            await run_with_state(storage_state)
        _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_playwright_executor, _run)


async def run_bid_optimizer_all_tenants() -> None:
    rules = get_bid_optimizer_rules()
    if not any(r.get("active", True) for r in rules):
        return

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
    """Fetch live keyword CPM + position data directly from Blinkit API via Playwright."""
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
                result["keywords"] = await client.get_campaign_keywords(campaign_id)
            finally:
                await browser.close()
                await pw.stop()

        _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_playwright_executor, _run)
    return result.get("keywords", [])


# ── Campaign products ─────────────────────────────────────────────────────────

async def get_campaign_products(tenant_id: uuid.UUID, campaign_id: int) -> list[dict]:
    """Fetch products in a campaign via Playwright (same session as keyword fetch)."""
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
                result["products"] = await client.get_campaign_products(campaign_id)
            finally:
                await browser.close()
                await pw.stop()

        _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_playwright_executor, _run)
    return result.get("products", [])


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
                if resp.get("status") or resp.get("success"):
                    return

                # Attempt 3: UI intercept (only works for ACTIVE / ON_HOLD campaigns)
                api_msg2 = resp.get("message", str(resp))
                log.warning("[set_campaign_budget] attempt 2 failed (%s) — falling back to UI intercept", api_msg2)
                resp = await client.update_campaign_budget_via_ui(campaign_id, budget)
                if not (resp.get("status") or resp.get("success")):
                    raise RuntimeError(f"Blinkit rejected: {resp.get('message', resp)}")
            finally:
                await browser.close()
                await pw.stop()

        _run_in_new_loop(_inner)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_playwright_executor, _run)


# ── Blinkit reconnect ─────────────────────────────────────────────────────────

async def reconnect_blinkit(db_session: AsyncSession, tenant_id: uuid.UUID, magic_link: str) -> None:
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
                    await page.goto(magic_link.strip(), wait_until="networkidle", timeout=45_000)
                    if "/diy/" not in page.url:
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
