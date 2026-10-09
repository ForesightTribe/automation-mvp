"""Client-scoped competitive intelligence (public data through the client's
watchlist). Mounted under /clients/{client_id}/competition."""
from typing import Literal

from fastapi import APIRouter, Query

from app.dependencies import ClientDep, MarketplacesDep, PaginationDep, PeriodDep, SessionDep
from app.schemas.common import Page
from app.schemas.competition import (
    AdPresenceResponse,
    CompetitorRankRow,
    DiscountDepthResponse,
    PriceByStoreResponse,
    StoreCompetitionResponse,
    KeywordPresenceResponse,
    SkuVarianceResponse,
    BrandComparisonResponse,
    PricePositionResponse,
    RankMatrixResponse,
    ShareOfVoiceResponse,
    TopCompetitorsResponse,
    TopCompetitorByMarketplaceRow,
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


@router.get(
    "/top-competitors/by-marketplace",
    response_model=list[TopCompetitorByMarketplaceRow],
)
async def top_competitors_by_marketplace(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    limit: int = Query(15, ge=1, le=50),
):
    """The same leaderboard, split by the marketplace each presence was seen on."""
    return await competition_service.get_top_competitors_by_marketplace(
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
    by_marketplace: bool = Query(
        False, description="Split each band by the shelf it was seen on"
    ),
):
    """Per keyword: own price band vs competitor price band. `kind` filters
    combos/multipacks (default main = singles on both sides)."""
    return await competition_service.get_price_position(
        session, tenant_id=client.id, keyword=keyword, city=city,
        marketplaces=marketplaces, start=period.start, end=period.end, kind=kind,
        by_marketplace=by_marketplace,
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


@router.get("/ad-presence", response_model=AdPresenceResponse)
async def ad_presence(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    keyword: str | None = None,
    city: str | None = None,
    kind: Literal["main", "combo", "all"] = "main",
    by_city: bool = Query(False, description="Split each brand by city."),
):
    """Who buys search slots, how many, and how high they land."""
    return await competition_service.get_ad_presence(
        session, tenant_id=client.id, keyword=keyword, city=city,
        marketplaces=marketplaces, start=period.start, end=period.end,
        kind=kind, by_city=by_city,
    )


@router.get("/discount-depth", response_model=DiscountDepthResponse)
async def discount_depth(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    keyword: str | None = None,
    city: str | None = None,
    kind: Literal["main", "combo", "all"] = "main",
):
    """How hard each brand is discounting, and across how much of its range."""
    return await competition_service.get_discount_depth(
        session, tenant_id=client.id, keyword=keyword, city=city,
        marketplaces=marketplaces, start=period.start, end=period.end, kind=kind,
    )


@router.get("/price-by-store", response_model=PriceByStoreResponse)
async def price_by_store(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    keyword: str | None = None,
    city: str | None = None,
    kind: Literal["main", "combo", "all"] = "main",
    limit: int = Query(200, ge=1, le=1000),
    min_listings: int = Query(
        1, ge=1, le=100,
        description="Minimum listings per side before a store is compared.",
    ),
):
    """Own per-unit price against the competitor set, store by store."""
    return await competition_service.get_price_by_store(
        session, tenant_id=client.id, keyword=keyword, city=city,
        marketplaces=marketplaces, start=period.start, end=period.end,
        kind=kind, limit=limit, min_listings=min_listings,
    )


@router.get("/store-competition", response_model=StoreCompetitionResponse)
async def store_competition(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    keyword: str | None = None,
    city: str | None = None,
    kind: Literal["main", "combo", "all"] = "main",
    limit: int = Query(200, ge=1, le=2000),
):
    """Rank, share and rivals at each dark store — the store grain."""
    return await competition_service.get_store_competition(
        session, tenant_id=client.id, keyword=keyword, city=city,
        marketplaces=marketplaces, start=period.start, end=period.end,
        kind=kind, limit=limit,
    )


@router.get("/keyword-presence", response_model=KeywordPresenceResponse)
async def keyword_presence(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    city: str | None = None,
    kind: Literal["main", "combo", "all"] = "main",
):
    """Per keyword: in how many searched stores the brand actually appears."""
    return await competition_service.get_keyword_presence(
        session, tenant_id=client.id, city=city, marketplaces=marketplaces,
        start=period.start, end=period.end, kind=kind,
    )


@router.get("/sku-variance", response_model=SkuVarianceResponse)
async def sku_variance(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    keyword: str | None = None,
    city: str | None = None,
    kind: Literal["main", "combo", "all"] = "main",
):
    """Own SKUs: price spread and availability across dark stores."""
    return await competition_service.get_sku_variance(
        session, tenant_id=client.id, keyword=keyword, city=city,
        marketplaces=marketplaces, start=period.start, end=period.end, kind=kind,
    )


@router.get("/brand-comparison", response_model=BrandComparisonResponse)
async def brand_comparison(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    keyword: str | None = None,
    city: str | None = None,
    kind: Literal["main", "combo", "all"] = "main",
):
    """Every brand on one shelf: price, rank, presence and discount together."""
    return await competition_service.get_brand_comparison(
        session, tenant_id=client.id, keyword=keyword, city=city,
        marketplaces=marketplaces, start=period.start, end=period.end, kind=kind,
    )
