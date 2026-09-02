"""Request/response contracts for the Campaign Manager v2 API (V4.3)."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

_orm = ConfigDict(from_attributes=True)


# ── Budget schedules + rules ────────────────────────────────────────────────

class BudgetRuleIn(BaseModel):
    budget: float
    type: str = "recurring"                 # "recurring" | "once"
    days: list[str] = []
    start_time: str | None = None
    end_time: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    date: str | None = None                 # for a "once" rule


class BudgetRuleOut(BaseModel):
    model_config = _orm
    id: int
    budget: float
    type: str
    days: list[str] = []
    start_time: str | None = None
    end_time: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    date: str | None = None
    status: str = "scheduled"           # running | scheduled | ended (computed per window)


class BudgetRuleUpdate(BaseModel):
    """Partial edit of a budget rule — only the fields sent are changed."""
    budget: float | None = None
    type: str | None = None
    days: list[str] | None = None
    start_time: str | None = None
    end_time: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    date: str | None = None


class BudgetScheduleIn(BaseModel):
    campaign_id: int
    campaign_name: str | None = None
    name: str | None = None
    default_budget: float
    # Also stop the campaign when a window ends (docs/campaign-manager.md). Starting
    # is unconditional either way — this only governs the stop.
    stop_after_window: bool = False
    rule: BudgetRuleIn | None = None        # optional inline first rule


class BudgetScheduleOut(BaseModel):
    model_config = _orm
    id: int
    campaign_id: int
    campaign_name: str
    name: str | None = None
    default_budget: float
    stop_after_window: bool = False
    state: str
    status: str = "scheduled"           # running | scheduled | ended | stopped (computed)
    platform: str
    rules: list[BudgetRuleOut] = []


class BudgetScheduleUpdate(BaseModel):
    """Partial edit of a budget schedule (its own fields; rules are edited separately)."""
    name: str | None = None
    default_budget: float | None = None
    stop_after_window: bool | None = None


# ── Bid rules ───────────────────────────────────────────────────────────────

class BidRuleIn(BaseModel):
    campaign_id: int
    campaign_name: str | None = None
    keyword: str
    target_position: int
    min_bid: int
    # Optional — omit for "reach the target whatever it costs". The engine still applies
    # the absolute backstop (`CM_BID_MAX_ABSOLUTE`), so this is never truly unbounded.
    max_bid: int | None = None
    match_type: str = "EXACT"
    type: str = "recurring"
    date: str | None = None
    days: list[str] = []
    start_time: str | None = None
    stop_time: str | None = None
    start_date: str | None = None
    stop_date: str | None = None
    lat: float | None = None
    lon: float | None = None
    city: str | None = None                 # resolved to a store's lat/lon if lat/lon omitted
    location_id: str | None = None          # a specific store (merchant_id)
    location_name: str | None = None
    brand_name: str | None = None


class BidRuleOut(BaseModel):
    model_config = _orm
    id: str
    campaign_id: int
    campaign_name: str
    keyword: str
    target_position: int
    min_bid: int
    max_bid: int | None = None          # None = no ceiling set; the absolute backstop applies
    match_type: str
    type: str
    date: str | None = None
    days: list[str] = []
    start_time: str | None = None
    stop_time: str | None = None
    start_date: str | None = None
    stop_date: str | None = None
    lat: float | None = None
    lon: float | None = None
    location_name: str | None = None
    state: str
    status: str = "scheduled"           # running | scheduled | ended | paused | stopped (computed)
    platform: str


class BidRuleUpdate(BaseModel):
    """Partial edit of a bid rule — only the fields sent are changed. `city`/`location_id`
    re-resolve the measurement lat/lon (like create); campaign is NOT editable (identity)."""
    keyword: str | None = None
    target_position: int | None = None
    min_bid: int | None = None
    max_bid: int | None = None
    match_type: str | None = None
    type: str | None = None
    date: str | None = None
    days: list[str] | None = None
    start_time: str | None = None
    stop_time: str | None = None
    start_date: str | None = None
    stop_date: str | None = None
    city: str | None = None
    location_id: str | None = None


# ── Bid context (V7.4) ──────────────────────────────────────────────────────
#
# What the bid-rule form needs to know about a campaign before someone fills it in: the
# minimum bid Blinkit publishes per keyword, and which cities the campaign actually targets.
# Everything here comes from the DAILY SCRAPE — the API has no browser, so it cannot ask
# Blinkit. `scraped_at` is therefore part of the contract, not decoration: the UI says how
# fresh this is, and an unscraped campaign returns `scraped_at: null` so the form can fall
# back instead of showing a confident wrong number.


class KeywordBidRange(BaseModel):
    keyword: str
    match_type: str
    current_cpm: int | None = None
    # Blinkit's published floor. None = we have not scraped this keyword (a keyword the
    # campaign does not carry yet), which means "no opinion" — never "no floor".
    min_bid: int | None = None
    max_bid: int | None = None
    suggested_min: int | None = None
    suggested_max: int | None = None
    keyword_searches: int | None = None


class TargetedCity(BaseModel):
    id: int
    name: str
    # The dark store a rule measuring in this city would use, or None when our catalog has
    # no store there — the form then asks the user to pick one rather than blocking.
    location_name: str | None = None
    lat: float | None = None
    lon: float | None = None


class BidContextOut(BaseModel):
    campaign_id: int
    campaign_type: str | None = None
    scraped_at: datetime | None = None
    # PAN_INDIA → the city picker stays free; CITY → offer `cities`, auto-filling when one.
    region_type: str | None = None
    cities: list[TargetedCity] = []
    keywords: list[KeywordBidRange] = []
    # Budget facts, for display. We deliberately do NOT enforce a minimum budget locally —
    # Blinkit publishes no such field and its dashboard derives one in the browser, so the
    # marketplace stays the judge (decided 2026-08-27).
    daily_budget: int | None = None
    pacing_type: str | None = None
    billed_amount: float | None = None


# ── Actions ─────────────────────────────────────────────────────────────────

class SetBudgetIn(BaseModel):
    campaign_id: int
    budget: float


class SetActivationIn(BaseModel):
    """Start or stop one campaign now.

    `budget` applies to `running` only — Blinkit's restart re-submits the campaign and
    sets its budget, so a resume always sends one. Omit it to reuse whatever the campaign
    is currently on (resolved on the VM against a fresh read, never guessed here).
    """
    status: Literal["running", "paused"]
    budget: float | None = None


class AdvertiserIn(BaseModel):
    advertiser_id: int


class AdvertiserOut(BaseModel):
    advertiser_id: int | None = None


class EnqueuedOut(BaseModel):
    """Returned by an enqueue endpoint — the UI polls the job by id."""
    job_id: uuid.UUID
    status: str = "pending"


class CmJobOut(BaseModel):
    model_config = _orm
    id: uuid.UUID
    job_type: str
    status: str
    error: str | None = None
    exit_code: int | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RunLogOut(BaseModel):
    model_config = _orm
    id: int
    kind: str
    campaign_id: int | None = None
    campaign_name: str | None = None
    keyword: str | None = None
    action: str
    old_value: float | None = None
    new_value: float | None = None
    reason: str | None = None
    dry_run: bool
    success: bool
    timestamp: datetime
