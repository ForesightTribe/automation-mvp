from datetime import date

from pydantic import BaseModel, ConfigDict


class CampaignRow(BaseModel):
    """Latest snapshot of a campaign within the window."""

    model_config = ConfigDict(from_attributes=True)

    campaign_id: int
    name: str | None
    type: str | None
    status: str | None
    date: date
    budget_consumed: float
    impressions: int
    atcs: int
    roas: float
    reach: int


class AdPerformancePoint(BaseModel):
    date: date
    budget_consumed: float
    impressions: int


class SponsoredSovRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    keyword: str
    monthly_searches: int
    searches: int
    sov: float
    date: date


class VisibilityPlanRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan_id: int
    name: str | None
    type: str | None
    budget: float
    start_date: str | None
    end_date: str | None
    status: str | None


class CollectionRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collection_id: int
    name: str | None
    number_of_products: int
    is_dynamic: bool
