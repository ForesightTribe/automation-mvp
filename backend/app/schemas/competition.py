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
