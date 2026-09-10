"""Response models for the Reports feature — the client's familiar Excel views
(sales pivot, marketing, competition) rebuilt as dashboard endpoints.

Everything is computed server-side so the frontend is a pure renderer and the
numbers match whatever a future server-side Excel export would produce.
"""
import uuid
from datetime import date

from pydantic import BaseModel


class PivotDay(BaseModel):
    """One day column. `weekend` = Fri/Sat/Sun (the client's convention), used to
    tint the column."""

    date: date
    weekend: bool


class PivotWeek(BaseModel):
    """One **complete** Monday–Sunday week inside the selected range. Partial weeks
    at either edge are excluded outright rather than clamped: a half-week summed
    against a full one made every week-over-week delta unreadable. `label` is
    sequential ("Wk 1"); `start` is always a Monday and `end` its Sunday."""

    label: str
    start: date
    end: date


class PivotSplit(BaseModel):
    """One half of the weekday/weekend split, as a series aligned to `weeks`.

    The client trades very differently Mon–Thu vs Fri–Sun, so a whole-week rollup
    averaged the two patterns together and hid both. Every weekly figure is
    therefore reported twice — once per half — and never blended.

    **Every value here is an average per day, not a sum.** Mon–Thu is 4 days and
    Fri–Sun is 3, so summed halves are not comparable quantities; per-day averages
    are. `cells[i]` is the average day in that half of week i, `total` the average
    day across the whole window, and `deltas[i]` week i vs week i-1 *for the same
    half* (index 0 is always None, as is any week following a zero).
    """

    cells: list[float]
    total: float
    deltas: list[float | None]


class PivotSku(BaseModel):
    """A single SKU row. `cells`/`total` are the daily view (aligned to `days`,
    covering the whole selected window) and are **sums**. `weekday`/`weekend` are
    the weekly view, cover **only the full weeks** in `weeks`, and are **averages
    per day**. `week_total` is the average day across all 7 days — a weighted mean
    of the two halves, so it is neither their sum nor their midpoint. The two
    views deliberately answer different questions and do not reconcile."""

    item_id: str
    name: str
    cells: list[float]
    total: float
    weekday: PivotSplit
    weekend: PivotSplit
    week_total: float


class PivotCategory(BaseModel):
    """One category group inside a platform block ("Cold Drinks & Juices",
    "Munchies", …, from `blinkit_seller_sales.category`) — its SKU rows plus the
    category subtotal row, in the same column shape as a SKU row."""

    name: str
    skus: list[PivotSku]
    # Same field names as PivotSku so a SKU row, a category subtotal and the grand
    # total all render through one code path on the frontend.
    cells: list[float]
    total: float
    weekday: PivotSplit
    weekend: PivotSplit
    week_total: float


class PivotPlatform(BaseModel):
    """One marketplace block: its category groups plus the Grand Total row (column
    sums, the weekday/weekend rollups, and their week-over-week deltas). `live` =
    the platform has a data pipeline (Blinkit today); others would arrive as
    separate blocks once their scrapers exist."""

    platform: str
    live: bool
    categories: list[PivotCategory]
    cells: list[float]
    total: float
    weekday: PivotSplit
    weekend: PivotSplit
    week_total: float


class SalesPivot(BaseModel):
    """`weeks` holds only complete Mon–Sun weeks, so it is empty for a window too
    short or too misaligned to contain one — the weekly view has nothing to show
    in that case while the daily view is unaffected."""

    client_id: uuid.UUID
    start: date
    end: date
    metric: str  # "value" (mrp_value) | "units" (qty_sold)
    days: list[PivotDay]
    weeks: list[PivotWeek]
    platforms: list[PivotPlatform]


# ── Marketing ledger ───────────────────────────────────────────────────────


class MarketingRow(BaseModel):
    """One day of the ad ledger. `spend`/`ad_revenue`/`impressions` come from the
    ad backbone; `total_revenue` from seller sales; `organic_revenue` =
    total − ad (clamped ≥ 0). Ratios are None when spend is 0 (no divide-by-0)."""

    date: date
    spend: float  # budget_consumed
    ad_revenue: float  # ad_sales
    roas: float | None  # ad_revenue / spend
    organic_revenue: float  # total_revenue − ad_revenue
    total_revenue: float  # seller mrp_value
    roi: float | None  # total_revenue / spend
    impressions: int


class MarketingTotals(BaseModel):
    """Footer totals. Ratios are recomputed from the summed inputs
    (Σ ad_revenue ÷ Σ spend), never averaged. `days` is the row count so the
    frontend can render a daily run-rate."""

    spend: float
    ad_revenue: float
    organic_revenue: float
    total_revenue: float
    impressions: int
    roas: float | None
    roi: float | None
    days: int


class MarketingReport(BaseModel):
    client_id: uuid.UUID
    start: date
    end: date
    rows: list[MarketingRow]
    totals: MarketingTotals


# ── Competition pricing ────────────────────────────────────────────────────


class CompRow(BaseModel):
    """One product in a competition group — own or competitor. `sp` is selling
    price, `mrp` list price. `pack_size`+`pack_uom` are the normalized pack (675.0 /
    "ml"); `unit_price` is the price at that UOM's display basis (₹/100 ml, ₹/100 g,
    ₹/piece) — the fair cross-pack comparison. `unit_price`/`pack_uom` are empty for
    an unparseable or heterogeneous pack. Only compare `unit_price` within one UOM."""

    name: str
    brand: str | None
    mrp: float | None
    sp: float | None
    pack_size: float | None
    pack_uom: str
    pack_count: int | None
    unit_price: float | None


class CompGroup(BaseModel):
    """A comparison set for one (marketplace, keyword): the client's own SKU(s)
    against the competitors that surfaced in the same search."""

    marketplace: str
    keyword: str
    own: list[CompRow]
    competitors: list[CompRow]


class CompetitionReport(BaseModel):
    client_id: uuid.UUID
    start: date
    end: date
    kind: str  # "main" | "combo" | "all"
    groups: list[CompGroup]


# ── Weekend planning ───────────────────────────────────────────────────────


class WeekendBlock(BaseModel):
    """One Fri–Sun weekend. `label` is "Weekend 1 (07 Aug)": the client's own
    numbering, plus the date so a reader can tell WHICH weekend without counting.
    `days` is how many of its three days fall inside the selected window, which is
    what the per-day figures divide by."""

    label: str
    index: int
    start: date
    end: date
    days: int


class CampaignHalf(BaseModel):
    """A campaign's numbers for one weekend, or for the weekdays. `roas` is
    recomputed from the summed spend and revenue, never averaged across days."""

    spend: float
    revenue: float
    roas: float | None
    impressions: int


class WeekendCampaign(BaseModel):
    """One campaign across every weekend in the window, plus its weekdays.

    `max_daily_spend` is the highest average day of spend the campaign reached in
    any single weekend. It is the planning number the client's sheet exists to
    produce: the ceiling this campaign has demonstrated it can spend to, rather
    than a budget someone hopes it will use.

    `ad_type` is the campaign's own type (PRODUCT_LISTING, BANNER_LISTING, …),
    which is the "Ad Type" column of the client's sheet. `weekends[i]` aligns to
    `WeekendPlanning.weekends`; a weekend the campaign did not run in is present
    with zeros rather than missing, so every row has the same shape."""

    campaign_id: int
    name: str
    ad_type: str | None
    weekends: list[CampaignHalf]
    weekend_total: CampaignHalf      # every weekend summed: the sheet's Grand Total group
    weekday: CampaignHalf
    total: CampaignHalf
    max_daily_spend: float


class AdTypeSection(BaseModel):
    """One ad-type block: its campaigns and the block's own subtotal row.

    Named the way the client names them ("Keyword Ads", "Recommendation Ads")
    rather than by Blinkit's enum, because that is the vocabulary the sheet is
    read in."""

    ad_type: str
    label: str
    campaigns: list[WeekendCampaign]
    subtotal: WeekendCampaign


class BannerRow(BaseModel):
    """A banner campaign. No revenue: banner placements carry no attribution, so
    they are judged on what an impression cost rather than on RoAS."""

    campaign_id: int
    name: str
    spend: float
    impressions: int
    spend_per_impression: float | None


class WeekendPlanning(BaseModel):
    """Campaign spend and return, split Fri–Sun against Mon–Thu.

    ⚠️ Unlike the sales pivot's weekday/weekend split, these are SUMS, not per-day
    averages. This sheet compares one weekend with another, which is like for
    like; the sales pivot compares a 4-day half with a 3-day half, which is not,
    and averages there for exactly that reason."""

    client_id: uuid.UUID
    start: date
    end: date
    weekends: list[WeekendBlock]
    sections: list[AdTypeSection]
    totals: WeekendCampaign
    # Their third sheet. Empty when no banner campaign ran in the window.
    banners: list[BannerRow]
