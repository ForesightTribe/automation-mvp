"""Zepto-only advertising endpoints, mounted alongside /clients/{client_id}/ads.

A separate router rather than extra handlers on `routes/ads.py`, so the Blinkit
ad routes and their response models stay exactly as they are. Anything Zepto can
express through the shared shapes (summary, campaigns, performance) is already
served by those routes via the merge in `ads_service`; only what has no Blinkit
counterpart lives here.
"""
from fastapi import APIRouter, Query

from app.dependencies import ClientDep, PeriodDep, SessionDep
from app.schemas.zepto_ads import (
    ZeptoBudgetSplitRow,
    ZeptoBreakdownRow,
    ZeptoKeywordRow,
    ZeptoProductRow,
    ZeptoSovRow,
)
from app.services import zepto_ads

router = APIRouter()


@router.get("/zepto-keywords", response_model=list[ZeptoKeywordRow])
async def zepto_keywords(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    sort: str = Query("spend", pattern="^(spend|sales|roas|impressions|clicks)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Keyword performance for the window, one row per keyword + match type.

    Not paginated the way `/keywords` is: Zepto returns tens of keywords for
    this account, not thousands, and the table is more useful sorted whole. The
    `limit` is a safety bound, not a page size.
    """
    rows = await zepto_ads.keywords(
        session, tenant_id=client.id, start=period.start, end=period.end
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


@router.get("/zepto-budget-split", response_model=list[ZeptoBudgetSplitRow])
async def zepto_budget_split(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
):
    """Spend share and RoAS by Zepto campaign type, for the budget-split donut."""
    return await zepto_ads.budget_split(
        session, tenant_id=client.id, start=period.start, end=period.end
    )


@router.get("/zepto-sov", response_model=list[ZeptoSovRow])
async def zepto_sov(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
):
    """Share of voice and ad position per campaign, highest SOV first.

    A snapshot, not a windowed figure — see `zepto_ads.share_of_voice`. The
    period only bounds which scrapes are considered; each row's `as_of` says
    what its numbers actually describe.
    """
    return await zepto_ads.share_of_voice(
        session, tenant_id=client.id, start=period.start, end=period.end
    )


# The three Zepto ad types. Passed through as an optional filter rather than
# validated against an enum, so a new tab on Zepto's side does not 422 here.
_AD_TYPE_HELP = (
    "Narrow to one ad type: sponsored_products | sponsored_display | "
    "sponsored_brands. Omit to combine all three, which is the default because "
    "the tabs are disjoint and summing them double-counts nothing."
)


@router.get("/zepto-products", response_model=list[ZeptoProductRow])
async def zepto_products(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    campaign_category: str | None = Query(None, description=_AD_TYPE_HELP),
    limit: int = Query(200, ge=1, le=1000),
):
    """Ad spend and return per advertised SKU, highest spend first."""
    rows = await zepto_ads.products(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        campaign_category=campaign_category,
    )
    return rows[:limit]


@router.get("/zepto-breakdown", response_model=list[ZeptoBreakdownRow])
async def zepto_breakdown(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    dimension: str = Query(
        "category",
        pattern="^(category|city|page)$",
        description=(
            "Which breakdown to return: category (retail category), city, or "
            "page (where the ad appeared)."
        ),
    ),
    campaign_category: str | None = Query(None, description=_AD_TYPE_HELP),
):
    """Ad spend and return per bucket for one dimension, highest spend first."""
    return await zepto_ads.breakdown(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        dimension=dimension,
        campaign_category=campaign_category,
    )
