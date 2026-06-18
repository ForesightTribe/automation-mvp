"""Competitive-intelligence endpoints (public scraped data, no auth)."""
from fastapi import APIRouter, Query

from app.dependencies import PaginationDep, SessionDep
from app.schemas.common import Page
from app.schemas.competition import CompetitorRankRow, ShareOfVoiceResponse
from app.services import competition_service

router = APIRouter()


@router.get("/share-of-voice", response_model=ShareOfVoiceResponse)
async def share_of_voice(
    session: SessionDep,
    brand: str = Query(..., description="Brand slug"),
    marketplace: str | None = Query(None, description="Marketplace slug, e.g. blinkit"),
    keyword: str | None = None,
    city: str | None = None,
    days: int = Query(30, ge=1, le=365),
):
    return await competition_service.get_share_of_voice(
        session,
        brand_slug=brand,
        marketplace=marketplace,
        keyword=keyword,
        city=city,
        days=days,
    )


@router.get("/rankings", response_model=Page[CompetitorRankRow])
async def rankings(
    session: SessionDep,
    pagination: PaginationDep,
    keyword: str | None = None,
    city: str | None = None,
    marketplace: str | None = None,
    competitor: str | None = None,
):
    return await competition_service.get_rankings(
        session,
        pagination=pagination,
        keyword=keyword,
        city=city,
        marketplace=marketplace,
        competitor=competitor,
    )
