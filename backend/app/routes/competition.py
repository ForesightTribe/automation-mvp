"""Client-scoped competitive intelligence (public data through the client's
watchlist). Mounted under /clients/{client_id}/competition."""
from typing import Literal

from fastapi import APIRouter, Query

from app.dependencies import ClientDep, MarketplacesDep, PaginationDep, PeriodDep, SessionDep
from app.schemas.common import Page
from app.schemas.competition import (
    CompetitorRankRow,
    PricePositionResponse,
    RankMatrixResponse,
    ShareOfVoiceResponse,
    TopCompetitorsResponse,
)
from app.services import competition_service

router = APIRouter()


@router.get("/share-of-voice", response_model=ShareOfVoiceResponse)
async def share_of_voice(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    keyword: str | None = None,
    city: str | None = None,
):
    return await competition_service.get_share_of_voice(
        session,
        tenant_id=client.id,
        marketplaces=marketplaces,
        keyword=keyword,
        city=city,
        start=period.start,
        end=period.end,
    )


@router.get("/rank-matrix", response_model=RankMatrixResponse)
async def rank_matrix(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
):
    """Own-brand rank + SoV per (keyword, city) — the heatmap of where you're weak."""
    return await competition_service.get_rank_matrix(
        session, tenant_id=client.id, marketplaces=marketplaces, start=period.start, end=period.end
    )


@router.get("/top-competitors", response_model=TopCompetitorsResponse)
async def top_competitors(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    limit: int = Query(15, ge=1, le=50),
):
    """Competitor leaderboard — who shows up most in the client's searches."""
    return await competition_service.get_top_competitors(
        session, tenant_id=client.id, keyword=keyword, city=city,
        marketplaces=marketplaces, start=period.start, end=period.end, limit=limit,
    )


@router.get("/price-position", response_model=PricePositionResponse)
async def price_position(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    kind: Literal["main", "combo", "all"] = "main",
):
    """Per keyword: own price band vs competitor price band. `kind` filters
    combos/multipacks (default main = singles on both sides)."""
    return await competition_service.get_price_position(
        session, tenant_id=client.id, keyword=keyword, city=city,
        marketplaces=marketplaces, start=period.start, end=period.end, kind=kind,
    )


@router.get("/rankings", response_model=Page[CompetitorRankRow])
async def rankings(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    pagination: PaginationDep,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    competitor: str | None = None,
):
    return await competition_service.get_rankings(
        session,
        tenant_id=client.id,
        pagination=pagination,
        keyword=keyword,
        city=city,
        marketplaces=marketplaces,
        competitor=competitor,
    )
