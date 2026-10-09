from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SovTrendPoint(BaseModel):
    date: date
    avg_sov: float | None
    avg_rank: float | None
    samples: int


class SovSummary(BaseModel):
    brands: list[str]  # the client's own brand(s) this SOV covers
    marketplaces: list[str] | None
    keyword: str | None
    city: str | None
    period_days: int
    latest_sov: float | None
    avg_sov: float | None
    avg_rank: float | None
    total_samples: int


class ShareOfVoiceResponse(BaseModel):
    summary: SovSummary
    trend: list[SovTrendPoint]


class CompetitorRankRow(BaseModel):
    # from_attributes lets us validate straight from ORM rows;
    # serialization_alias renames mp_slug -> marketplace in the JSON output.
    model_config = ConfigDict(from_attributes=True)

    competitor: str
    keyword: str
    city: str
    zone: str
    mp_slug: str = Field(serialization_alias="marketplace")
    position: int | None
    price: float | None
    scraped_at: datetime


# --- Rank matrix (keyword × city heatmap) -----------------------------------

class RankCell(BaseModel):
    keyword: str
    city: str
    avg_rank: float | None
    avg_sov: float | None
    # Number of SEARCHES behind the cell (one search = one keyword at one probe
    # point), not distinct stores — rank/SoV describe a blended result list, so the
    # search is the sample unit. Keeps pre-2026-07-18 history usable.
    searches: int


class RankMatrixResponse(BaseModel):
    keywords: list[str]  # rows
    cities: list[str]    # columns
    cells: list[RankCell]
    period_days: int
    as_of: datetime | None


# --- Competitor leaderboard --------------------------------------------------

class TopCompetitorRow(BaseModel):
    competitor: str
    stores: int            # distinct dark stores the competitor was found in
    keywords: int          # distinct keywords the competitor showed up in
    avg_position: float | None
    avg_price: float | None
    share_pct: float | None  # share of all (competitor, store) presences


class TopCompetitorByMarketplaceRow(TopCompetitorRow):
    """A leaderboard row for one marketplace. `share_pct` is of THAT
    marketplace's competitor presences, so each marketplace's shares add to 100
    on their own."""

    marketplace: str


class TopCompetitorsResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    total_competitor_stores: int
    competitors: list[TopCompetitorRow]


# --- Price positioning (own vs competitor range, per keyword) ----------------

class PricePositionRow(BaseModel):
    keyword: str
    # Set only when the bands were split by shelf; None on the blended view.
    marketplace: str | None = None
    own_avg_price: float | None
    own_min_price: float | None
    own_max_price: float | None
    comp_avg_price: float | None
    comp_min_price: float | None
    comp_median_price: float | None
    comp_max_price: float | None
    own_samples: int
    comp_samples: int
    # Distinct products behind the figures. `*_samples` count listing rows
    # (product x store x scrape day) and overstate the basis roughly 1,800x, so
    # these are what a confidence judgement must rest on.
    own_products: int = 0
    comp_products: int = 0
    # Per-unit band at `unit_uom`'s basis (₹/100 ml · 100 g · piece) — the fair
    # comparison across pack sizes. `unit_uom` is the keyword's dominant UOM ("" when
    # nothing parsed); per-unit values are None for rows with no parseable pack.
    unit_uom: str = ""
    own_avg_unit_price: float | None = None
    own_min_unit_price: float | None = None
    own_max_unit_price: float | None = None
    comp_avg_unit_price: float | None = None
    comp_min_unit_price: float | None = None
    comp_median_unit_price: float | None = None
    comp_max_unit_price: float | None = None


class PricePositionResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    rows: list[PricePositionRow]


# ── Competitor benchmarking ─────────────────────────────────────────────────

class AdPresenceRow(BaseModel):
    brand: str
    city: str | None = None
    is_own: bool
    listings: int
    paid_placements: int
    paid_share_pct: float | None
    avg_paid_position: float | None
    best_paid_position: int | None


class AdPresenceResponse(BaseModel):
    rows: list[AdPresenceRow]
    by_city: bool
    # Set when the window predates Blinkit's is_ad capture (2026-09-04).
    caveat: str | None = None


class DiscountDepthRow(BaseModel):
    brand: str
    is_own: bool
    listings: int
    skus: int
    on_offer_share_pct: float | None
    avg_discount_pct: float | None
    median_discount_pct: float | None
    max_discount_pct: float | None


class DiscountDepthResponse(BaseModel):
    rows: list[DiscountDepthRow]


class PriceByStoreRow(BaseModel):
    store: str
    city: str
    marketplace: str
    # "ml" / "g" / "pc" — the basis both sides are measured in. Rows of different
    # bases are never averaged together.
    unit_basis: str
    own_unit_price: float | None
    competitor_avg_unit_price: float | None
    competitor_cheapest_unit_price: float | None
    # Positive = the client is the pricier option at this store.
    gap_vs_competitor_pct: float | None
    own_listings: int
    competitor_listings: int


class PriceByStoreResponse(BaseModel):
    rows: list[PriceByStoreRow]
    stores_compared: int
    min_listings: int


class StoreCompetitionRow(BaseModel):
    store: str
    city: str
    marketplace: str
    locality: str
    pincode: str
    results: int
    own_listings: int
    own_share_pct: float | None
    own_avg_position: float | None
    own_best_position: int | None
    own_skus: int
    own_in_stock_pct: float | None
    rival_brands: int
    top_rival: str | None
    top_rival_avg_position: float | None


class StoreCompetitionResponse(BaseModel):
    rows: list[StoreCompetitionRow]
    stores: int


class KeywordPresenceRow(BaseModel):
    keyword: str
    stores_searched: int
    stores_found: int
    presence_pct: float | None
    avg_rank: float | None
    best_rank: int | None
    avg_sov_pct: float | None


class KeywordPresenceResponse(BaseModel):
    rows: list[KeywordPresenceRow]


class SkuVarianceRow(BaseModel):
    sku: str
    pack: str
    appearances: int
    stores: int
    min_price: float | None
    max_price: float | None
    avg_price: float | None
    price_spread_pct: float | None
    in_stock_pct: float | None


class SkuVarianceResponse(BaseModel):
    rows: list[SkuVarianceRow]


class BrandComparisonRow(BaseModel):
    brand: str
    is_own: bool
    listings: int
    stores: int
    presence_pct: float | None
    skus: int
    avg_position: float | None
    best_position: int | None
    avg_price: float | None
    min_price: float | None
    max_price: float | None
    avg_unit_price: float | None
    unit_basis: str
    avg_discount_pct: float | None
    in_stock_pct: float | None
    paid_share_pct: float | None


class BrandComparisonResponse(BaseModel):
    rows: list[BrandComparisonRow]
    stores_measured: int
    keyword: str | None
