"""Instamart-side reads for the Reports page.

Same split as `zepto_reports.py`, and the same reasoning for each:

* **Sales pivot** — `pivot_rows` returns rows in the exact tuple shape
  `reports_service.get_sales_pivot`'s own query produces, so the caller
  extends its list and the whole pivot machinery (week axis, category
  grouping, subtotals, weekday/weekend split) runs over Instamart unchanged.
* **Marketing** — `sales_daily` is the per-day revenue map, from
  `instamart_brand_city_daily` (a genuinely SEPARATE report/table from the
  per-item sales pivot's source, `instamart_seller_store_daily` — same
  "two independent figures" shape as Zepto's own `zepto_seller_sales_summary`
  vs. `zepto_seller_sales`). `ad_daily` is the ad side, from
  `instamart_ad_account_daily` — the same real per-day account-wide table the
  Ads Insights KPI strip already uses (see `instamart_ads.summary_agg`).
* **Competition** — nothing needed here either, same reason as Zepto: it
  reads `search_listings`, keyed by `mp_slug`, already carrying Instamart
  rows from the public scraper.

* **Weekend planning** — `weekend_rows` sources `instamart_ad_product_daily`,
  which (unlike `instamart_ad_account_daily`) IS per-campaign-per-day, so the
  same weekend/weekday split Blinkit gets works here too. It intentionally
  does NOT also read `instamart_ad_keyword_daily`: the two are different
  VIEWS of the same campaign spend (see `instamart_ads.py`'s own
  campaign-breakdown docstring), and summing both would double it.
  `campaign_id` is Instamart's own UUID string, not Blinkit's int — the two
  never collide as dict keys upstream (`WeekendCampaign.campaign_id` is
  typed `int | str` for exactly this). `ad_type` is always None here:
  Instamart's ad-type breakdown was removed upstream as unreliable (see
  `asset_metrics.py`), so every Instamart campaign lands in one flat
  "Other Ads" section rather than Blinkit's "Keyword Ads"/"Banner Ads" split.
"""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instamart_ads import InstamartAdAccountDaily as AdDaily
from app.models.instamart_ads import InstamartAdCampaign
from app.models.instamart_ads import InstamartAdProductDaily as ProductDaily
from app.models.instamart_seller import InstamartBrandCityDaily as BrandDaily
from app.models.instamart_seller import InstamartSellerStoreDaily as Store

SLUG = "instamart"


def wants_instamart(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Instamart."""
    return marketplaces is None or SLUG in marketplaces


async def pivot_rows(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    metric: str = "value",
) -> list[tuple]:
    """(platform, item_id, item_name, category, date, value) — the exact tuple
    `get_sales_pivot` builds its pivot from.

    Category is `l2_category` ("Cheese" / "Bread and Buns"), falling back to
    `l1_category` — the same level `instamart_analytics.sales_by_category`
    already uses, for the same reason: every SKU here shares one broad L1
    bucket, which would collapse the pivot into a single group.
    """
    metric_col = Store.units_sold if metric == "units" else Store.gmv
    rows = (
        await session.execute(
            select(
                Store.item_code,
                func.max(Store.product_name),
                func.coalesce(Store.l2_category, Store.l1_category),
                Store.date,
                func.coalesce(func.sum(metric_col), 0.0),
            )
            .where(
                Store.tenant_id == tenant_id,
                Store.date >= start,
                Store.date <= end,
            )
            .group_by(
                Store.item_code,
                func.coalesce(Store.l2_category, Store.l1_category),
                Store.date,
            )
        )
    ).all()
    return [(SLUG, item_id, name, cat, d, val) for item_id, name, cat, d, val in rows]


async def sales_daily(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> dict[date, float]:
    """date -> total revenue, from Instamart's own brand-metrics sheet
    (`instamart_brand_city_daily`) rather than summing the per-item table —
    a separate report, and therefore an independent figure to check the pivot
    against, same shape as Zepto's own two-table split."""
    rows = (
        await session.execute(
            select(BrandDaily.date, func.coalesce(func.sum(BrandDaily.brand_gmv), 0.0))
            .where(
                BrandDaily.tenant_id == tenant_id,
                BrandDaily.date >= start,
                BrandDaily.date <= end,
            )
            .group_by(BrandDaily.date)
        )
    ).all()
    return {d: float(rev) for d, rev in rows}


async def ad_daily(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> dict[date, tuple[float, float, int]]:
    """date -> (spend, ad_gmv, impressions), from the same account-wide daily
    table the Ads Insights KPI strip reads (`instamart_ads.summary_agg`) —
    the one Instamart ad table genuinely windowed by day."""
    rows = (
        await session.execute(
            select(
                AdDaily.date,
                func.coalesce(func.sum(AdDaily.spend), 0.0),
                func.coalesce(func.sum(AdDaily.gmv), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
            )
            .where(
                AdDaily.tenant_id == tenant_id,
                AdDaily.date >= start,
                AdDaily.date <= end,
            )
            .group_by(AdDaily.date)
        )
    ).all()
    return {d: (float(sp), float(ga), int(im)) for d, sp, ga, im in rows}


async def weekend_rows(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[tuple]:
    """(campaign_id, campaign_type, date, spend, revenue, impressions) — the
    exact tuple `reports_service.get_weekend_planning`'s own Blinkit query
    produces, so it extends that same list.

    Sourced from `instamart_ad_product_daily` ONLY, not also
    `instamart_ad_keyword_daily` — the two are different VIEWS of the same
    campaign spend (see `instamart_ads.py`'s own campaign-breakdown
    docstring: "Products and keywords are two views of the same spend...
    not added up"), and using both here would double it. `campaign_type` is
    always None: Instamart's ad-type breakdown was removed upstream as
    unreliable (see `asset_metrics.py`), so unlike Blinkit's `PRODUCT_
    LISTING`/`BANNER_DIY` split, every Instamart campaign lands in one flat
    section in the caller's grouping.
    """
    rows = (
        await session.execute(
            select(
                ProductDaily.campaign_id,
                ProductDaily.date,
                func.sum(ProductDaily.spend),
                func.sum(ProductDaily.gmv),
                func.sum(ProductDaily.impressions),
            )
            .where(
                ProductDaily.tenant_id == tenant_id,
                ProductDaily.date >= start,
                ProductDaily.date <= end,
                ProductDaily.campaign_id.is_not(None),
            )
            .group_by(ProductDaily.campaign_id, ProductDaily.date)
        )
    ).all()
    return [(cid, None, d, sp, rev, im) for cid, d, sp, rev, im in rows]


async def raw_ad_rows(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Instamart's raw material for the Weekend Planning raw-sheet tab —
    ungrouped `instamart_ad_product_daily` rows for the same campaigns
    `weekend_rows()` sums, so this tab's total for one campaign+date
    reconciles exactly against the Weekend Planning sheet above it.

    Rows whose `candidate_id` doesn't resolve to a known product are still
    shown (unlike `instamart_ads.products()`, which drops them for a clean
    aggregate view) — dropping here would understate this sheet's sum below
    what Weekend Planning shows for the same campaign+date, defeating the
    one reason a raw sheet exists. They get a `(unresolved product ...)`
    label instead.
    """
    names = dict(
        (
            await session.execute(
                select(InstamartAdCampaign.campaign_id, InstamartAdCampaign.name).where(
                    InstamartAdCampaign.tenant_id == tenant_id
                )
            )
        ).all()
    )
    from app.models.search import SkuSnapshot

    product_names = dict(
        (
            await session.execute(
                select(SkuSnapshot.platform_product_id, SkuSnapshot.product_name)
                .where(SkuSnapshot.tenant_id == tenant_id, SkuSnapshot.mp_slug == SLUG)
                .distinct(SkuSnapshot.platform_product_id)
            )
        ).all()
    )
    rows = (
        await session.execute(
            select(
                ProductDaily.date,
                ProductDaily.campaign_id,
                ProductDaily.candidate_id,
                ProductDaily.spend,
                ProductDaily.gmv,
                ProductDaily.impressions,
                ProductDaily.clicks,
                ProductDaily.add_to_cart_count,
            )
            .where(
                ProductDaily.tenant_id == tenant_id,
                ProductDaily.date >= start,
                ProductDaily.date <= end,
                ProductDaily.campaign_id.is_not(None),
            )
            .order_by(ProductDaily.date, ProductDaily.campaign_id)
        )
    ).all()
    return [
        {
            "date": d,
            "campaign_id": cid,
            "campaign_name": names.get(cid) or f"Campaign {cid}",
            "candidate_id": candidate_id,
            "product_name": product_names.get(candidate_id)
            or f"(unresolved product {candidate_id})",
            "spend": round(float(spend or 0), 2),
            "gmv": round(float(gmv or 0), 2),
            "impressions": int(impr or 0),
            "clicks": int(clicks or 0),
            "add_to_cart_count": int(atc or 0),
            "roas": round(float(gmv) / float(spend), 4) if spend else None,
        }
        for d, cid, candidate_id, spend, gmv, impr, clicks, atc in rows
    ]


async def campaign_names(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> dict[str, str]:
    """campaign_id -> name, for `weekend_rows`' rows to look their names up
    against — the same lifetime `instamart_ad_campaigns` table the Ads
    Insights page reads, not something re-derived here."""
    rows = (
        await session.execute(
            select(InstamartAdCampaign.campaign_id, InstamartAdCampaign.name).where(
                InstamartAdCampaign.tenant_id == tenant_id
            )
        )
    ).all()
    return {cid: name for cid, name in rows}
