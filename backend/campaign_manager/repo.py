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


class DuplicateSchedule(Exception):
    """A budget automation already exists for this campaign.

    One schedule per (tenant, platform, campaign) is a DB constraint — a campaign has one
    everyday budget, and several automations for it could only contradict each other.
    Extra windows go on the existing schedule as rules. Raised as a domain error so the
    API can answer 409 and the CLI can point at the schedule you actually want, instead of
    either surfacing a raw UniqueViolationError."""

    def __init__(self, campaign_id: int, schedule_id: int | None):
        self.campaign_id, self.schedule_id = campaign_id, schedule_id
        where = f"schedule #{schedule_id}" if schedule_id else "an existing schedule"
        super().__init__(
            f"campaign {campaign_id} already has a budget automation ({where}) — "
            "add a window to it instead of creating a second one")


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
            # ORDER BY id is load-bearing, not cosmetic: `budget.target_for_now` takes the
            # FIRST matching rule, so with two overlapping windows the winner is decided
            # here. Without an explicit order Postgres may return them differently between
            # runs, and the same campaign would flip between two budgets for no visible
            # reason. Oldest rule wins — stable, and explainable to a user ("the one you
            # made first takes precedence").
            rules = (await db.execute(
                select(CmBudgetRule).where(CmBudgetRule.schedule_id == s.id)
                .order_by(CmBudgetRule.id)
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


# ── Platform account (advertiser id) — per (tenant, platform), B3 ───────────

async def get_tenant_name(tenant_id: uuid.UUID) -> str | None:
    """The client's display name, for the run header. One row, once per run — a log that
    says "Tenant: Dobra" beats a bare UUID for whoever is reading it.

    Never raises. This is a cosmetic detail in a log line, and it runs BEFORE the engine
    does any real work — letting it fail would take down a whole bid or budget run over a
    label. If the DB is genuinely unreachable the very next repo call says so loudly."""
    from app.models.tenant import Tenant
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(Tenant, tenant_id)
            return row.name if row else None
    except Exception:
        return None


async def get_advertiser(tenant_id: uuid.UUID,
                         platform: str = "blinkit") -> int | str | None:
    """The stored ad-account identity for a tenant, or None if not configured.

    TWO columns, because marketplaces disagree about the shape of an ad account:

    * **Blinkit** — an integer `advertiser_id` that appears in NO read API. It has
      to be captured once from a dashboard write and SENT with every live write; a
      stale value spends real money on the wrong account (that is B3).
    * **Zepto** — a brand UUID in `account_ref`. It arrives in the login response,
      so it is never sent; it is stored only to ASSERT that the live session belongs
      to the account we think it does.

    Returns whichever is populated. An `int` means "send this"; a `str` means
    "check against this".
    """
    from app.models.campaign_manager_v2 import CmPlatformAccount
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(CmPlatformAccount).where(
                CmPlatformAccount.tenant_id == tenant_id,
                CmPlatformAccount.platform == platform,
            )
        )).scalars().first()
        if row is None:
            return None
        if row.advertiser_id is not None:
            return int(row.advertiser_id)
        return row.account_ref or None


async def set_advertiser(tenant_id: uuid.UUID, account: int | str,
                         platform: str = "blinkit") -> None:
    """Upsert the tenant's ad-account identity (set once at onboarding).

    The column follows the id's own shape rather than the marketplace name: an
    integer lands in `advertiser_id`, anything else in `account_ref`. Keeping the
    integer column typed is what lets Blinkit's write path stay unchanged.
    """
    from app.models.campaign_manager_v2 import CmPlatformAccount
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(CmPlatformAccount).where(
                CmPlatformAccount.tenant_id == tenant_id,
                CmPlatformAccount.platform == platform,
            )
        )).scalars().first()
        numeric = isinstance(account, int) or str(account).strip().isdigit()
        fields = ({"advertiser_id": int(account), "account_ref": None} if numeric
                  else {"advertiser_id": None, "account_ref": str(account).strip()})
        if row:
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = now_ist()
        else:
            db.add(CmPlatformAccount(tenant_id=tenant_id, platform=platform, **fields))
        await db.commit()


async def get_armed(tenant_id: uuid.UUID, platform: str = "blinkit") -> bool:
    """Is this tenant armed for LIVE writes (the V5 cutover switch)? False if unset."""
    from app.models.campaign_manager_v2 import CmPlatformAccount
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(CmPlatformAccount).where(
                CmPlatformAccount.tenant_id == tenant_id,
                CmPlatformAccount.platform == platform,
            )
        )).scalars().first()
        return bool(row and row.live_armed)


async def set_armed(tenant_id: uuid.UUID, armed: bool, platform: str = "blinkit") -> bool:
    """Arm/disarm a tenant for LIVE writes. Returns False (no-op) if the tenant has no
    account row — arming without one is meaningless (live writes would refuse), so the
    caller should set the account first."""
    from app.models.campaign_manager_v2 import CmPlatformAccount
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(CmPlatformAccount).where(
                CmPlatformAccount.tenant_id == tenant_id,
                CmPlatformAccount.platform == platform,
            )
        )).scalars().first()
        if not row:
            return False
        row.live_armed = bool(armed)
        row.updated_at = now_ist()
        await db.commit()
        return True


# ── Rules CRUD (service layer — the CLI uses it now, the V4 API will reuse it) ──

async def create_budget_schedule(tenant_id: uuid.UUID, platform: str, campaign_id: int,
                                 campaign_name: str, default_budget: float, name: str | None = None,
                                 stop_after_window: bool = False):
    """Create a budget-schedule container for a campaign. Raises on the unique
    (tenant, platform, campaign_id) conflict."""
    from sqlalchemy.exc import IntegrityError

    from app.models.campaign_manager_v2 import CmBudgetSchedule
    async with AsyncSessionLocal() as db:
        s = CmBudgetSchedule(tenant_id=tenant_id, platform=platform, campaign_id=campaign_id,
                             campaign_name=campaign_name, name=name, default_budget=default_budget,
                             stop_after_window=stop_after_window,
                             enabled=True)
        db.add(s)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = (await db.execute(
                select(CmBudgetSchedule).where(
                    CmBudgetSchedule.tenant_id == tenant_id,
                    CmBudgetSchedule.platform == platform,
                    CmBudgetSchedule.campaign_id == campaign_id,
                )
            )).scalars().first()
            raise DuplicateSchedule(campaign_id, existing.id if existing else None) from None
        await db.refresh(s)
        return s


async def add_budget_rule(schedule_id: int, *, budget: float, type: str = "recurring",
                          days: list | None = None, time_slots: list | None = None,
                          start_time=None, end_time=None, start_date=None, end_date=None, date=None):
    """Add one rule to an existing budget schedule."""
    from app.models.campaign_manager_v2 import CmBudgetRule
    async with AsyncSessionLocal() as db:
        r = CmBudgetRule(schedule_id=schedule_id, type=type, days=days or [],
                         time_slots=time_slots or [], start_time=start_time, end_time=end_time,
                         start_date=start_date, end_date=end_date, date=date, budget=budget)
        db.add(r)
        await db.commit()
        await db.refresh(r)
        return r


async def delete_budget_schedule(schedule_id: int) -> bool:
    """Delete a budget schedule and its rules (FK is ON DELETE CASCADE; explicit too)."""
    from app.models.campaign_manager_v2 import CmBudgetRule, CmBudgetSchedule
    async with AsyncSessionLocal() as db:
        s = await db.get(CmBudgetSchedule, schedule_id)
        if not s:
            return False
        for r in (await db.execute(
            select(CmBudgetRule).where(CmBudgetRule.schedule_id == schedule_id)
        )).scalars().all():
            await db.delete(r)
        await db.delete(s)
        await db.commit()
        return True


async def delete_budget_rule(rule_id: int) -> bool:
    """Delete a single budget rule, keeping its schedule (so the schedule's default
    budget applies on the next run — the clean way to revert a rule-driven change)."""
    from app.models.campaign_manager_v2 import CmBudgetRule
    async with AsyncSessionLocal() as db:
        r = await db.get(CmBudgetRule, rule_id)
        if not r:
            return False
        await db.delete(r)
        await db.commit()
        return True


async def create_bid_rule(tenant_id: uuid.UUID, platform: str, campaign_id: int, campaign_name: str,
                          keyword: str, target_position: int, min_bid: int,
                          max_bid: int | None = None, *,
                          match_type: str = "EXACT", type: str = "recurring", date=None,
                          days: list | None = None, start_time=None, stop_time=None,
                          start_date=None, stop_date=None, lat=None, lon=None,
                          location_name=None, brand_name=None):
    """Create a keyword bid rule (runtime row is created lazily by the optimizer)."""
    from app.models.campaign_manager_v2 import CmBidRule
    async with AsyncSessionLocal() as db:
        r = CmBidRule(id=uuid.uuid4().hex, tenant_id=tenant_id, platform=platform,
                      campaign_id=campaign_id, campaign_name=campaign_name, keyword=keyword,
                      match_type=match_type, type=type, date=date, days=days or [],
                      target_position=target_position, min_bid=min_bid, max_bid=max_bid,
                      start_time=start_time, stop_time=stop_time, start_date=start_date,
                      stop_date=stop_date, lat=lat, lon=lon, location_name=location_name,
                      brand_name=brand_name, active=True)
        db.add(r)
        await db.commit()
        await db.refresh(r)
        return r


async def resolve_store(platform: str, *, city: str | None = None,
                        location_id: str | None = None) -> tuple[float | None, float | None, str] | None:
    """Resolve a bid rule's measurement point from the darkstore catalog: a specific
    store by `location_id` (merchant_id), or a representative active store in `city`.
    Returns (lat, lon, label) or None if nothing matches.

    `city` may be OUR catalog name or the MARKETPLACE's own (V7.3) — a campaign's targeting
    arrives as the latter, and the two disagree wherever our catalog groups cities that the
    ad platform lists separately (Blinkit's `Gurugram` is inside our `hr-ncr`). Resolution
    goes through the CANONICAL registry, and the stores themselves carry `city_id`, so the
    grouped catalog names never have to be understood here:

        1. `<platform>:ads` alias → canonical city → stores tagged with it;
        2. a canonical city NAME match, for the names that need no alias;
        3. the catalog's own `city` text, so a caller passing our name still works;
        4. nothing — the caller asks the user to pick a store. Never a guess.
    """
    from sqlalchemy import func
    from app.models.search import City, CityAlias, MarketplaceLocation

    async with AsyncSessionLocal() as db:
        q = select(MarketplaceLocation).where(
            MarketplaceLocation.mp_slug == platform,
            MarketplaceLocation.is_active == True,  # noqa: E712
        )
        if location_id:
            q = q.where(MarketplaceLocation.merchant_id == location_id)
        elif city:
            key = city.strip().lower()
            city_id = (await db.execute(
                select(CityAlias.city_id).where(
                    CityAlias.source == f"{platform}:ads",
                    CityAlias.alias == key,
                    CityAlias.is_active == True,  # noqa: E712
                )
            )).scalars().first()
            if city_id is None:
                city_id = (await db.execute(
                    select(City.id).where(func.lower(City.name) == key)
                )).scalars().first()
            if city_id is not None:
                q = q.where(MarketplaceLocation.city_id == city_id)
            else:
                q = q.where(func.lower(MarketplaceLocation.city) == key)
        # Deterministic representative store when a city matches several.
        row = (await db.execute(q.order_by(MarketplaceLocation.merchant_id).limit(1))).scalars().first()
        if not row:
            return None
        label = row.location_name or f"{row.city}/{row.merchant_id}"
        return row.lat, row.lon, label


async def get_bid_context(tenant_id: uuid.UUID, campaign_id: int, platform: str = "blinkit"):
    """What the bid-rule form needs to know about a campaign, from the DAILY SCRAPE (V7.4).

    Returns (campaign_row, keyword_rows) or (None, []) when the campaign has never been
    scraped with V7 in place — the caller then falls back to today's behaviour rather than
    blocking, because a campaign created since the last scrape is a normal state, not an
    error.

    Reads only scraped tables, never Blinkit: this is served by the API on Render, which
    has no browser (D2). The authoritative floor check happens at WRITE time on the VM.
    """
    from app.models.blinkit_marketing import BlinkitAdCampaign, BlinkitAdCampaignKeyword

    async with AsyncSessionLocal() as db:
        campaign = (await db.execute(
            select(BlinkitAdCampaign).where(
                BlinkitAdCampaign.tenant_id == tenant_id,
                BlinkitAdCampaign.platform == platform,
                BlinkitAdCampaign.campaign_id == campaign_id,
            )
        )).scalars().first()
        keywords = (await db.execute(
            select(BlinkitAdCampaignKeyword).where(
                BlinkitAdCampaignKeyword.tenant_id == tenant_id,
                BlinkitAdCampaignKeyword.platform == platform,
                BlinkitAdCampaignKeyword.campaign_id == campaign_id,
            ).order_by(BlinkitAdCampaignKeyword.keyword,
                       BlinkitAdCampaignKeyword.match_type)
        )).scalars().all()
    return campaign, list(keywords)


async def get_keyword_floor(tenant_id: uuid.UUID, campaign_id: int, keyword: str,
                            match_type: str = "EXACT", platform: str = "blinkit") -> int | None:
    """Blinkit's published minimum bid for one keyword, or None when we have not scraped it.

    None means "no opinion", never "no floor": a keyword the campaign does not carry yet has
    no scraped row, and refusing to save a rule for it would block the exact case someone
    is trying to set up.
    """
    from sqlalchemy import func
    from app.models.blinkit_marketing import BlinkitAdCampaignKeyword

    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(BlinkitAdCampaignKeyword.min_bid).where(
                BlinkitAdCampaignKeyword.tenant_id == tenant_id,
                BlinkitAdCampaignKeyword.platform == platform,
                BlinkitAdCampaignKeyword.campaign_id == campaign_id,
                func.lower(BlinkitAdCampaignKeyword.keyword) == (keyword or "").strip().lower(),
                BlinkitAdCampaignKeyword.match_type == (match_type or "EXACT").upper(),
            )
        )).scalars().first()


async def get_budget_schedule(schedule_id: int):
    from app.models.campaign_manager_v2 import CmBudgetSchedule
    async with AsyncSessionLocal() as db:
        return await db.get(CmBudgetSchedule, schedule_id)


async def get_bid_rule(rule_id: str):
    from app.models.campaign_manager_v2 import CmBidRule
    async with AsyncSessionLocal() as db:
        return await db.get(CmBidRule, rule_id)


async def get_budget_rule(rule_id: int):
    from app.models.campaign_manager_v2 import CmBudgetRule
    async with AsyncSessionLocal() as db:
        return await db.get(CmBudgetRule, rule_id)


async def set_budget_state(schedule_id: int, state: str):
    """Set a budget schedule's D19 state (active/stopped). Returns the row or None."""
    from app.models.campaign_manager_v2 import CmBudgetSchedule
    async with AsyncSessionLocal() as db:
        s = await db.get(CmBudgetSchedule, schedule_id)
        if not s:
            return None
        s.state = state
        s.enabled = (state == "active")
        await db.commit()
        await db.refresh(s)
        return s


async def set_bid_state(rule_id: str, state: str):
    """Set a bid rule's D19 state (active/paused/stopped). Returns the row or None."""
    from app.models.campaign_manager_v2 import CmBidRule
    async with AsyncSessionLocal() as db:
        r = await db.get(CmBidRule, rule_id)
        if not r:
            return None
        r.state = state
        r.active = (state == "active")
        await db.commit()
        await db.refresh(r)
        return r


async def update_budget_schedule(schedule_id: int, fields: dict):
    """Patch a budget schedule's editable fields (name, default_budget). Returns row or None."""
    from app.models.campaign_manager_v2 import CmBudgetSchedule
    async with AsyncSessionLocal() as db:
        s = await db.get(CmBudgetSchedule, schedule_id)
        if not s:
            return None
        for k, v in fields.items():
            setattr(s, k, v)
        await db.commit()
        await db.refresh(s)
        return s


async def update_budget_rule(rule_id: int, fields: dict):
    """Patch a budget rule's editable fields (budget + timing). Returns row or None."""
    from app.models.campaign_manager_v2 import CmBudgetRule
    async with AsyncSessionLocal() as db:
        r = await db.get(CmBudgetRule, rule_id)
        if not r:
            return None
        for k, v in fields.items():
            setattr(r, k, v)
        await db.commit()
        await db.refresh(r)
        return r


async def update_bid_rule(rule_id: str, fields: dict):
    """Patch a bid rule's editable fields (target/bids/timing/location). Returns row or None.

    Editing `max_bid` or `target_position` also voids any relaxed target in runtime: it was
    concluded against the OLD ceiling and the OLD goal, so keeping it would be wrong — most
    sharply when `max_bid` is raised, where a stale relaxed target has the optimizer drift
    DOWN just after being handed more room to climb. `bid.stored_effective_target` guards
    the `max_bid` case on read too (self-healing for edits that bypass this function); the
    `target_position` case has no such tell, so it is cleared here."""
    from app.models.campaign_manager_v2 import CmBidRule, CmBidRuntime
    async with AsyncSessionLocal() as db:
        r = await db.get(CmBidRule, rule_id)
        if not r:
            return None
        for k, v in fields.items():
            setattr(r, k, v)
        if "max_bid" in fields or "target_position" in fields:
            rt = await db.get(CmBidRuntime, rule_id)
            if rt:
                rt.effective_target = None
                rt.effective_at_max_bid = None
        await db.commit()
        await db.refresh(r)
        return r


async def list_run_log(tenant_id: uuid.UUID, platform: str = "blinkit", *,
                       kind: str | None = None, limit: int = 50, offset: int = 0):
    """Recent cm_run_log rows for a tenant (newest first) + total count."""
    from sqlalchemy import func
    from app.models.campaign_manager_v2 import CmRunLog

    async with AsyncSessionLocal() as db:
        base = select(CmRunLog).where(CmRunLog.tenant_id == tenant_id,
                                      CmRunLog.platform == platform)
        if kind:
            base = base.where(CmRunLog.kind == kind)
        total = (await db.execute(
            select(func.count()).select_from(base.subquery())
        )).scalar() or 0
        rows = (await db.execute(
            base.order_by(CmRunLog.timestamp.desc()).limit(limit).offset(offset)
        )).scalars().all()
        return list(rows), int(total)


async def delete_bid_rule(rule_id: str) -> bool:
    """Delete a bid rule and its runtime row (FK is ON DELETE CASCADE; explicit too)."""
    from app.models.campaign_manager_v2 import CmBidRule, CmBidRuntime
    async with AsyncSessionLocal() as db:
        r = await db.get(CmBidRule, rule_id)
        if not r:
            return False
        rt = await db.get(CmBidRuntime, rule_id)
        if rt:
            await db.delete(rt)
        await db.delete(r)
        await db.commit()
        return True


# Actions that represent a real value write (as opposed to a skip/no-op/error). Bids
# gained `drift`/`recover`/`open` alongside `apply`; all of them are PUTs and all of them
# must count toward the runaway-loop guard.
_WRITE_ACTIONS = ("apply", "drift", "recover", "open", "reset", "bounds")


async def recent_write_count(tenant_id: uuid.UUID, campaign_id: int, *,
                             window_minutes: int, kind: str,
                             keyword: str | None = None) -> int:
    """How many successful writes happened within the window (rate limit).

    Scoped to a KEYWORD when one is given. The guard exists to catch a runaway loop, and
    a keyword-level count still does that — while a campaign-level count would let one
    busy keyword throttle every other keyword on the same campaign, which is the wrong
    failure. Budget keeps the campaign-level count (a campaign has one budget).
    """
    from sqlalchemy import func
    from app.models.campaign_manager_v2 import CmRunLog

    cutoff = now_ist() - timedelta(minutes=window_minutes)
    async with AsyncSessionLocal() as db:
        q = select(func.count()).select_from(CmRunLog).where(
            CmRunLog.tenant_id == tenant_id,
            CmRunLog.campaign_id == campaign_id,
            CmRunLog.kind == kind,
            CmRunLog.action.in_(_WRITE_ACTIONS),
            CmRunLog.dry_run == False,  # noqa: E712 — only real writes count
            CmRunLog.timestamp >= cutoff,
        )
        if keyword is not None:
            q = q.where(CmRunLog.keyword == keyword)
        n = (await db.execute(q)).scalar()
        return int(n or 0)


async def write_bid_runtime(rows: list[dict]) -> None:
    """Upsert 1:1 runtime state per bid rule (Q2). Each row = {rule_id, + any of
    last_cpm / last_position / last_bid_updated_at}. Only the provided fields are
    updated (a HOLD/dry-run pass that saw a position but wrote no bid updates only
    `last_position`, never nulling `last_cpm`). No-op on empty."""
    if not rows:
        return
    from sqlalchemy.dialects.postgresql import insert
    from app.models.campaign_manager_v2 import CmBidRuntime

    async with AsyncSessionLocal() as db:
        for r in rows:
            values = {**r, "updated_at": now_ist()}
            stmt = insert(CmBidRuntime).values(**values).on_conflict_do_update(
                index_elements=["rule_id"],
                set_={k: v for k, v in values.items() if k != "rule_id"},
            )
            await db.execute(stmt)
        await db.commit()


async def upsert_campaign_catalog(tenant_id: uuid.UUID, campaigns: list[dict],
                                  platform: str = "blinkit") -> int:
    """Refresh the campaign catalogue from a live account listing. Returns rows written.

    This is the one place the campaign manager writes OUTSIDE its own cm_* tables: the
    catalogue (`blinkit_ad_campaigns`) is shared with the marketing scraper and Ads
    Analytics. That is deliberate — a second cm-owned copy would drift from the scraper's,
    and the pickers' freshness filter only means anything against a single catalogue.

    It is safe because this writes the SAME source the scraper does (the account campaign
    list) in the same shape, keyed on the same `upsert_key`. Two things it will not touch:
    `scrape_job_id` (this run has no scrape job, and blanking it would destroy the
    scraper's lineage) and `platform`/`tenant_id` (identity). `scraped_at` DOES advance —
    that is the point, since freshness is what marks a campaign as still on the account.
    """
    if not campaigns:
        return 0
    from sqlalchemy.dialects.postgresql import insert

    from app.models.blinkit_marketing import BlinkitAdCampaign
    from scraper.platforms.blinkit.dashboard_data.marketing.parser import parse_campaign
    from scraper.platforms.blinkit.dashboard_data.marketing.storage import prepare_row

    rows = []
    for raw in campaigns:
        if raw.get("id") is None:
            continue
        row = parse_campaign(raw, str(tenant_id), None)
        row.pop("scrape_job_id")            # keep the scraper's lineage intact
        row["platform"] = platform
        rows.append(prepare_row(BlinkitAdCampaign, row))
    # ON CONFLICT cannot update the same row twice in one statement.
    rows = list({r["upsert_key"]: r for r in rows}.values())
    if not rows:
        return 0

    # ⚠️ Deliberately excludes the detail-derived columns (region_type / cities / min_cpm /
    # pacing_type / billed_amount / campaign_cpm, V7). This refresh reads only the campaign
    # LIST, which carries none of them, so listing them here would blank a campaign's city
    # targeting and budget floor every time someone clicked Refresh.
    updatable = {"name", "type", "status", "start_ts", "end_ts",
                 "infinite_campaign", "daily_budget", "scraped_at"}
    async with AsyncSessionLocal() as db:
        stmt = insert(BlinkitAdCampaign).values(rows).on_conflict_do_update(
            index_elements=["upsert_key"],
            set_={c: insert(BlinkitAdCampaign).excluded[c] for c in updatable},
        )
        await db.execute(stmt)
        await db.commit()
    return len(rows)


async def write_run_log(rows: list[dict]) -> None:
    """Append slim history rows for the UI. No-op on empty."""
    if not rows:
        return
    from app.models.campaign_manager_v2 import CmRunLog

    async with AsyncSessionLocal() as db:
        for r in rows:
            db.add(CmRunLog(**r))
        await db.commit()
