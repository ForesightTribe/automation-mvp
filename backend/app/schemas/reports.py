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
    """One calendar-week rollup column (Monday-start), clamped to the selected
    range at the edges. `label` is sequential ("Wk 1"); `start`/`end` are the
    visible span summed into it."""

    label: str
    start: date
    end: date


class PivotSku(BaseModel):
    """A single SKU row: daily cells aligned to `days`, the window total, weekly
    rollups aligned to `weeks`, and week-over-week deltas (`week_deltas[i]` = week
    i vs i-1; index 0 is always None)."""

    item_id: str
    name: str
    cells: list[float]
    total: float
    weeks: list[float]
    week_deltas: list[float | None]


class PivotPlatform(BaseModel):
    """One marketplace block: its SKU rows plus the Grand Total row (column sums,
    weekly rollups, and their week-over-week deltas). `live` = the platform has a
    data pipeline (Blinkit today); others would arrive as separate blocks once
    their scrapers exist."""

    platform: str
    live: bool
    skus: list[PivotSku]
    day_totals: list[float]
    total: float
    week_totals: list[float]
    week_deltas: list[float | None]


class SalesPivot(BaseModel):
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
    price, `mrp` list price. `grammage`/`sp_per_gram` stay None until grammage is
    captured (system-wide gap), so the per-gram comparison is blank for now."""

    name: str
    brand: str | None
    mrp: float | None
    sp: float | None
    grammage: float | None
    sp_per_gram: float | None


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
