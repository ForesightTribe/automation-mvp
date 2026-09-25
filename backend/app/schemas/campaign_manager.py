"""Request/response contracts for the Campaign Manager v2 API (V4.3)."""
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict

from campaign_manager import window

_orm = ConfigDict(from_attributes=True)


# ── Time and date formats ───────────────────────────────────────────────────
#
# Rule windows are compared as STRINGS (`campaign_manager.window.in_window`), which is only
# correct for zero-padded 24-hour `HH:MM` and `YYYY-MM-DD`. Until 2026-09-10 nothing here
# enforced that, so a hand-written "9:00" saved fine and then matched at the wrong times.
#
# INPUT models only. The `*Out` models stay permissive, so a row that predates this check
# can still be listed, shown and corrected rather than breaking the page it is on. `None`
# stays allowed everywhere: the dashboard clears a field by sending null.

def _time(v: str | None) -> str | None:
    if v is not None and not window.valid_hhmm(v):
        raise ValueError(f"{v!r} is not a time — use 24-hour HH:MM, e.g. 09:00 or 23:30")
    return v


def _date(v: str | None) -> str | None:
    if v is not None and not window.valid_date(v):
        raise ValueError(f"{v!r} is not a date — use YYYY-MM-DD, e.g. 2026-09-10")
    return v


Time = Annotated[str | None, AfterValidator(_time)]
Date = Annotated[str | None, AfterValidator(_date)]


# ── Budget schedules + rules ────────────────────────────────────────────────

class BudgetRuleIn(BaseModel):
    budget: float
    type: str = "recurring"                 # "recurring" | "once"
    days: list[str] = []
    start_time: Time = None
    end_time: Time = None
    start_date: Date = None
    end_date: Date = None
    date: Date = None                       # for a "once" rule


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
    start_time: Time = None
    end_time: Time = None
    start_date: Date = None
    end_date: Date = None
    date: Date = None


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
    # When the last window closed, and when its final teardown landed (lifecycle.py). The
    # label above is computed live; these are what the reconciler has recorded.
    ended_at: datetime | None = None
    settled_at: datetime | None = None


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
    date: Date = None
    days: list[str] = []
    start_time: Time = None
    stop_time: Time = None
    start_date: Date = None
    stop_date: Date = None
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
    # The city `location_name` is IN. Store labels are sub-city names ("Block C") that repeat
    # across the country, so the label alone does not say where position is measured. Derived
    # for display — from `city_id` when the rule was saved by city, from the pinned store's
    # catalog row otherwise. None when neither resolves; the UI then shows the label alone.
    city_name: str | None = None
    state: str
    status: str = "scheduled"           # running | scheduled | ended | paused (computed)
    platform: str
    # When the last window closed, and when its final teardown landed (lifecycle.py).
    ended_at: datetime | None = None
    settled_at: datetime | None = None


class BidRuleUpdate(BaseModel):
    """Partial edit of a bid rule — only the fields sent are changed. `city`/`location_id`
    re-resolve the measurement lat/lon (like create); campaign is NOT editable (identity)."""
    keyword: str | None = None
    target_position: int | None = None
    min_bid: int | None = None
    max_bid: int | None = None
    match_type: str | None = None
    type: str | None = None
    date: Date = None
    days: list[str] | None = None
    start_time: Time = None
    stop_time: Time = None
    start_date: Date = None
    stop_date: Date = None
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
    # A stable render key, NOT a foreign key: the canonical `cities.id` where we could
    # resolve one, else the marketplace's own region id, else None for a catalog city with
    # no canonical row. Nothing keys data off it — rules are saved by `name`.
    id: int | None = None
    # Canonical spelling where we have one, so the picker reads consistently no matter which
    # vocabulary the name arrived in (Blinkit's ads surface says `Gurugram`, our catalog says
    # `hr-ncr`). This is the string a rule is saved with; `resolve_store` resolves it back.
    name: str
    state: str | None = None
    # The dark store a rule measuring in this city would use, or None when our catalog has
    # no store there — the form then asks the user to pick one rather than blocking.
    location_name: str | None = None
    lat: float | None = None
    lon: float | None = None


class BidContextOut(BaseModel):
    campaign_id: int
    campaign_type: str | None = None
    scraped_at: datetime | None = None
    # Why `cities` is what it is, for the copy under the picker — NOT for choosing a widget.
    # CITY → the campaign's own cities. PAN_INDIA → it runs everywhere. None → we have not
    # scraped its targeting, so "everywhere" is an assumption rather than a fact.
    region_type: str | None = None
    # Where a bid rule for this campaign may measure, ALWAYS populated: the campaign's own
    # cities when it targets some, every measurable city otherwise. One list, one shape, so
    # the form never picks between sources — see `_measurement_cities`.
    cities: list[TargetedCity] = []
    keywords: list[KeywordBidRange] = []
    # Budget facts, for display. We deliberately do NOT enforce a minimum budget locally —
    # Blinkit publishes no such field and its dashboard derives one in the browser, so the
    # marketplace stays the judge (decided 2026-08-27).
    daily_budget: int | None = None
    pacing_type: str | None = None
    billed_amount: float | None = None
    # What a bid buys on this marketplace — CPM (Blinkit, per 1,000 impressions) or CPC
    # (Zepto, per click). The same ₹ figure is very different money, so the form must say.
    # `keywords[].current_cpm` keeps its old name on both; this field is its unit.
    unit: Literal["CPM", "CPC"] | None = None


class CatalogKeywordOut(BaseModel):
    """One (campaign, keyword, match_type) the marketplace's catalogue holds — a row of the
    keyword picker (ZC-E3). No performance numbers: on Zepto there are none per campaign
    (its keyword metrics are brand grain), so the picker shows the bid and the floor instead.
    """
    campaign_id: int
    campaign_name: str | None = None
    # Raw status and its meaning, same pair as `CampaignRow` — sort and badge by `state`.
    status: str | None = None
    state: str | None = None
    keyword: str
    match_type: str
    # The live bid, in `unit` (CPC on Zepto, CPM on Blinkit), and the marketplace's floor.
    bid: int | None = None
    min_bid: int | None = None
    unit: Literal["CPM", "CPC"] | None = None
    automatable: bool = True
    not_automatable_reason: str | None = None
    scraped_at: datetime | None = None


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
    # Blinkit: an integer advertiser id. Zepto: the brand UUID (ZC-D5) — the old `int`
    # refused it, so a Zepto account could never be stored through the API.
    advertiser_id: int | str


class AdvertiserOut(BaseModel):
    advertiser_id: int | str | None = None


class LiveOut(BaseModel):
    """Whether automations on this marketplace write for real (ZC-D9). Armed from the CLI
    only (`cm arm -m <marketplace>`) — the switch that spends money is not a button."""
    marketplace: str
    live: bool


class EnqueuedOut(BaseModel):
    """Returned by an enqueue endpoint — the UI polls the job by id."""
    job_id: uuid.UUID
    status: str = "pending"


class CmJobOut(BaseModel):
    model_config = _orm
    id: uuid.UUID
    job_type: str
    status: str
    # The id this run files its `cm_run_log` rows under — the link between "the job
    # finished" and "here is what it did". Set by the service from `params`; None for job
    # types that record nothing (a catalogue refresh) and for rows enqueued before this
    # existed, so every consumer must handle its absence.
    #
    # ⚠️ `status: success` means the process exited, NOT that the write landed. The CM
    # commands return their counts and never set a non-zero exit code, so a refused write
    # settles exactly like an accepted one. Ask `/history?run_id=` for the real outcome.
    run_id: str | None = None
    error: str | None = None
    exit_code: int | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CmActionOut(BaseModel):
    """One thing a person asked for, for the dashboard's activity list.

    A job row, not a history row — which is the point: it exists from the moment the action
    is queued, long before the run has written anything. The run log cannot answer "is my
    change happening" because its rows are written when the run ENDS.

    `run_id` links the two: once the job settles, the rows filed under that id are what it
    actually did. `status` alone never answers that — the CM commands never set a non-zero
    exit code, so a refused write settles exactly like an accepted one.
    """
    model_config = _orm
    id: uuid.UUID
    job_type: str
    # Human wording for the type ("Campaign budget change"), from the job registry, so the
    # UI never has to render a dotted type name at a reader.
    label: str | None = None
    status: str
    run_id: str | None = None
    campaign_id: int | None = None
    # Set only by the actions that target ONE keyword (a bid reset). It is what makes a row
    # in the table match exactly: without it, resetting one keyword would mark every bid
    # rule on that campaign as busy.
    keyword: str | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RunLogOut(BaseModel):
    model_config = _orm
    id: int
    # The run that wrote this row — every row one engine tick or one job produced shares it,
    # so the UI can show a run's decisions together (and match a row to Cloud Logging).
    run_id: str | None = None
    kind: str
    campaign_id: int | None = None
    campaign_name: str | None = None
    keyword: str | None = None
    action: str
    # Which automation this decision belongs to — the key a per-automation view groups by.
    # A bid rule's id is a uuid hex string, so this is text (see CmRunLog.rule_id).
    rule_id: str | None = None
    old_value: float | None = None
    new_value: float | None = None
    # The two inputs behind the decision, so the UI can show WHY without parsing `reason`.
    position: float | None = None
    target: int | None = None
    reason: str | None = None
    dry_run: bool
    success: bool
    timestamp: datetime
