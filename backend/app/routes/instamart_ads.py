"""Instamart-only advertising endpoints, mounted alongside /clients/{client_id}/ads.

Same reasoning as `routes/zepto_ads.py`: a separate router so the Blinkit ad
routes and their response models stay exactly as they are. Anything Instamart
can express through the shared shapes (summary, campaigns, performance) is
already served by those routes via the merge in `ads_service`; only what has
no Blinkit counterpart lives here.
"""
from fastapi import APIRouter, Query

from app.dependencies import ClientDep, PeriodDep, SessionDep
from app.schemas.instamart_ads import (
    InstamartBudgetSplitRow,
    InstamartCampaignKeywordRow,
    InstamartKeywordRow,
    InstamartProductRow,
)
from app.services import instamart_ads

router = APIRouter()


@router.get("/instamart-budget-split", response_model=list[InstamartBudgetSplitRow])
async def instamart_budget_split(session: SessionDep, client: ClientDep, period: PeriodDep):
    """Spend share and RoAS by Instamart campaign type, windowed by `period`
    — see instamart_ads.budget_split."""
    return await instamart_ads.budget_split(
        session, tenant_id=client.id, start=period.start, end=period.end,
    )


@router.get("/instamart-products", response_model=list[InstamartProductRow])
async def instamart_products_ads(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    limit: int = Query(200, ge=1, le=1000),
):
    """Ad spend and return per advertised product, highest spend first,
    account-wide. Each row's `campaigns` breaks the total down by campaign
    — see instamart_ads.products. No ad-type filter: it existed earlier and
    was removed as unreliable — see asset_metrics.py's docstring."""
    rows = await instamart_ads.products(
        session, tenant_id=client.id, start=period.start, end=period.end,
    )
    return rows[:limit]


@router.get("/instamart-keywords", response_model=list[InstamartKeywordRow])
async def instamart_keywords(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    sort: str = Query("spend", pattern="^(spend|sales|roas|impressions|clicks)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Keyword performance for the window, account-wide. Each row's
    `campaigns` breaks the total down by campaign — see
    instamart_ads.keywords. No ad-type filter — see instamart_products_ads."""
    rows = await instamart_ads.keywords(
        session, tenant_id=client.id, start=period.start, end=period.end,
    )
    key = {
        "spend": lambda r: r["spend"],
        "sales": lambda r: r["sales"],
        "roas": lambda r: r["roas"] or 0.0,
        "impressions": lambda r: r["impressions"],
        "clicks": lambda r: r["clicks"],
    }[sort]
    rows.sort(key=key, reverse=(order != "asc"))
    return rows[:limit]


@router.get(
    "/instamart-campaign-keywords", response_model=list[InstamartCampaignKeywordRow]
)
async def instamart_campaign_keywords(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    campaign_id: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
):
    """Top keywords by spend for ONE campaign, windowed — fills the Campaign
    insights drawer's "Top keywords by spend" section for an Instamart
    campaign, the same spot Blinkit/Zepto campaigns already fill from their
    own tables. See instamart_ads.campaign_keywords."""
    return await instamart_ads.campaign_keywords(
        session, tenant_id=client.id, campaign_id=campaign_id,
        start=period.start, end=period.end, limit=limit,
    )
