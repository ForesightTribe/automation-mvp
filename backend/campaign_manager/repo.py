"""Tenant-scoped DB access for the campaign manager — cm_* tables, NO JSON files.

Reads rules, writes the slim run-log, and (V2+) persists bid runtime. Everything is
scoped by tenant_id (+ platform). Kept thin: the orchestration decides *what*, this
only reads/writes rows.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.utils.logger import logger
from app.utils.time import now_ist
from campaign_manager import window


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


# ── Rule loaders: the caller says WHICH automations, on both axes ────────────
#
# `state` is the user axis (what a person chose, stored). `calendar` is the calendar axis
# (scheduled / running / ended — what the dates say, derived by `window`). Both are REQUIRED
# keywords with no default. The loaders used to hand back every row and let each engine
# filter; every engine thought of `state` and none of the calendar, which is how automations
# that had ENDED kept being reset and kept having their budgets enforced (2026-09-10).
#
# `ANY_STATE` / `ANY_CALENDAR` are for callers that genuinely want everything — the point is
# that "everything" is now written at the call site, where a reviewer can see it.

ANY_STATE = None
ANY_CALENDAR = window.ANY_CALENDAR


def _calendar_filter(calendar, now: datetime | None) -> frozenset | None:
    """Check a `calendar` argument → the calendar states to keep, or None for "no filter"."""
    wanted = frozenset(calendar)
    if not wanted or not wanted <= window.ANY_CALENDAR:
        raise ValueError(f"calendar must be a non-empty subset of "
                         f"{sorted(window.ANY_CALENDAR)}, got {sorted(wanted)}")
    if wanted == window.ANY_CALENDAR:
        return None
    if now is None:
        raise ValueError("filtering on the calendar needs `now` — pass the caller's clock")
    return wanted


def _bid_rule_in_calendar(rule, wanted: frozenset | None, now: datetime | None) -> bool:
    return wanted is None or window.calendar_state(window.from_bid(rule), now) in wanted


def _schedule_in_calendar(rules, wanted: frozenset | None, now: datetime | None) -> bool:
    return wanted is None or window.schedule_calendar_state(
        [window.from_budget(r) for r in rules], now) in wanted


async def get_budget_schedules(tenant_id: uuid.UUID, platform: str = "blinkit", *,
                               state: str | None, calendar, now: datetime | None = None):
    """Return [(schedule, [rules])] for a tenant — only the schedules asked for.

    `state`: the schedule's user state (`"active"` / `"stopped"`), or `ANY_STATE`.
    `calendar`: keep schedules whose windows, taken together, are in one of these calendar
    states at `now` (`window.schedule_calendar_state`), or `ANY_CALENDAR` to skip the check.
    """
    from app.models.campaign_manager_v2 import CmBudgetSchedule, CmBudgetRule
    wanted = _calendar_filter(calendar, now)

    async with AsyncSessionLocal() as db:
        query = select(CmBudgetSchedule).where(
            CmBudgetSchedule.tenant_id == tenant_id,
            CmBudgetSchedule.platform == platform,
        )
        if state is not ANY_STATE:
            query = query.where(CmBudgetSchedule.state == state)
        schedules = (await db.execute(query)).scalars().all()
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
            if not _schedule_in_calendar(rules, wanted, now):
                continue
            out.append((s, list(rules)))
        return out


async def get_bid_rules(tenant_id: uuid.UUID, platform: str = "blinkit", *,
                        state: str | None, calendar, now: datetime | None = None):
    """Return [(rule, runtime_or_None)] for a tenant — only the rules asked for.

    `state`: the rule's user state (`"active"` / `"paused"`), or `ANY_STATE`.
    `calendar`: keep rules in one of these calendar states at `now`
    (`window.calendar_state`), or `ANY_CALENDAR` to skip the check.
    """
    from app.models.campaign_manager_v2 import CmBidRule, CmBidRuntime
    wanted = _calendar_filter(calendar, now)

    async with AsyncSessionLocal() as db:
        query = select(CmBidRule).where(
            CmBidRule.tenant_id == tenant_id,
            CmBidRule.platform == platform,
        )
        if state is not ANY_STATE:
            query = query.where(CmBidRule.state == state)
        rules = (await db.execute(query)).scalars().all()
        out = []
        for r in rules:
            if not _bid_rule_in_calendar(r, wanted, now):
                continue
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
                          location_name=None, brand_name=None, city_id=None):
    """Create a keyword bid rule (runtime row is created lazily by the optimizer).
    `city_id` set → the rule follows that city's frozen store; None → pinned to lat/lon."""
    from app.models.campaign_manager_v2 import CmBidRule
    async with AsyncSessionLocal() as db:
        r = CmBidRule(id=uuid.uuid4().hex, tenant_id=tenant_id, platform=platform,
                      campaign_id=campaign_id, campaign_name=campaign_name, keyword=keyword,
                      match_type=match_type, type=type, date=date, days=days or [],
                      target_position=target_position, min_bid=min_bid, max_bid=max_bid,
                      start_time=start_time, stop_time=stop_time, start_date=start_date,
                      stop_date=stop_date, lat=lat, lon=lon, location_name=location_name,
                      brand_name=brand_name, city_id=city_id, active=True)
        db.add(r)
        await db.commit()
        await db.refresh(r)
        return r


# ── Measurement stores — where a bid rule reads its position (cm_city_stores) ─
#
# A rule names a CITY; which store inside it is a SETTING, not a per-rule choice. One frozen
# store per (marketplace, city): a GLOBAL row (tenant_id NULL — the default, set from the CLI)
# and, optionally, a CLIENT row that overrides it. The bid engine resolves it on every run, so
# changing a city's store moves every automation measuring there from the next tick.
#
# Keyed by `merchant_id`, not `marketplace_locations.id`: `cli sync --prune` deletes and
# re-creates catalog rows, and the merchant id is the store's natural key across that.

PRIMARY_RANK = 1    # the store a city measures at; higher ranks are reserved for multi-store
                    # measurement, which is not built


class StoreNotInCity(ValueError):
    """A store that cannot be a city's measurement store: unknown, inactive, without
    coordinates, or in a different city."""


@dataclass(frozen=True)
class MeasurementStore:
    """A real dark store to read positions at, and why it was chosen.

    `source`: `tenant` (the client's override) · `global` (the default for the city) ·
    `catalog` (nothing frozen — the lowest merchant_id in the city, deterministic but
    arbitrary) · `store` (an explicitly named merchant_id)."""
    lat: float
    lon: float
    label: str
    merchant_id: str
    city_id: int | None
    source: str


def store_label(loc) -> str:
    """A catalog store's human name. `.strip()`: names arrive with stray whitespace
    ("Financial District\r\n")."""
    return (loc.location_name or "").strip() or f"{loc.city}/{loc.merchant_id}"


def _store_of(loc, source: str) -> MeasurementStore:
    return MeasurementStore(lat=loc.lat, lon=loc.lon, label=store_label(loc),
                            merchant_id=loc.merchant_id, city_id=loc.city_id, source=source)


def _usable(loc) -> bool:
    return loc is not None and loc.is_active and loc.lat is not None and loc.lon is not None


def pick_city_store(rows, tenant_id: uuid.UUID | None):
    """Pure. The frozen store in force for ONE city, from its `cm_city_stores` rows joined to
    the catalog — `[(city_store, catalog_row | None)]`, possibly spanning several clients.

    The client's own row wins, then the global row; other clients' rows are ignored. A row
    whose store has left the catalog or gone inactive is skipped rather than honoured, so a
    store closing falls through to the next layer instead of measuring nowhere.

    Returns `(city_store, catalog_row, "tenant" | "global")`, or None when nothing usable is
    frozen for the city.
    """
    primary = [(cs, loc) for cs, loc in rows if cs.rank == PRIMARY_RANK and _usable(loc)]
    if tenant_id is not None:
        for cs, loc in primary:
            if cs.tenant_id == tenant_id:
                return cs, loc, "tenant"
    for cs, loc in primary:
        if cs.tenant_id is None:
            return cs, loc, "global"
    return None


async def _city_store_rows(db, platform: str, city_ids, tenant_ids=None) -> list:
    """`[(CmCityStore, MarketplaceLocation | None)]` for these cities. `tenant_ids=None` loads
    every client's rows; a list loads those clients' plus the global ones."""
    from sqlalchemy import and_, or_
    from app.models.campaign_manager_v2 import CmCityStore
    from app.models.search import MarketplaceLocation

    city_ids = [c for c in city_ids if c is not None]
    if not city_ids:
        return []
    q = (select(CmCityStore, MarketplaceLocation)
         .join(MarketplaceLocation,
               and_(MarketplaceLocation.mp_slug == CmCityStore.platform,
                    MarketplaceLocation.merchant_id == CmCityStore.merchant_id),
               isouter=True)
         .where(CmCityStore.platform == platform, CmCityStore.city_id.in_(city_ids))
         .order_by(CmCityStore.city_id, CmCityStore.rank))
    if tenant_ids is not None:
        q = q.where(or_(CmCityStore.tenant_id.is_(None),
                        CmCityStore.tenant_id.in_(list(tenant_ids))))
    return [(cs, loc) for cs, loc in (await db.execute(q)).all()]


async def _resolve_city_id(db, platform: str, city: str | None) -> int | None:
    from sqlalchemy import func
    from app.models.search import City, CityAlias, MarketplaceLocation

    key = (city or "").strip().lower()
    if not key:
        return None
    city_id = (await db.execute(
        select(CityAlias.city_id).where(
            CityAlias.source == f"{platform}:ads",
            CityAlias.alias == key,
            CityAlias.is_active == True,  # noqa: E712
        )
    )).scalars().first()
    if city_id is None:
        city_id = (await db.execute(
            select(City.id).where((func.lower(City.name) == key) | (City.slug == key))
        )).scalars().first()
    if city_id is None:
        # Our catalog's own city text — only when every store under it agrees on one city.
        # `hr-ncr` is all Gurugram; a grouped name spanning two cities stays unresolved.
        ids = (await db.execute(
            select(MarketplaceLocation.city_id).where(
                MarketplaceLocation.mp_slug == platform,
                MarketplaceLocation.is_active == True,  # noqa: E712
                func.lower(MarketplaceLocation.city) == key,
                MarketplaceLocation.city_id.is_not(None),
            ).distinct()
        )).scalars().all()
        city_id = ids[0] if len(ids) == 1 else None
    return city_id


async def resolve_city_id(platform: str, city: str | None) -> int | None:
    """A city name → its canonical `cities.id`, or None.

    Accepts the MARKETPLACE's own name (a campaign's targeting), a canonical name or slug, or
    OUR catalog's city text — they disagree wherever our catalog groups cities the ad platform
    lists separately (Blinkit's `Gurugram` is inside our `hr-ncr`). In order:

        1. `<platform>:ads` alias;
        2. a canonical city name or slug;
        3. the catalog's `city` text, when all its stores carry the same `city_id`;
        4. nothing — never a guess.
    """
    async with AsyncSessionLocal() as db:
        return await _resolve_city_id(db, platform, city)


async def resolve_store(platform: str, *, city: str | None = None,
                        location_id: str | None = None,
                        tenant_id: uuid.UUID | None = None) -> MeasurementStore | None:
    """Where a rule being SAVED would measure, from the darkstore catalog.

    - `location_id` (a merchant_id) → exactly that store (`source="store"`).
    - `city` → the city's FROZEN store (`tenant_id`'s override, then the global default);
      with nothing frozen, the lowest merchant_id in the city (`source="catalog"`) — the old
      behaviour, deterministic but arbitrary, and now only what an unconfigured city gets.
    - no match → None; the caller asks for a store. Never a guess.

    `city_id` on the result is the STORE's city. Whether the rule then follows that city or
    stays pinned to this store is the caller's call: saved by city → follows.
    """
    from sqlalchemy import func
    from app.models.search import MarketplaceLocation

    async with AsyncSessionLocal() as db:
        stores = select(MarketplaceLocation).where(
            MarketplaceLocation.mp_slug == platform,
            MarketplaceLocation.is_active == True,  # noqa: E712
            MarketplaceLocation.lat.is_not(None),
            MarketplaceLocation.lon.is_not(None),
        )
        if location_id:
            row = (await db.execute(
                stores.where(MarketplaceLocation.merchant_id == location_id)
            )).scalars().first()
            return _store_of(row, "store") if row else None
        if not city:
            return None
        city_id = await _resolve_city_id(db, platform, city)
        if city_id is not None:
            picked = pick_city_store(
                await _city_store_rows(db, platform, [city_id], [tenant_id] if tenant_id else []),
                tenant_id)
            if picked:
                return _store_of(picked[1], picked[2])
            stores = stores.where(MarketplaceLocation.city_id == city_id)
        else:
            stores = stores.where(func.lower(MarketplaceLocation.city) == city.strip().lower())
        # Deterministic representative store when nothing is frozen for the city.
        row = (await db.execute(
            stores.order_by(MarketplaceLocation.merchant_id).limit(1)
        )).scalars().first()
        return _store_of(row, "catalog") if row else None


async def city_stores_for(platform: str, tenant_id: uuid.UUID, city_ids) -> dict:
    """`{city_id: MeasurementStore}` — each city's frozen store for ONE client, in one query
    (the bid engine calls this once per run). A city with nothing usable frozen is absent, and
    the engine keeps each rule's saved store. A frozen store that is no longer an active
    catalog store is logged: it silently changes where automations measure."""
    async with AsyncSessionLocal() as db:
        rows = await _city_store_rows(db, platform, set(city_ids), [tenant_id])
    by_city: dict[int, list] = {}
    for cs, loc in rows:
        by_city.setdefault(cs.city_id, []).append((cs, loc))
        if cs.rank == PRIMARY_RANK and not _usable(loc):
            logger.warning(f"cm: frozen {platform} store {cs.merchant_id} for city {cs.city_id} "
                           f"is not an active catalog store with coordinates — skipped")
    out = {}
    for city_id, city_rows in by_city.items():
        picked = pick_city_store(city_rows, tenant_id)
        if picked:
            out[city_id] = _store_of(picked[1], picked[2])
    return out


async def get_city(city_id: int):
    from app.models.search import City
    async with AsyncSessionLocal() as db:
        return await db.get(City, city_id)


async def city_store_candidates(platform: str, city_id: int) -> list:
    """Every active store with coordinates in a city — what its frozen store can be."""
    from app.models.search import MarketplaceLocation
    async with AsyncSessionLocal() as db:
        return list((await db.execute(
            select(MarketplaceLocation).where(
                MarketplaceLocation.mp_slug == platform,
                MarketplaceLocation.city_id == city_id,
                MarketplaceLocation.is_active == True,  # noqa: E712
                MarketplaceLocation.lat.is_not(None),
                MarketplaceLocation.lon.is_not(None),
            ).order_by(MarketplaceLocation.location_name, MarketplaceLocation.merchant_id)
        )).scalars().all())


async def list_city_stores(platform: str, *, tenant_ids=None, city_id: int | None = None) -> list:
    """`[(CmCityStore, MarketplaceLocation | None, City | None)]` — frozen stores, for display.
    `tenant_ids=None` lists every client's overrides as well as the global defaults."""
    from sqlalchemy import and_, or_
    from app.models.campaign_manager_v2 import CmCityStore
    from app.models.search import City, MarketplaceLocation

    async with AsyncSessionLocal() as db:
        q = (select(CmCityStore, MarketplaceLocation, City)
             .join(MarketplaceLocation,
                   and_(MarketplaceLocation.mp_slug == CmCityStore.platform,
                        MarketplaceLocation.merchant_id == CmCityStore.merchant_id),
                   isouter=True)
             .join(City, City.id == CmCityStore.city_id, isouter=True)
             .where(CmCityStore.platform == platform)
             .order_by(City.name, CmCityStore.tenant_id.is_not(None), CmCityStore.rank))
        if city_id is not None:
            q = q.where(CmCityStore.city_id == city_id)
        if tenant_ids is not None:
            q = q.where(or_(CmCityStore.tenant_id.is_(None),
                            CmCityStore.tenant_id.in_(list(tenant_ids))))
        return [tuple(r) for r in (await db.execute(q)).all()]


async def set_city_store(platform: str, city_id: int, merchant_id: str, *,
                         tenant_id: uuid.UUID | None) -> tuple[MeasurementStore, int]:
    """Freeze `merchant_id` as the store `city_id`'s bid automations measure at — for one
    client, or with `tenant_id=None` as the GLOBAL default for every client without an
    override. Refuses a store that is unknown, inactive, has no coordinates, or sits in a
    different city: an automation for Bengaluru must never quietly measure in Mysuru.

    Returns (the store, how many automations were re-pointed at it)."""
    from app.models.campaign_manager_v2 import CmCityStore
    from app.models.search import City, MarketplaceLocation

    async with AsyncSessionLocal() as db:
        loc = (await db.execute(select(MarketplaceLocation).where(
            MarketplaceLocation.mp_slug == platform,
            MarketplaceLocation.merchant_id == merchant_id,
        ))).scalars().first()
        if not _usable(loc):
            raise StoreNotInCity(f"{merchant_id!r} is not an active {platform} store with "
                                 f"coordinates in the catalog")
        store = _store_of(loc, "global" if tenant_id is None else "tenant")
        if loc.city_id != city_id:
            wanted = await db.get(City, city_id)
            actual = await db.get(City, loc.city_id) if loc.city_id is not None else None
            raise StoreNotInCity(
                f"store {merchant_id} ({store.label}) is in "
                f"{actual.name if actual else 'no registered city'}, not "
                f"{wanted.name if wanted else f'city {city_id}'}")
        scope = (CmCityStore.tenant_id.is_(None) if tenant_id is None
                 else CmCityStore.tenant_id == tenant_id)
        row = (await db.execute(select(CmCityStore).where(
            CmCityStore.platform == platform, CmCityStore.city_id == city_id,
            CmCityStore.rank == PRIMARY_RANK, scope,
        ))).scalars().first()
        if row:
            row.merchant_id, row.updated_at = merchant_id, now_ist()
        else:
            db.add(CmCityStore(tenant_id=tenant_id, platform=platform, city_id=city_id,
                               merchant_id=merchant_id, rank=PRIMARY_RANK))
        await db.commit()
        moved = await _repoint_rules(db, platform, city_id, tenant_id)
    return store, moved


async def clear_city_store(platform: str, city_id: int, *,
                           tenant_id: uuid.UUID | None) -> tuple[bool, int]:
    """Remove a frozen store — a client's override (its automations move to the global
    default, if one exists) or, with `tenant_id=None`, the global default (automations with
    no override then keep the store they were last saved at: nothing moves).

    Returns (removed?, how many automations were re-pointed)."""
    from app.models.campaign_manager_v2 import CmCityStore

    async with AsyncSessionLocal() as db:
        scope = (CmCityStore.tenant_id.is_(None) if tenant_id is None
                 else CmCityStore.tenant_id == tenant_id)
        row = (await db.execute(select(CmCityStore).where(
            CmCityStore.platform == platform, CmCityStore.city_id == city_id,
            CmCityStore.rank == PRIMARY_RANK, scope,
        ))).scalars().first()
        if not row:
            return False, 0
        await db.delete(row)
        await db.commit()
        return True, await _repoint_rules(db, platform, city_id, tenant_id)


async def _repoint_rules(db, platform: str, city_id: int, tenant_id: uuid.UUID | None) -> int:
    """Bring saved automations in line with their city's frozen store after it changes.

    The engine resolves the store on every run anyway (`bid.measurement_point`), so this is
    not what moves the MEASUREMENT. It keeps the rule row honest for everything that reads it
    (the automations list, the CLI), and clears what the engine learned at the old store:
    positions differ between stores, so the last position, the holding price and a relaxed
    target would each feed the first decision at the new store a fact about another one — the
    same reason Resume clears them (`_RUNTIME_MEMORY`, `updated_at` deliberately kept).

    Only rules that FOLLOW the city (`city_id` set) move; pinned ones never do. `tenant_id`
    narrows to one client (their override changed); None covers every client (the global
    default changed — a client with its own override is unaffected, `pick_city_store` sees to
    that). A rule whose city is left with nothing frozen keeps its saved store."""
    from app.models.campaign_manager_v2 import CmBidRule, CmBidRuntime

    q = select(CmBidRule).where(CmBidRule.platform == platform, CmBidRule.city_id == city_id)
    if tenant_id is not None:
        q = q.where(CmBidRule.tenant_id == tenant_id)
    rules = (await db.execute(q)).scalars().all()
    if not rules:
        return 0
    rows = await _city_store_rows(db, platform, [city_id])
    moved = 0
    for r in rules:
        picked = pick_city_store(rows, r.tenant_id)
        if not picked:
            continue
        store = _store_of(picked[1], picked[2])
        if (r.lat, r.lon) == (store.lat, store.lon):
            continue
        r.lat, r.lon, r.location_name = store.lat, store.lon, store.label
        rt = await db.get(CmBidRuntime, r.id)
        if rt:
            for field in _RUNTIME_MEMORY:
                setattr(rt, field, None)
        moved += 1
    await db.commit()
    return moved


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
    """Set a bid rule's lifecycle state (`active` / `paused`). Returns the row or None."""
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


# Everything the engine LEARNED, as opposed to what it did. Cleared on resume: a bid rule
# that has been paused for six hours knows nothing useful about the auction any more, and
# every one of these fields is an input to a decision.
_RUNTIME_MEMORY = ("last_cpm", "last_position", "last_bid_updated_at", "last_holding_cpm",
                   "drift_paused_until", "effective_target", "effective_at_max_bid",
                   "raise_step")


async def clear_bid_runtime(rule_id: str) -> bool:
    """Forget everything the engine learned about this rule, but KEEP `updated_at`.

    ⚠️ `updated_at` is load-bearing and must not be touched. The engine decides whether a
    window has already been opened with `runtime.updated_at >= window_start`, so preserving
    it makes Resume do the right thing for free:

      paused and resumed INSIDE one window  → updated_at is after the window start
                                              → carry on from the live bid
      paused ACROSS a window start          → updated_at is before it
                                              → the next tick re-opens at the floor

    Which is also why this cannot go through `write_bid_runtime`: that stamps
    `updated_at = now()` on every call, so using it here would make every resume look
    mid-window and silently skip the floor.
    """
    from app.models.campaign_manager_v2 import CmBidRuntime
    async with AsyncSessionLocal() as db:
        rt = await db.get(CmBidRuntime, rule_id)
        if not rt:
            return False
        for field in _RUNTIME_MEMORY:
            setattr(rt, field, None)
        await db.commit()
        return True


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


# Actions that record a tick where NOTHING changed. Stored (a per-automation view is made
# of them) but filtered out of the default History, which is a list of what the automation
# DID — a "held at ₹201" row every 15 minutes would bury the changes among them.
NO_CHANGE_ACTIONS = ("hold", "no-op")


async def list_run_log(tenant_id: uuid.UUID, platform: str = "blinkit", *,
                       kind: str | None = None, limit: int = 50, offset: int = 0,
                       campaign_id: int | None = None, rule_id: str | None = None,
                       include_unchanged: bool = False):
    """Recent cm_run_log rows for a tenant (newest first) + total count.

    Defaults to CHANGES ONLY. Pass `include_unchanged=True` for the full per-tick record —
    that is the per-automation drill-down, where "we held, and here is why" is the answer
    being looked for. `campaign_id` / `rule_id` narrow it to one campaign or automation.
    """
    from sqlalchemy import func
    from app.models.campaign_manager_v2 import CmRunLog

    async with AsyncSessionLocal() as db:
        base = select(CmRunLog).where(CmRunLog.tenant_id == tenant_id,
                                      CmRunLog.platform == platform)
        if kind:
            base = base.where(CmRunLog.kind == kind)
        if campaign_id is not None:
            base = base.where(CmRunLog.campaign_id == campaign_id)
        if rule_id is not None:
            base = base.where(CmRunLog.rule_id == rule_id)
        if not include_unchanged:
            base = base.where(CmRunLog.action.notin_(NO_CHANGE_ACTIONS))
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


# ── Settle-once lifecycle writes (campaign_manager/lifecycle.py) ─────────────
#
# `kind` is "bid" (keyed by cm_bid_rules.id) or "budget" (keyed by cm_budget_schedules.id).
# Every writer is a no-op on empty input, so a run with no ending automation never opens a
# session for it.

_LIFECYCLE_COLUMNS = frozenset({"ended_at", "settled_at", "settle_attempts"})


def _lifecycle_model(kind: str):
    from app.models.campaign_manager_v2 import CmBidRule, CmBudgetSchedule
    return {"bid": CmBidRule, "budget": CmBudgetSchedule}[kind]


async def mark_settled(kind: str, stamps: dict) -> None:
    """Latch final teardowns as landed: `settled_at` per id, and attempts back to 0."""
    if not stamps:
        return
    from sqlalchemy import update
    model = _lifecycle_model(kind)
    async with AsyncSessionLocal() as db:
        for id_, stamp in stamps.items():
            await db.execute(update(model).where(model.id == id_)
                             .values(settled_at=stamp, settle_attempts=0))
        await db.commit()


async def bump_settle_attempts(kind: str, ids) -> list:
    """Count one failed final teardown against each id. Returns the ids that have JUST used up
    `config.SETTLE_MAX_ATTEMPTS` — the settle pass gives up on those, and the caller records
    that in History exactly once. Read back from the UPDATE itself, so it is the DB's count
    and not a guess from a row loaded earlier."""
    ids = list(ids)
    if not ids:
        return []
    from sqlalchemy import update
    from campaign_manager import config
    model = _lifecycle_model(kind)
    async with AsyncSessionLocal() as db:
        result = await db.execute(update(model).where(model.id.in_(ids))
                                  .values(settle_attempts=model.settle_attempts + 1)
                                  .returning(model.id, model.settle_attempts))
        exhausted = [id_ for id_, attempts in result.all()
                     if attempts == config.SETTLE_MAX_ATTEMPTS]
        await db.commit()
    return exhausted


async def write_lifecycle_markers(kind: str, changes: dict) -> None:
    """Apply the reconciler's sweep: {id: {column: value}}. Refuses anything that is not a
    lifecycle column, so a bug upstream cannot turn this into a general-purpose UPDATE."""
    if not changes:
        return
    from sqlalchemy import update
    model = _lifecycle_model(kind)
    async with AsyncSessionLocal() as db:
        for id_, values in changes.items():
            unknown = set(values) - _LIFECYCLE_COLUMNS
            if unknown:
                raise ValueError(f"not a lifecycle column: {sorted(unknown)}")
            await db.execute(update(model).where(model.id == id_).values(**values))
        await db.commit()


async def write_run_log(rows: list[dict]) -> None:
    """Append slim history rows for the UI. No-op on empty."""
    if not rows:
        return
    from app.models.campaign_manager_v2 import CmRunLog

    async with AsyncSessionLocal() as db:
        for r in rows:
            db.add(CmRunLog(**r))
        await db.commit()
