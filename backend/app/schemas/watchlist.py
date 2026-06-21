from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Relationship = Literal["own", "competitor"]


class WatchlistEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_slug: str
    relationship: str
    cities: list[str]
    keywords: list[str]
    marketplaces: list[str]
    created_at: datetime
    updated_at: datetime


class WatchlistCreate(BaseModel):
    brand_slug: str
    relationship: Relationship = "competitor"
    cities: list[str] = []
    keywords: list[str] = []
    marketplaces: list[str] = []


class WatchlistUpdate(BaseModel):
    """Partial update — only provided fields are changed."""

    relationship: Relationship | None = None
    cities: list[str] | None = None
    keywords: list[str] | None = None
    marketplaces: list[str] | None = None
