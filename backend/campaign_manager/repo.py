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
from campaign_manager import config, coverage, window


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


class NotAutomatable(ValueError):
    """This campaign — or this rule as written — is not something the automations may run on
    this marketplace (ZC-C3: Zepto automates only product ads bid by keyword; ZC-C14: a
    Zepto bid rule must name a city or a store). A ValueError, so the API answers 400 and the
    CLI prints the sentence: the request is wrong, and retrying it will never succeed."""


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
    (tenant, platform, campaign_id) conflict, and `NotAutomatable` for a campaign this
    marketplace does not let the automations touch."""
    from sqlalchemy.exc import IntegrityError

    from app.models.campaign_manager_v2 import CmBudgetSchedule
    await require_automatable(tenant_id, platform, campaign_id)
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
    `city_id` set → the rule follows that city's frozen store; None → pinned to lat/lon.
    Raises `NotAutomatable` for an ineligible campaign, or a rule with nowhere to measure on
    a marketplace that needs one (ZC-C3, C14)."""
    from app.models.campaign_manager_v2 import CmBidRule
    from campaign_manager.marketplaces import rule_needs_location
    await require_automatable(tenant_id, platform, campaign_id)
    # Nowhere to measure, on a marketplace where the coordinate fallback is not a store
    # (ZC-C14): choose from the campaign's own targeting rather than refusing — and refuse
    # only when even that yields nothing, saying which cities we could not place.
    if (rule_needs_location(platform) and city_id is None
            and (lat is None or lon is None)):
        store, unresolved = await pick_rule_location(tenant_id, platform, campaign_id)
        if store is None:
            missing = (f" We could not match these targeted cities to ours: "
                       f"{', '.join(sorted(unresolved))}." if unresolved else "")
            raise NotAutomatable(
                f"a {platform.title()} bid rule must say where to measure, and none of "
                f"campaign {campaign_id}'s cities has a store we can read.{missing} "
                f"Name a city or a store. Nothing was created.")
        lat, lon = store.lat, store.lon
        city_id = store.city_id
        location_name = location_name or store.label
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

PRIMARY_RANK = 1    # rank 1 is a city's ANCHOR store; ranks 2..config.max_stores() validate it


class StoreSetError(ValueError):
    """A change to a city's measurement-store set that cannot be made."""


class StoreNotInCity(StoreSetError):
    """A store that cannot be a city's measurement store: unknown, inactive, without
    coordinates, or in a different city."""


@dataclass(frozen=True)
class MeasurementStore:
    """A real dark store to read positions at, and why it was chosen.

    `source`: `tenant` (the client's set) · `global` (the default set for the city) ·
    `catalog` (nothing frozen — the lowest merchant_id in the city, deterministic but
    arbitrary) · `store` (an explicitly named merchant_id) · `rule` (the store saved on the
    automation) · `default` (no store at all — the Bengaluru fallback).
    `rank` 1 is the anchor; higher ranks validate it."""
    lat: float
    lon: float
    label: str
    merchant_id: str
    city_id: int | None
    source: str
    rank: int = PRIMARY_RANK


def store_label(loc) -> str:
    """A catalog store's human name. `.strip()`: names arrive with stray whitespace
    ("Financial District\r\n")."""
    return (loc.location_name or "").strip() or f"{loc.city}/{loc.merchant_id}"


def _store_of(loc, source: str, rank: int = PRIMARY_RANK) -> MeasurementStore:
    return MeasurementStore(lat=loc.lat, lon=loc.lon, label=store_label(loc),
                            merchant_id=loc.merchant_id, city_id=loc.city_id, source=source,
                            rank=rank)


def _usable(loc) -> bool:
    return loc is not None and loc.is_active and loc.lat is not None and loc.lon is not None


def pick_city_stores(rows, tenant_id: uuid.UUID | None, max_stores: int | None = None):
    """Pure. The frozen SET of stores for ONE city, in rank order, and whose set it is.

    `rows` = `[(city_store, catalog_row | None)]` for the city, possibly spanning several
    clients. **A client's set replaces the global set whole** — never mixed rank by rank,
    which could put one store in twice, or pair a client's anchor with validators chosen for
    everyone else. The client's set is used when it has at least one usable store; otherwise
    the global set. Other clients' rows are ignored.

    A row whose store has left the catalog or gone inactive is dropped from its set rather
    than honoured, so a closing store never leaves a city measuring nowhere — the set's
    lowest remaining rank becomes the anchor. Ranks beyond `max_stores` are ignored, and a
    store listed twice keeps its lower rank.

    Returns `([(city_store, catalog_row), …], "tenant" | "global")`, or `([], None)`.
    """
    limit = max_stores or config.BID_MAX_STORES

    def _set(owner):
        seen, out = set(), []
        for cs, loc in sorted(rows, key=lambda row: row[0].rank):
            if (cs.tenant_id != owner or not 1 <= cs.rank <= limit or not _usable(loc)
                    or cs.merchant_id in seen):
                continue
            seen.add(cs.merchant_id)
            out.append((cs, loc))
        return out

    if tenant_id is not None:
        mine = _set(tenant_id)
        if mine:
            return mine, "tenant"
    everyone = _set(None)
    return (everyone, "global") if everyone else ([], None)


def pick_city_store(rows, tenant_id: uuid.UUID | None):
    """Pure. The ANCHOR of a city's frozen set: `(city_store, catalog_row, source)`, or None
    when nothing usable is frozen. See `pick_city_stores`."""
    stores, source = pick_city_stores(rows, tenant_id)
    return (stores[0][0], stores[0][1], source) if stores else None


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


async def resolve_city_ids(platform: str, names) -> dict[str, int | None]:
    """`{lowercased name: city_id | None}` for MANY marketplace city names, in one session.

    The bulk form of `resolve_city_id`: identical rules in identical order, but three
    queries for the whole list instead of three per name. A picker resolving a campaign's
    targeting calls this once — looping the single form opens a session per name, which is
    how a read path quietly turns into pool pressure.
    """
    from sqlalchemy import func
    from app.models.search import City, CityAlias, MarketplaceLocation

    keys = {(n or "").strip().lower() for n in names}
    keys.discard("")
    if not keys:
        return {}
    out: dict[str, int | None] = dict.fromkeys(keys)

    async with AsyncSessionLocal() as db:
        # 1. the platform's own alias for the name.
        for alias, cid in (await db.execute(
            select(CityAlias.alias, CityAlias.city_id).where(
                CityAlias.source == f"{platform}:ads",
                CityAlias.alias.in_(keys),
                CityAlias.is_active == True,  # noqa: E712
            )
        )).all():
            out[alias] = cid

        # 2. a canonical city name or slug.
        rest = [k for k, v in out.items() if v is None]
        if rest:
            for name, slug, cid in (await db.execute(
                select(City.name, City.slug, City.id).where(
                    (func.lower(City.name).in_(rest)) | (City.slug.in_(rest))
                )
            )).all():
                for k in ((name or "").lower(), slug):
                    if out.get(k, "miss") is None:
                        out[k] = cid

        # 3. our catalog's own city text — only when every store under it agrees on one
        #    city, exactly as the single form does. A grouped name spanning two cities
        #    (`up-ncr` is Noida AND Ghaziabad) stays unresolved rather than picking one.
        rest = [k for k, v in out.items() if v is None]
        if rest:
            by_text: dict[str, set] = {}
            for text_, cid in (await db.execute(
                select(MarketplaceLocation.city, MarketplaceLocation.city_id).where(
                    MarketplaceLocation.mp_slug == platform,
                    MarketplaceLocation.is_active == True,  # noqa: E712
                    func.lower(MarketplaceLocation.city).in_(rest),
                    MarketplaceLocation.city_id.is_not(None),
                ).distinct()
            )).all():
                by_text.setdefault((text_ or "").lower(), set()).add(cid)
            for k, ids in by_text.items():
                if len(ids) == 1:
                    out[k] = next(iter(ids))
    return out


async def measurable_cities(platform: str, *, tenant_id: uuid.UUID | None = None,
                            city_ids=None) -> dict:
    """`{city_id: (name, state, MeasurementStore)}` — every city we can measure position in.

    The list form of `resolve_store`, and the answer to "where may a bid rule point?". A
    city is in here only if our catalog has an active store with coordinates in it, which
    is the same test `resolve_store` applies one city at a time — so anything this offers,
    a save can resolve.

    `city_ids=None` means the whole catalog (what a PAN_INDIA campaign may choose from);
    a list narrows it to those cities (what a CITY-targeted campaign may choose from), and
    a targeted city absent from the result is one we cannot measure at.

    ⚠️ TWO queries + one, never a loop. `resolve_store` opens its own session per call, so
    calling it once per city is fine for a campaign's handful and a fan-out of a couple of
    hundred sessions for the pan-India list — the shape behind the 2026-09 pool exhaustion.

    Store choice follows the frozen `cm_city_stores` layers (tenant override, then global),
    falling back to the city's lowest merchant_id — the same order, and the same `source`
    labels, as `resolve_store`.
    """
    from sqlalchemy import func
    from app.models.search import City, MarketplaceLocation

    ids = None if city_ids is None else [c for c in city_ids if c is not None]
    if ids is not None and not ids:
        return {}

    base = (select(MarketplaceLocation).where(
        MarketplaceLocation.mp_slug == platform,
        MarketplaceLocation.is_active == True,  # noqa: E712
        MarketplaceLocation.lat.is_not(None),
        MarketplaceLocation.lon.is_not(None),
    ))

    async with AsyncSessionLocal() as db:
        # One representative store per canonical city — lowest merchant_id, matching the
        # unfrozen fallback in `resolve_store` so both paths land on the same store.
        q = (base.add_columns(City.name, City.state)
             .join(City, City.id == MarketplaceLocation.city_id)
             .order_by(MarketplaceLocation.city_id, MarketplaceLocation.merchant_id)
             .distinct(MarketplaceLocation.city_id))
        if ids is not None:
            q = q.where(MarketplaceLocation.city_id.in_(ids))
        out = {loc.city_id: (name, state, _store_of(loc, "catalog"))
               for loc, name, state in (await db.execute(q)).all()}

        # Catalog cities with no canonical row yet. Offering them keeps this list's coverage
        # identical to the store catalog's — a city we can measure in must not disappear from
        # the picker because its `cities` row has not been seeded. Keyed by catalog text,
        # which is what `resolve_store` falls back to matching on.
        if ids is None:
            orphans = (base.where(MarketplaceLocation.city_id.is_(None),
                                  func.length(func.trim(MarketplaceLocation.city)) > 0)
                       .order_by(func.lower(MarketplaceLocation.city),
                                 MarketplaceLocation.merchant_id)
                       .distinct(func.lower(MarketplaceLocation.city)))
            for loc in (await db.execute(orphans)).scalars().all():
                out[f"text:{loc.city.strip().lower()}"] = (
                    loc.city.strip().title(), loc.state, _store_of(loc, "catalog"))

        frozen = await _city_store_rows(
            db, platform, [k for k in out if isinstance(k, int)],
            [tenant_id] if tenant_id else [])

    by_city: dict[int, list] = {}
    for cs, loc in frozen:
        by_city.setdefault(cs.city_id, []).append((cs, loc))
    for city_id, rows in by_city.items():
        picked = pick_city_store(rows, tenant_id)
        if picked and city_id in out:
            name, state, _ = out[city_id]
            out[city_id] = (name, state, _store_of(picked[1], picked[2]))
    return out


FROZEN_SOURCES = ("tenant", "global")      # a store somebody chose, vs one we fell back to


def best_measurement_city(cities: dict, store_counts: dict):
    """Pick one city to measure in, from `{city_id: (name, state, store)}`. Pure.

    A city whose store was FROZEN wins — that is a deliberate choice (`cm stores`), so
    honouring it is how freezing takes over from the fallback. Otherwise the city with the
    most stores, which is the most representative place to read a position, and alphabetical
    order breaks a tie so the same campaign always lands on the same city.
    """
    return min(cities.items(),
               key=lambda kv: (kv[1][2].source not in FROZEN_SOURCES,
                               -store_counts.get(kv[0], 0), (kv[1][0] or "").lower()))


async def campaign_target_cities(tenant_id: uuid.UUID, platform: str,
                                 campaign_id: int) -> tuple[bool, list[str]]:
    """`(targets chosen cities?, the marketplace's own city names)` from the catalogue.

    The names are the ad platform's spelling ("Belgavi", "Mysuru"); `resolve_city_ids` maps
    them onto ours. False means the campaign runs everywhere it can — or that we have not
    scraped it, which is the same answer for the caller: nothing narrows the choice.
    On Zepto an excluded city is listed alongside the included ones, so it is filtered here.
    """
    cat = _catalog(platform)
    model = cat.campaigns
    mode_col, mode_val = cat.city_mode
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(getattr(model, mode_col), model.cities).where(
                model.tenant_id == tenant_id,
                model.platform == platform,
                model.campaign_id == campaign_id,
            ).limit(1)
        )).first()
    if row is None:
        return False, []
    mode, cities = row
    names = [str(c["name"]).strip() for c in (cities or [])
             if isinstance(c, dict) and c.get("name") and c.get("included", True)]
    return (str(mode or "").strip().upper() == mode_val, names)


async def pick_rule_location(tenant_id: uuid.UUID, platform: str, campaign_id: int
                             ) -> tuple[MeasurementStore | None, list[str]]:
    """Where a bid rule should measure when its author named no city (ZC-C14).

    Returns `(store, city names we could not resolve)`. The store carries its `city_id`, so
    the rule is saved BY CITY and follows that city's frozen store from then on — freezing
    one later moves the rule with no edit (ZC-C5).

    Chosen from the campaign's OWN targeting, so a rule cannot measure where the campaign
    does not run. Among those cities, in order: one with a store somebody FROZE (that is a
    deliberate choice, so it wins), then the city with the most stores (the most
    representative read, and stable), then alphabetically. A campaign that runs everywhere
    picks from every city we can measure in, by the same rule.

    None means there is nowhere to measure — every targeted city is either unknown to us or
    has no store — and the caller refuses the rule rather than guessing.
    """
    from sqlalchemy import func
    from app.models.search import MarketplaceLocation

    specific, names = await campaign_target_cities(tenant_id, platform, campaign_id)
    ids, unresolved = None, []
    if specific and names:
        resolved = await resolve_city_ids(platform, names)
        ids = {v for v in resolved.values() if v is not None}
        unresolved = [n for n in names if resolved.get(n.strip().lower()) is None]
        if not ids:
            return None, unresolved

    catalog = await measurable_cities(platform, tenant_id=tenant_id, city_ids=ids)
    numbered = {cid: v for cid, v in catalog.items() if isinstance(cid, int)}
    if not numbered:
        return None, unresolved

    async with AsyncSessionLocal() as db:
        counts = dict((await db.execute(
            select(MarketplaceLocation.city_id, func.count())
            .where(MarketplaceLocation.mp_slug == platform,
                   MarketplaceLocation.is_active == True,  # noqa: E712
                   MarketplaceLocation.city_id.in_(list(numbered)))
            .group_by(MarketplaceLocation.city_id)
        )).all())

    city_id, (name, _state, store) = best_measurement_city(numbered, counts)
    logger.info(f"cm: {platform} campaign {campaign_id} — no city on the rule, measuring in "
                f"{name} at {store.label or store.merchant_id} ({store.source})")
    return store, unresolved


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


async def city_stores_for(platform: str, tenant_id: uuid.UUID | None, city_ids, *,
                          run_id: str | None = None, dry_run: bool = False) -> dict:
    """`{city_id: [MeasurementStore, …]}` — each city's frozen store SET in rank order, for
    ONE client (its own set, else the global one; `tenant_id=None` = the global set only), in
    one query. The bid engine calls this once per run. A city with nothing usable frozen is
    absent, and the engine keeps each rule's saved store.

    A frozen store that is no longer an active catalog store is warned about: it silently
    changes where automations measure. Pass `run_id` so the warning lands in that run's log
    alongside the decisions it affects."""
    from campaign_manager import logs

    limit = config.max_stores(platform)
    async with AsyncSessionLocal() as db:
        rows = await _city_store_rows(db, platform, set(city_ids),
                                      [tenant_id] if tenant_id else [])
    by_city: dict[int, list] = {}
    for cs, loc in rows:
        by_city.setdefault(cs.city_id, []).append((cs, loc))
        if not _usable(loc):
            msg = (f"frozen store {cs.merchant_id} (rank {cs.rank}) for city {cs.city_id} is no "
                   f"longer an active catalog store — skipped, the rest of the set measures")
            if run_id:
                logs.note(run_id, msg, dry_run=dry_run, level="warning")
            else:
                logger.warning(f"cm: {platform} {msg}")
    out = {}
    for city_id, city_rows in by_city.items():
        stores, source = pick_city_stores(city_rows, tenant_id, limit)
        if stores:
            out[city_id] = [_store_of(loc, source, cs.rank) for cs, loc in stores]
    return out


async def city_names_for(platform: str, rules) -> dict:
    """`{rule.id: city name | None}` for a batch of bid rules, in ONE session.

    "Measured at Block C" does not say where Block C is, and store labels are sub-city names
    that repeat across the country. The city is already implied by the rule — this just
    fetches the word for it:

    - saved BY CITY → `city_id` names it straight from the canonical registry;
    - pinned to a STORE → no `city_id` (that is what pinning means), so the city comes from
      the catalog row its coordinates name — the same row `location_name` came from.

    Two queries for any number of rules. A list endpoint calls this once.
    """
    from sqlalchemy import tuple_
    from app.models.search import City, MarketplaceLocation

    ids = {r.city_id for r in rules if r.city_id is not None}
    coords = {(r.lat, r.lon) for r in rules
              if r.city_id is None and r.lat is not None and r.lon is not None}
    if not ids and not coords:
        return {}

    by_id, by_coord = {}, {}
    async with AsyncSessionLocal() as db:
        if ids:
            by_id = dict((await db.execute(
                select(City.id, City.name).where(City.id.in_(ids))
            )).all())
        if coords:
            for lat, lon, text_, canonical in (await db.execute(
                select(MarketplaceLocation.lat, MarketplaceLocation.lon,
                       MarketplaceLocation.city, City.name)
                .join(City, City.id == MarketplaceLocation.city_id, isouter=True)
                .where(MarketplaceLocation.mp_slug == platform,
                       tuple_(MarketplaceLocation.lat, MarketplaceLocation.lon).in_(coords))
            )).all():
                by_coord[(lat, lon)] = canonical or (text_ or "").strip().title() or None

    return {r.id: (by_id.get(r.city_id) if r.city_id is not None
                   else by_coord.get((r.lat, r.lon)))
            for r in rules}


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
                         tenant_id: uuid.UUID | None,
                         rank: int = PRIMARY_RANK) -> tuple[MeasurementStore, int]:
    """Freeze `merchant_id` at `rank` in `city_id`'s store set — for one client, or with
    `tenant_id=None` in the GLOBAL set every client without its own set uses. Rank 1 is the
    anchor; ranks 2..`config.max_stores` validate it.

    Refuses a rank outside that range, a store already in this set at another rank, and a
    store that is unknown, inactive, has no coordinates, or sits in a different city: an
    automation for Bengaluru must never quietly measure in Mysuru.

    Returns (the store, how many automations were reset onto the changed set). Setting the
    store a rank already holds changes nothing and resets nothing."""
    from app.models.campaign_manager_v2 import CmCityStore
    from app.models.search import City, MarketplaceLocation

    limit = config.max_stores(platform)
    if not 1 <= rank <= limit:
        raise StoreSetError(f"rank must be between 1 and {limit} on {platform}, got {rank}")

    async with AsyncSessionLocal() as db:
        loc = (await db.execute(select(MarketplaceLocation).where(
            MarketplaceLocation.mp_slug == platform,
            MarketplaceLocation.merchant_id == merchant_id,
        ))).scalars().first()
        if not _usable(loc):
            raise StoreNotInCity(f"{merchant_id!r} is not an active {platform} store with "
                                 f"coordinates in the catalog")
        store = _store_of(loc, "global" if tenant_id is None else "tenant", rank)
        if loc.city_id != city_id:
            wanted = await db.get(City, city_id)
            actual = await db.get(City, loc.city_id) if loc.city_id is not None else None
            raise StoreNotInCity(
                f"store {merchant_id} ({store.label}) is in "
                f"{actual.name if actual else 'no registered city'}, not "
                f"{wanted.name if wanted else f'city {city_id}'}")
        scope = (CmCityStore.tenant_id.is_(None) if tenant_id is None
                 else CmCityStore.tenant_id == tenant_id)
        current = (await db.execute(select(CmCityStore).where(
            CmCityStore.platform == platform, CmCityStore.city_id == city_id, scope,
        ))).scalars().all()
        clash = next((r for r in current if r.merchant_id == merchant_id and r.rank != rank), None)
        if clash:
            raise StoreSetError(f"store {merchant_id} ({store.label}) is already rank "
                                f"{clash.rank} in this set — clear that rank first")
        row = next((r for r in current if r.rank == rank), None)
        if row and row.merchant_id == merchant_id:
            return store, 0
        if row:
            row.merchant_id, row.updated_at = merchant_id, now_ist()
        else:
            db.add(CmCityStore(tenant_id=tenant_id, platform=platform, city_id=city_id,
                               merchant_id=merchant_id, rank=rank))
        await db.commit()
        moved = await _repoint_rules(db, platform, city_id, tenant_id)
    return store, moved


async def clear_city_store(platform: str, city_id: int, *, tenant_id: uuid.UUID | None,
                           rank: int | None = None) -> tuple[int, int]:
    """Remove stores from a city's set — one rank, or with `rank=None` the whole set.

    Clearing a client's whole set moves its automations to the global set, if one exists.
    Clearing the global set leaves automations with no set of their own at the store they
    were last saved at: nothing is re-pointed, but they stop being validated elsewhere.

    Returns (stores removed, how many automations were reset onto the changed set)."""
    from app.models.campaign_manager_v2 import CmCityStore

    async with AsyncSessionLocal() as db:
        scope = (CmCityStore.tenant_id.is_(None) if tenant_id is None
                 else CmCityStore.tenant_id == tenant_id)
        q = select(CmCityStore).where(CmCityStore.platform == platform,
                                      CmCityStore.city_id == city_id, scope)
        if rank is not None:
            q = q.where(CmCityStore.rank == rank)
        rows = (await db.execute(q)).scalars().all()
        if not rows:
            return 0, 0
        for row in rows:
            await db.delete(row)
        await db.commit()
        return len(rows), await _repoint_rules(db, platform, city_id, tenant_id)


async def _repoint_rules(db, platform: str, city_id: int,
                         changed_scope: uuid.UUID | None) -> int:
    """Bring saved automations in line with their city's store set after it changes.

    The engine resolves the set on every run anyway (`bid.measurement_stores`), so this is
    not what moves the MEASUREMENT. It keeps the rule row's snapshot on the set's anchor for
    everything that reads it (the automations list, the CLI), and clears what the engine
    learned under the OLD set: a different anchor reads different positions, and different
    validators change which store is worst — so the last position, holding price, relaxed
    target and raise step would each feed the next decision a fact about another set. Same
    reason Resume clears them (`_RUNTIME_MEMORY`, with `updated_at` deliberately kept).

    Only rules that FOLLOW the city (`city_id` set) are touched; pinned ones never are.
    `changed_scope` is whose set changed: one client's (only its rules), or None for the
    global set (every client whose OWN set is not in force). A rule left with no set keeps
    its saved store, but its memory is still cleared: it has stopped being validated."""
    from app.models.campaign_manager_v2 import CmBidRule, CmBidRuntime

    q = select(CmBidRule).where(CmBidRule.platform == platform, CmBidRule.city_id == city_id)
    if changed_scope is not None:
        q = q.where(CmBidRule.tenant_id == changed_scope)
    rules = (await db.execute(q)).scalars().all()
    if not rules:
        return 0
    rows = await _city_store_rows(db, platform, [city_id])
    limit = config.max_stores(platform)
    moved = 0
    for r in rules:
        stores, source = pick_city_stores(rows, r.tenant_id, limit)
        if changed_scope is None and source == "tenant":
            continue                          # this client's own set is untouched
        if stores:
            anchor = _store_of(stores[0][1], source, stores[0][0].rank)
            r.lat, r.lon, r.location_name = anchor.lat, anchor.lon, anchor.label
        rt = await db.get(CmBidRuntime, r.id)
        if rt:
            for field in _RUNTIME_MEMORY:
                setattr(rt, field, None)
        moved += 1
    await db.commit()
    return moved


# ── Stock per measurement store + per-store bid readings ─────────────────────

async def store_ids_at(platform: str, coords) -> dict:
    """`{(lat, lon): merchant_id}` — the catalog store behind saved coordinates, for rules
    that measure at their own saved store (pinned, or a city with nothing frozen). Stock is
    keyed by store and the rule row only carries coordinates. One query."""
    from sqlalchemy import tuple_
    from app.models.search import MarketplaceLocation

    wanted = {(float(a), float(b)) for a, b in coords if a is not None and b is not None}
    if not wanted:
        return {}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(MarketplaceLocation.lat, MarketplaceLocation.lon, MarketplaceLocation.merchant_id)
            .where(MarketplaceLocation.mp_slug == platform,
                   tuple_(MarketplaceLocation.lat, MarketplaceLocation.lon).in_(wanted))
            .order_by(MarketplaceLocation.merchant_id)
        )).all()
    out: dict = {}
    for lat, lon, merchant_id in rows:
        out.setdefault((lat, lon), merchant_id)
    return out


async def get_own_brands(tenant_id: uuid.UUID) -> list[tuple[str, int, set[str]]]:
    """`[(search query, cap, brand names)]` for each own brand a client tracks — what a stock
    check searches for. The query is the targeted scrape's (first alias, else the de-slugged
    brand slug); the cap is the watchlist's `brand_cap`, else `CM_STOCK_DEFAULT_BRAND_CAP`;
    the names are what a product's `brand` field may say."""
    from app.models.tenant import TenantWatchlist

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(TenantWatchlist).where(
            TenantWatchlist.tenant_id == tenant_id,
            TenantWatchlist.relationship == "own",
        ))).scalars().all()
    out = []
    for w in rows:
        slug_name = w.brand_slug.replace("-", " ")
        aliases = [a for a in (w.aliases or []) if a and a.strip()]
        out.append((aliases[0] if aliases else slug_name,
                    int(w.brand_cap or config.STOCK_DEFAULT_BRAND_CAP),
                    {slug_name, *aliases}))
    return out


async def get_store_stock(tenant_id: uuid.UUID, platform: str,
                          merchant_ids) -> dict[str, coverage.StoreStock]:
    """`{merchant_id: StoreStock}` from the cache, whatever its age — freshness is the
    caller's call (campaign_manager/stock.py)."""
    from app.models.campaign_manager_v2 import CmStoreStock

    ids = [m for m in merchant_ids if m]
    if not ids:
        return {}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(CmStoreStock).where(
            CmStoreStock.tenant_id == tenant_id,
            CmStoreStock.platform == platform,
            CmStoreStock.merchant_id.in_(ids),
        ))).scalars().all()
    return {r.merchant_id: coverage.StoreStock(
                complete=bool(r.complete),
                in_stock={str(p["pid"]): bool(p.get("in_stock"))
                          for p in (r.products or []) if p.get("pid")},
                checked_at=r.checked_at)
            for r in rows}


async def upsert_store_stock(tenant_id: uuid.UUID, platform: str, rows: list[dict]) -> None:
    """Replace the cached stock for these stores. Never raises: a cache that could not be
    written only means the next run reads the store again."""
    if not rows:
        return
    from sqlalchemy.dialects.postgresql import insert
    from app.models.campaign_manager_v2 import CmStoreStock

    stmt = insert(CmStoreStock).values(
        [{"tenant_id": tenant_id, "platform": platform, **r} for r in rows])
    stmt = stmt.on_conflict_do_update(
        constraint="uq_cm_store_stock",
        set_={"served_by": stmt.excluded.served_by, "complete": stmt.excluded.complete,
              "products": stmt.excluded.products, "checked_at": stmt.excluded.checked_at})
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(stmt)
            await db.commit()
    except Exception as e:
        logger.error(f"cm: could not cache store stock — {e}")


async def list_store_stock(tenant_id: uuid.UUID, platform: str) -> list:
    """Every cached stock row for a client, newest first — for `cm stores stock`."""
    from app.models.campaign_manager_v2 import CmStoreStock

    async with AsyncSessionLocal() as db:
        return list((await db.execute(select(CmStoreStock).where(
            CmStoreStock.tenant_id == tenant_id,
            CmStoreStock.platform == platform,
        ).order_by(CmStoreStock.checked_at.desc()))).scalars().all())


async def recent_store_reads(tenant_id: uuid.UUID, platform: str, rule_ids, *,
                             since: datetime, dry_run: bool) -> dict:
    """`{(rule_id, merchant_id): [CmBidStoreRead, …]}` newest first, since `since` — what each
    rule's stores showed on recent ticks. Feeds giving up on a store that stays out of reach at
    the ceiling, and warning about one that keeps giving unusable readings.

    Only rows of the SAME mode (`dry_run`): a manual dry run must not make a live run give up,
    or the other way round."""
    from app.models.campaign_manager_v2 import CmBidStoreRead

    ids = [r for r in rule_ids if r]
    if not ids:
        return {}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(CmBidStoreRead).where(
            CmBidStoreRead.tenant_id == tenant_id,
            CmBidStoreRead.platform == platform,
            CmBidStoreRead.rule_id.in_(ids),
            CmBidStoreRead.observed_at >= since,
            CmBidStoreRead.dry_run == dry_run,
        ).order_by(CmBidStoreRead.observed_at.desc()))).scalars().all()
    out: dict = {}
    for r in rows:
        out.setdefault((r.rule_id, r.merchant_id), []).append(r)
    return out


async def write_store_reads(rows: list[dict]) -> None:
    """Append a run's per-store readings and trim what has aged past
    `CM_STORE_READS_RETENTION_DAYS` for the clients written. Never raises: the bids these
    rows explain have already gone out, and a missing audit row must not fail the run."""
    if not rows:
        return
    from sqlalchemy import delete
    from app.models.campaign_manager_v2 import CmBidStoreRead

    cutoff = now_ist() - timedelta(days=config.STORE_READS_RETENTION_DAYS)
    try:
        async with AsyncSessionLocal() as db:
            db.add_all([CmBidStoreRead(**r) for r in rows])
            for tenant in {r["tenant_id"] for r in rows}:
                await db.execute(delete(CmBidStoreRead).where(
                    CmBidStoreRead.tenant_id == tenant,
                    CmBidStoreRead.observed_at < cutoff))
            await db.commit()
    except Exception as e:
        logger.error(f"cm: could not record per-store bid readings — {e}")


# ── The campaign CATALOGUE, per marketplace ─────────────────────────────────
#
# Each marketplace keeps its campaigns' CURRENT configuration in its own pair of tables —
# Blinkit's `blinkit_ad_campaigns` / `_keywords`, Zepto's `zepto_ad_campaigns` / `_keywords`
# (ZC-B2/B3) — with different column names for the same facts. Every reader below picks
# its tables here, from ONE mapping, never from an `if platform ==` chain at the call site.

@dataclass(frozen=True)
class _Catalog:
    campaigns: object          # the campaign model
    keywords: object           # the (campaign, keyword, match_type) model
    name_col: str              # the campaign-name column
    floor_col: str             # the keyword's published minimum-bid column
    # (campaign-type column, bidding-mode column) for the eligibility check (ZC-C3), or None
    # on a marketplace that does not limit which campaigns may be automated.
    type_cols: tuple[str, str] | None = None
    # How the row says "this campaign targets chosen cities": (column, value). Anything else
    # in that column means it runs everywhere. The cities themselves are `cities`, a list of
    # {id, name} in the MARKETPLACE's spelling (ZC-C4 resolves them to `cities.id`).
    city_mode: tuple[str, str] = ("region_type", "CITY")


def _catalog(platform: str) -> _Catalog:
    if platform == "zepto":
        from app.models.zepto_seller import ZeptoAdCampaign, ZeptoAdCampaignKeyword
        return _Catalog(ZeptoAdCampaign, ZeptoAdCampaignKeyword, "campaign_name", "min_bid",
                        ("campaign_type", "bid_targeting_type"),
                        city_mode=("city_targeting", "MANUAL"))
    from app.models.blinkit_marketing import BlinkitAdCampaign, BlinkitAdCampaignKeyword
    return _Catalog(BlinkitAdCampaign, BlinkitAdCampaignKeyword, "name", "min_bid")


async def require_automatable(tenant_id: uuid.UUID, platform: str, campaign_id: int) -> None:
    """Raise `NotAutomatable` when the catalogue says this campaign is not one the
    automations may touch (ZC-C3). A campaign the catalogue has not seen is allowed — one
    created since the last scrape is a normal state — and the write-time check on the fresh
    read (the adapter) still stands behind it."""
    from campaign_manager.marketplaces import automation_refusal

    cat = _catalog(platform)
    if cat.type_cols is None:
        return
    model = cat.campaigns
    type_col, bidding_col = cat.type_cols
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(getattr(model, type_col), getattr(model, bidding_col)).where(
                model.tenant_id == tenant_id,
                model.campaign_id == campaign_id,
            ).limit(1)
        )).first()
    if row is None:
        return
    refused = automation_refusal(platform, row[0], row[1])
    if refused:
        raise NotAutomatable(f"campaign {campaign_id} cannot be automated: {refused}. "
                             "Nothing was created.")


async def catalog_cutoff(tenant_id: uuid.UUID, platform: str = "blinkit"):
    """`scraped_at` a campaign must reach to count as part of the CURRENT account (ZC-B8).

    Every catalogue write upserts what the marketplace returned, so a campaign that stops
    coming back (deleted, or on an account the client left) keeps its last `scraped_at`
    forever. Within 2 h of the newest write = returned by the latest scrape or Refresh.
    Same rule as `ads_service._recent_campaign_cutoff` (Blinkit). None when there is none.
    """
    from sqlalchemy import func

    model = _catalog(platform).campaigns
    async with AsyncSessionLocal() as db:
        latest = (await db.execute(
            select(func.max(model.scraped_at)).where(model.tenant_id == tenant_id)
        )).scalar()
    return latest - timedelta(hours=2) if latest else None


async def campaign_marketplaces(tenant_id: uuid.UUID, campaign_id: int) -> set[str]:
    """Every marketplace whose catalogue knows this campaign id for this client.

    The automation API is pinned to one marketplace, but the campaign lists it is fed from
    merge Blinkit and Zepto — and the two id spaces are separate. This is what lets a write
    surface refuse a campaign that belongs to the OTHER marketplace instead of filing it
    under its own and sending the id to the wrong ad account.

    Empty means "no catalogue has seen it", which is a normal state (a campaign created
    since the last scrape) and is the caller's to allow — not a refusal.
    """
    from app.models.blinkit_marketing import BlinkitAdCampaign
    from app.models.zepto_seller import ZeptoAdCampaign, ZeptoAdCampaignDaily

    async with AsyncSessionLocal() as db:
        found = set((await db.execute(
            select(BlinkitAdCampaign.platform).where(
                BlinkitAdCampaign.tenant_id == tenant_id,
                BlinkitAdCampaign.campaign_id == campaign_id,
            ).distinct()
        )).scalars().all())
        # Zepto: its catalogue, or — for a campaign scraped before the catalogue existed —
        # its daily metrics table.
        zepto = None
        for model in (ZeptoAdCampaign, ZeptoAdCampaignDaily):
            zepto = zepto or (await db.execute(
                select(model.id).where(model.tenant_id == tenant_id,
                                       model.campaign_id == campaign_id).limit(1)
            )).scalars().first()
    if zepto is not None:
        found.add("zepto")
    return {p for p in found if p}


async def campaign_name(tenant_id: uuid.UUID, campaign_id: int,
                        platform: str = "blinkit") -> str | None:
    """A campaign's name from the catalogue, for a History row whose writer never read it.

    `set_budget` reads only the budget, so its rows went into `cm_run_log` nameless and the
    Execution logs showed "—" for every one-off change. Best-effort: None when the campaign
    has not been scraped yet, or on any error — a nameless row beats a failed run.
    """
    try:
        cat = _catalog(platform)
        model = cat.campaigns
        async with AsyncSessionLocal() as db:
            return (await db.execute(
                select(getattr(model, cat.name_col)).where(
                    model.tenant_id == tenant_id,
                    model.platform == platform,
                    model.campaign_id == campaign_id,
                ).limit(1)
            )).scalar()
    except Exception:
        return None


async def get_bid_context(tenant_id: uuid.UUID, campaign_id: int, platform: str = "blinkit"):
    """What the bid-rule form needs to know about a campaign, from the DAILY SCRAPE (V7.4).

    Returns (campaign_row, keyword_rows) or (None, []) when the campaign has never been
    scraped with V7 in place — the caller then falls back to today's behaviour rather than
    blocking, because a campaign created since the last scrape is a normal state, not an
    error.

    Reads only scraped tables, never the marketplace: this is served by the API on Render,
    which has no browser (D2). The authoritative floor check happens at WRITE time on the VM.

    Returns the marketplace's OWN row types (their columns differ — see `_catalog`); the
    service shapes them for the API. On Zepto the keyword rows include negatives
    (`is_negative`), which are not bid targets.
    """
    cat = _catalog(platform)
    cm, km = cat.campaigns, cat.keywords
    async with AsyncSessionLocal() as db:
        campaign = (await db.execute(
            select(cm).where(
                cm.tenant_id == tenant_id,
                cm.platform == platform,
                cm.campaign_id == campaign_id,
            )
        )).scalars().first()
        keywords = (await db.execute(
            select(km).where(
                km.tenant_id == tenant_id,
                km.platform == platform,
                km.campaign_id == campaign_id,
            ).order_by(km.keyword, km.match_type)
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

    cat = _catalog(platform)
    km = cat.keywords
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(getattr(km, cat.floor_col)).where(
                km.tenant_id == tenant_id,
                km.platform == platform,
                km.campaign_id == campaign_id,
                func.lower(km.keyword) == (keyword or "").strip().lower(),
                km.match_type == (match_type or "EXACT").upper(),
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
                       run_id: str | None = None, include_unchanged: bool = False,
                       keyword: str | None = None, success: bool | None = None):
    """Recent cm_run_log rows for a tenant (newest first) + total count.

    Defaults to CHANGES ONLY. Pass `include_unchanged=True` for the full per-tick record —
    that is the per-automation drill-down, where "we held, and here is why" is the answer
    being looked for. `campaign_id` / `rule_id` narrow it to one campaign or automation.

    `kind` takes a comma-separated list ("budget,activation"): a campaign automation's own
    record is its budget changes AND the starts/stops it made, without the bid ticks of
    every keyword automation on the same campaign, which outnumber them ~50:1.

    `keyword` (with `campaign_id`) is how ONE keyword automation's record is asked for,
    rather than `rule_id`: a Delete + reset writes its row after the rule is gone, with no
    rule id, and rows from before 2026-09-04 carry none either — both belong to the keyword.

    `success` filters on whether the row did what it meant to (a refused or failed write is
    False). Server-side, so a "Failed" filter pages through ALL of them, not one page's worth.

    `run_id` narrows it to ONE RUN — every row a single job wrote, and nothing else. That is
    the filter that answers "did the thing I just asked for actually happen", because a
    finished job only reports that the process exited: the CM commands never set a non-zero
    exit code, so a refused write settles exactly like an accepted one. Matching on the
    campaign instead would race the parallel `cm_bid` / `cm_ops` lanes and could not
    describe a run spanning many campaigns at all.
    """
    from sqlalchemy import func
    from app.models.campaign_manager_v2 import CmRunLog

    async with AsyncSessionLocal() as db:
        base = select(CmRunLog).where(CmRunLog.tenant_id == tenant_id,
                                      CmRunLog.platform == platform)
        kinds = [k.strip() for k in (kind or "").split(",") if k.strip()]
        if kinds:
            base = base.where(CmRunLog.kind.in_(kinds))
        if campaign_id is not None:
            base = base.where(CmRunLog.campaign_id == campaign_id)
        if rule_id is not None:
            base = base.where(CmRunLog.rule_id == rule_id)
        if keyword is not None:
            base = base.where(CmRunLog.keyword == keyword)
        if run_id is not None:
            base = base.where(CmRunLog.run_id == run_id)
        if success is not None:
            base = base.where(CmRunLog.success == success)
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
            # Only writes that LANDED, as the docstring always said. A `reset` row is filed
            # under its write action whether or not it landed, so refused resets were being
            # counted against the limit that guards against writes actually happening.
            CmRunLog.success == True,  # noqa: E712
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
    if platform == "zepto":
        return await _upsert_zepto_catalog(tenant_id, campaigns)
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

    # ⚠️ Deliberately excludes the detail-derived columns (daily_budget / region_type /
    # cities / min_cpm / pacing_type / billed_amount / campaign_cpm, V7). This refresh reads
    # only the campaign LIST, which carries none of them, so listing them here would blank a
    # campaign's budget, city targeting and budget floor every time someone clicked Refresh.
    updatable = {"name", "type", "status", "start_ts", "end_ts",
                 "infinite_campaign", "scraped_at"}
    async with AsyncSessionLocal() as db:
        stmt = insert(BlinkitAdCampaign).values(rows).on_conflict_do_update(
            index_elements=["upsert_key"],
            set_={c: insert(BlinkitAdCampaign).excluded[c] for c in updatable},
        )
        await db.execute(stmt)
        await db.commit()
    return len(rows)


# ── Catalogue write-back (campaign_manager/writes.py) ───────────────────────
#
# The second reason the campaign manager writes outside its own cm_* tables, and it is the
# same reason as `upsert_campaign_catalog` above: a landed write changed the marketplace,
# and the catalogue is where the product reads the marketplace's state from. Before this,
# only the nightly scrape ever refreshed those columns — so a budget set at 10:00, a
# campaign paused at noon and a bid the optimizer climbed all afternoon were invisible in
# our own dashboard until 03:00 the next morning, while `cm_run_log` showed all three.
#
# What makes it safe is what it does NOT do:
#
#   * **UPDATE only, never INSERT.** A campaign created this morning has no catalogue row
#     yet, so its patch matches nothing and is dropped. Inserting one would fabricate a
#     campaign whose every other column is NULL and whose `scraped_at` is fresh — and
#     `scraped_at` is exactly what the pickers' freshness filter trusts.
#   * **Never advances `scraped_at`.** That column means "when the scrape last saw this",
#     and a write-back has not scraped anything. The nightly scrape stays the source of
#     truth and overwrites all of this with Blinkit's own answer, so a write-back that is
#     somehow wrong decays within a day instead of persisting.
#   * **Never raises.** By the time this is called the marketplace has ALREADY been mutated
#     and `cm_run_log` has already recorded it. A bookkeeping failure must not turn a
#     successful write into a failed run — the same reasoning as `_record_run_blocked`.

def _catalog_model(table: str):
    """Logical table name → model. Adapters return the name (they never import
    `app.models`); this is the one place that resolves it, so a second marketplace adds a
    line here rather than a branch in the choke point."""
    from app.models.blinkit_marketing import BlinkitAdCampaign, BlinkitAdCampaignKeyword
    from app.models.zepto_seller import ZeptoAdCampaign, ZeptoAdCampaignKeyword
    return {
        "blinkit.campaigns": BlinkitAdCampaign,
        "blinkit.keywords": BlinkitAdCampaignKeyword,
        "zepto.campaigns": ZeptoAdCampaign,
        "zepto.keywords": ZeptoAdCampaignKeyword,
    }.get(table)


async def _upsert_zepto_catalog(tenant_id: uuid.UUID, campaigns: list[dict]) -> int:
    """`cm.sync_campaigns -m zepto` — the LIST fields of `zepto_ad_campaigns`. (ZC-B5, A4)

    Through the scraper's own parser and writer, exactly as the Blinkit branch above reuses
    the marketing scraper's `parse_campaign`: one definition of a row. List fields only —
    `save_campaign_catalog` updates only the columns a row carries, so a Refresh can never
    blank the targeting, products or keywords the daily scrape stored. `scrape_job_id` is
    dropped for the same reason the Blinkit branch drops it: this run has no scrape job,
    and blanking it would destroy the scraper's lineage.

    This used to run Blinkit's parser on Zepto rows, which skipped every one (they carry
    `campaign_id`, not `id`) and reported success with 0 campaigns (ZC-A4).
    """
    from scraper.platforms.zepto.dashboard_data.seller.parser import parse_catalog_list_row
    from scraper.platforms.zepto.dashboard_data.seller.storage import save_campaign_catalog

    rows = []
    for raw in campaigns:
        if raw.get("campaign_id") is None:
            continue
        row = parse_catalog_list_row(raw, str(tenant_id), None)
        row.pop("scrape_job_id")
        rows.append(row)
    if not rows:
        return 0
    async with AsyncSessionLocal() as db:
        written = await save_campaign_catalog(db, [], rows, {})
    return written["campaigns"]


def merge_patches(patches: list[dict]) -> list[dict]:
    """Collapse a run's patches to one per row, later values winning. Pure — unit-tested.

    A single campaign can collect several in one run: the budget engine reverts a budget
    and then stops the campaign, and a Blinkit restart produces a status and a budget at
    once. Left alone those are three UPDATEs on one row; merged they are one. It also
    fixes the ordering hazard — two patches touching the same column would otherwise race
    on statement order, and here the last write plainly wins.
    """
    merged: dict[tuple, dict] = {}
    for p in patches:
        # ⚠️ An EMPTY key is dropped, not treated as "match anything". `record_applied`
        # scopes every statement by tenant and platform and then ANDs the key on top, so a
        # keyless patch would widen into "UPDATE every campaign this client owns" — a
        # bookkeeping bug turning into a data-loss incident. A patch must name its row.
        if not p or not p.get("set") or not p.get("table") or not p.get("key"):
            continue
        key = (p["table"], tuple(sorted(p["key"].items(), key=lambda kv: kv[0])))
        if key in merged:
            merged[key]["set"].update(p["set"])
        else:
            merged[key] = {"table": p["table"], "key": dict(p["key"]),
                           "set": dict(p["set"])}
    return list(merged.values())


async def record_applied(tenant_id: uuid.UUID, platform: str,
                         patches: list[dict]) -> int:
    """Mirror landed marketplace writes into the catalogue. Returns rows actually patched.

    `patches` is what the adapters' `catalog_patch` produced over a whole run, flushed once
    beside `write_run_log` rather than per write — a bid run can apply a write per keyword
    per tick, and opening a session for each would put real pressure on a pool that has
    been exhausted before. One session, one statement per distinct row, no-op on empty.
    """
    from sqlalchemy import func, update

    patched = 0
    try:
        # Inside the try, with everything else: the whole point of this function is that
        # bookkeeping cannot break the write it describes, and a malformed patch is exactly
        # the kind of upstream bug that would otherwise escape from the merge.
        patches = merge_patches(patches or [])
        if not patches:
            return 0
        async with AsyncSessionLocal() as db:
            for p in patches:
                model = _catalog_model(p["table"])
                if model is None:
                    logger.warning(f"[cm] no catalogue model for {p['table']!r} — "
                                   f"{p['set']} not written back")
                    continue
                conds = [model.tenant_id == tenant_id, model.platform == platform]
                for col, val in p["key"].items():
                    # Keywords are matched case-insensitively, the way `get_keyword_floor`
                    # already does it: the scrape stores whatever Blinkit returned and a
                    # rule stores whatever someone typed, and a case difference must not
                    # silently patch nothing.
                    if col == "keyword":
                        conds.append(func.lower(model.keyword) ==
                                     (val or "").strip().lower())
                    else:
                        conds.append(getattr(model, col) == val)
                result = await db.execute(update(model).where(*conds).values(**p["set"]))
                if result.rowcount:
                    patched += result.rowcount
                else:
                    # Not an error: a campaign or keyword created since the last sync has
                    # no row to patch. Worth saying once, because it also means the UI will
                    # keep showing nothing for it until a scrape or a catalogue refresh.
                    logger.debug(f"[cm] nothing to write back for {p['key']} in "
                                 f"{p['table']} — not in the catalogue yet")
            await db.commit()
    except Exception as e:
        logger.warning(f"[cm] catalogue write-back failed ({e}) — the marketplace change "
                       f"itself landed and is recorded in cm_run_log; the catalogue stays "
                       f"stale until the next scrape")
        return 0
    return patched


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
