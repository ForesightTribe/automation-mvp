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
    locations_scraped: int      # probe points searched from
    stores_seen: int            # distinct dark stores that answered
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
    total_listings: int         # PRODUCT ROWS captured, not distinct products
    total_products: int         # distinct products seen across the run
    own_products: int           # distinct products belonging to the focus brand
    total_competitors: int
    errors: int


class KeywordScore(BaseModel):
    keyword: str
    # `searches` counts individual searches; `stores` counts distinct dark stores.
    # These were one field called `locations` until 2026-08-11, which meant
    # searches here and distinct locations on CityScore — same name, two units.
    searches: int
    stores: int
    avg_rank: float | None
    best_rank: int | None
    sov_pct: float | None
    presence_pct: float | None
    in_stock_pct: float | None
    competitors: int
    top_competitor: str | None


class CityScore(BaseModel):
    city: str
    stores: int
    searches: int
    avg_rank: float | None
    sov_pct: float | None
    in_stock_pct: float | None
    keywords: int


class CompetitorScore(BaseModel):
    competitor: str
    stores: int             # distinct dark stores the competitor appeared in
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
    # Per-unit band at `unit_uom`'s basis (₹/100 ml · 100 g · piece) — the fair
    # comparison across pack sizes. "" / None when nothing in the keyword parsed.
    unit_uom: str = ""
    own_avg_unit: float | None = None
    own_min_unit: float | None = None
    own_max_unit: float | None = None
    comp_avg_unit: float | None = None
    comp_min_unit: float | None = None
    comp_median_unit: float | None = None
    comp_max_unit: float | None = None


class AvailabilityRow(BaseModel):
    keyword: str
    city: str
    own_found: int
    own_in_stock: int
    in_stock_pct: float | None


class CatalogRow(BaseModel):
    product_id: str
    name: str
    found_stores: int
    in_stock_stores: int
    reach_pct: float | None
    distribution_pct: float | None
    price_min: float | None
    price_median: float | None
    price_max: float | None
    discount_pct: float | None
    rating: float | None
    is_combo: bool
    # Pack + per-unit band (₹ per 100 ml / 100 g / piece per `pack_uom`).
    pack_size: float | None = None
    pack_uom: str = ""
    unit_price_min: float | None = None
    unit_price_median: float | None = None
    unit_price_max: float | None = None


class StoreScore(BaseModel):
    """One dark store: how much of the brand's range it carries."""

    merchant_id: str
    store_type: str
    city: str
    products_carried: int
    products_in_stock: int
    products_out_of_stock: int
    products_missing: int
    on_shelf_pct: float | None
    in_stock_pct: float | None


class GapRow(BaseModel):
    """One product missing or empty at one store — the work queue."""

    problem: str                # "Not carried" | "Out of stock"
    product: str
    product_id: str
    city: str
    merchant_id: str
    store_type: str
    units: int | None = None
    price: float | None = None


class GridCell(BaseModel):
    """Average position for one (search term, city) — the weakness grid."""

    keyword: str
    city: str
    avg_rank: float | None
    searches: int


class FamilyRow(BaseModel):
    """Singles plus their multipacks, counted as one product."""

    family: str
    variants: int
    stores_carrying: int
    on_shelf_pct: float | None
    listings: int
    in_stock_pct: float | None
    price_low: float | None
    price_high: float | None
    variant_names: str


class ExplorerInsights(BaseModel):
    overview: RunOverview
    keywords: list[KeywordScore]
    geography: list[CityScore]
    competitors: list[CompetitorScore]
    pricing: list[PriceRow]
    availability: list[AvailabilityRow]
    catalog: list[CatalogRow]
    stores: list[StoreScore] = Field(default_factory=list)
    gaps: list[GapRow] = Field(default_factory=list)
    grid: list[GridCell] = Field(default_factory=list)
    families: list[FamilyRow] = Field(default_factory=list)
