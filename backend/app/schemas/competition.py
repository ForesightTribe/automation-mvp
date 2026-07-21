from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SovTrendPoint(BaseModel):
    date: date
    avg_sov: float | None
    avg_rank: float | None
    samples: int


class SovSummary(BaseModel):
    brands: list[str]  # the client's own brand(s) this SOV covers
    marketplace: str | None
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


class TopCompetitorsResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    total_competitor_stores: int
    competitors: list[TopCompetitorRow]


# --- Price positioning (own vs competitor range, per keyword) ----------------

class PricePositionRow(BaseModel):
    keyword: str
    own_avg_price: float | None
    own_min_price: float | None
    own_max_price: float | None
    comp_avg_price: float | None
    comp_min_price: float | None
    comp_median_price: float | None
    comp_max_price: float | None
    own_samples: int
    comp_samples: int


class PricePositionResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    rows: list[PricePositionRow]
