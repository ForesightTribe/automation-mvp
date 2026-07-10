"""Explorer schemas — the run's data contracts.

`ExplorerSpec` is the single input contract for one Explorer run: the CLI parses
argv into it today, and the admin API (Phase 4) will validate its request body
into the same model. Response/insight schemas (Phase 2) are added alongside.
"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["keyword", "catalog", "both"]


class ExplorerSpec(BaseModel):
    """One on-demand Explorer run. All inputs are ad-hoc — no tenant required."""

    marketplace: str = "blinkit"
    brand: str                                              # focus brand (name or slug)
    aliases: list[str] = Field(default_factory=list)        # brand-name variants for matching
    competitors: list[str] = Field(default_factory=list)    # whitelist; empty = discover (keep all)
    keywords: list[str] = Field(default_factory=list)       # category keywords (keyword mode)
    cities: list[str] = Field(default_factory=list)         # empty = every catalog city

    mode: Mode = "keyword"
    sample: int | None = 50        # locations sampled per city; ignored when full=True
    full: bool = False             # census — every catalog location in the city
    workers: int = 5               # concurrent browser workers
    cap: int | None = None         # per-keyword result cap override
    brand_cap: int | None = None   # catalog-mode brand-query cap override

    label: str = ""                # optional human label for the run
    tenant_id: str | None = None   # optional: attribute the run to a client
    account_id: str | None = None  # creator attribution (set by the API; CLI leaves None)


class ExplorerRunOut(BaseModel):
    """Pollable run record — the CLI summary line and the future UI status/history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    marketplace: str
    mode: str
    brand_slug: str
    label: str
    status: str
    processed: int
    total: int
    keywords: int
    locations: int
    snapshots: int
    rows: int
    errors: int
    output_filename: str | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


# ── Insights (Phase 2) — one typed shape feeding BOTH the Excel writer and a
#    future JSON insights endpoint. `build_insights` returns `ExplorerInsights`. ──

class RunOverview(BaseModel):
    marketplace: str
    brand: str
    mode: str
    label: str
    keywords: list[str]
    cities: list[str]
    locations_scraped: int
    sample: int | None
    full: bool
    generated_at: datetime
    overall_sov_pct: float | None
    avg_rank: float | None
    in_stock_pct: float | None
    keywords_top3: int
    strongest_keyword: str | None
    weakest_keyword: str | None
    strongest_city: str | None
    weakest_city: str | None
    total_listings: int
    total_competitors: int
    errors: int


class KeywordScore(BaseModel):
    keyword: str
    locations: int
    avg_rank: float | None
    best_rank: int | None
    sov_pct: float | None
    presence_pct: float | None
    in_stock_pct: float | None
    competitors: int
    top_competitor: str | None


class CityScore(BaseModel):
    city: str
    locations: int
    avg_rank: float | None
    sov_pct: float | None
    in_stock_pct: float | None
    keywords: int


class CompetitorScore(BaseModel):
    competitor: str
    locations: int          # distinct (lat,lon) the competitor appeared in
    keywords: int
    appearances: int
    avg_position: float | None
    avg_price: float | None
    share_pct: float | None  # share of all competitor appearances


class PriceRow(BaseModel):
    keyword: str
    own_avg: float | None
    own_min: float | None
    own_max: float | None
    own_discount_pct: float | None
    comp_avg: float | None
    comp_min: float | None
    comp_median: float | None
    comp_max: float | None


class AvailabilityRow(BaseModel):
    keyword: str
    city: str
    own_found: int
    own_in_stock: int
    in_stock_pct: float | None


class CatalogRow(BaseModel):
    product_id: str
    name: str
    found_locations: int
    reach_pct: float | None
    distribution_pct: float | None
    price_min: float | None
    price_median: float | None
    price_max: float | None
    discount_pct: float | None
    rating: float | None
    is_combo: bool


class ExplorerInsights(BaseModel):
    overview: RunOverview
    keywords: list[KeywordScore]
    geography: list[CityScore]
    competitors: list[CompetitorScore]
    pricing: list[PriceRow]
    availability: list[AvailabilityRow]
    catalog: list[CatalogRow]
