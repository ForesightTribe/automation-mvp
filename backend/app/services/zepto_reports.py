"""Zepto-side reads for the Reports page.

Three reports, three different situations:

* **Sales pivot** — `pivot_rows` returns rows in exactly the tuple shape
  `reports_service.get_sales_pivot`'s own query produces, so the caller extends
  its list and the whole pivot machinery (week axis, category grouping,
  subtotals, weekday/weekend split) runs over both marketplaces unchanged. No
  logic is duplicated here.
* **Marketing** — `sales_daily` returns the per-day revenue map. The ad side
  comes from `zepto_ads.trend_series`, which is also what the Overview chart
  uses, so Zepto ad spend has exactly one definition. Ratios (RoAS, ROI) are
  recomputed by the caller from summed inputs, never averaged.
* **Competition** — nothing needed. It reads `search_listings`, which is keyed
  by `mp_slug` and already carries Zepto rows.
* **Weekend planning** — `weekend_rows` reads `zepto_ad_campaign_daily`
  directly: unlike Blinkit (identity + series split across two tables) and
  Instamart (no per-campaign table at all for the account-wide daily series),
  Zepto's scraper already writes one row per campaign per day with both the
  identity fields and the windowed metrics together — see that table's own
  docstring. `campaign_name` lives on the same row, so no separate names
  lookup is needed the way Blinkit's and Instamart's campaign tables require.
  `campaign_type` (PLA | Display) is a real, campaign-level axis here — unlike
  Instamart, which lost its ad-type breakdown upstream — so Zepto gets its own
  "PLA Ads" / "Display Ads" sections the same way Blinkit gets "Keyword Ads" /
  "Banner Ads".

One thing to know about the pivot's week axis: it counts only whole Mon–Sun
weeks, so a window like 27–28 Aug (Thu–Fri) yields no weekly columns at all.
That is the existing Blinkit behaviour and applies identically to Zepto — it is
not a gap in this module.
"""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zepto_seller import ZeptoAdCampaignDaily as AdDaily
from app.models.zepto_seller import ZeptoSellerSales as Prod
from app.models.zepto_seller import ZeptoSellerSalesSummary as Daily

SLUG = "zepto"


def wants_zepto(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Zepto."""
    return marketplaces is None or SLUG in marketplaces


def _prod_conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    # Day-grain rows only; a window-grain row would double-count (see
    # zepto_products._conds for the same guard).
    return [
        Prod.tenant_id == tenant_id,
        Prod.period_start >= start,
        Prod.period_start <= end,
        Prod.period_start == Prod.period_end,
    ]


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

    Category is the **subcategory** ("Breads & Buns" / "Cheese"): every Brik Oven
    SKU shares one `category_name`, which would collapse the pivot into a single
    group and defeat the grouping entirely. Same choice as `zepto_products`.
    """
    metric_col = Prod.qty_sold if metric == "units" else Prod.gmv
    rows = (
        await session.execute(
            select(
                Prod.product_variant_id,
                func.max(func.coalesce(Prod.sku_name, Prod.product_name)),
                func.coalesce(Prod.subcategory_name, Prod.category_name),
                Prod.period_start,
                func.coalesce(func.sum(metric_col), 0.0),
            )
            .where(*_prod_conds(tenant_id, start, end))
            .group_by(
                Prod.product_variant_id,
                func.coalesce(Prod.subcategory_name, Prod.category_name),
                Prod.period_start,
            )
        )
    ).all()
    return [(SLUG, pid, name, cat, d, val) for pid, name, cat, d, val in rows]


async def sales_daily(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> dict[date, float]:
    """date -> total revenue, from Zepto's own brand totals.

    `zepto_seller_sales_summary` rather than summing the per-SKU table: it is a
    separate endpoint and therefore an independent figure. The two have agreed
    to the rupee on every day scraped so far, and a disagreement would mean the
    per-day product loop dropped something — worth surfacing, not papering over.
    """
    rows = (
        await session.execute(
            select(Daily.date, func.coalesce(func.sum(Daily.gmv), 0.0))
            .where(Daily.tenant_id == tenant_id, Daily.date >= start, Daily.date <= end)
            .group_by(Daily.date)
        )
    ).all()
    return {d: float(rev) for d, rev in rows}


async def weekend_rows(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[tuple]:
    """(campaign_id, campaign_type, date, spend, revenue, impressions) — the
    exact tuple `reports_service.get_weekend_planning`'s own Blinkit query
    produces, so it extends that same list.

    `campaign_id` is prefixed `"zepto:<id>"` rather than passed through as
    the bare int Zepto itself uses. Blinkit's ids are also plain ints, both
    platform-assigned and independent of each other — nothing stops the two
    from landing on the same number for a different client (verified no
    overlap for THIS tenant today, but that's this tenant's current data, not
    a guarantee). The caller's accumulator keys purely on `campaign_id`, so an
    unprefixed collision would silently sum two unrelated campaigns' spend
    together under one row. The prefix is never shown to a user (the
    frontend only uses it as a React key), so this costs nothing.

    `revenue` is nullable on the source table (a campaign with spend but no
    Analytics-view match yet), coalesced to 0 here — same treatment Blinkit's
    `ad_sales` gets.
    """
    rows = (
        await session.execute(
            select(
                AdDaily.campaign_id,
                AdDaily.campaign_type,
                AdDaily.date,
                func.sum(AdDaily.spend),
                func.coalesce(func.sum(AdDaily.revenue), 0.0),
                func.sum(AdDaily.impressions),
            )
            .where(
                AdDaily.tenant_id == tenant_id,
                AdDaily.date >= start,
                AdDaily.date <= end,
            )
            .group_by(AdDaily.campaign_id, AdDaily.campaign_type, AdDaily.date)
        )
    ).all()
    return [(f"zepto:{cid}", ctype, d, sp, rev, im) for cid, ctype, d, sp, rev, im in rows]


async def campaign_names(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> dict[str, str]:
    """`"zepto:<id>"` -> its most recently scraped name, keyed to match
    `weekend_rows`'s prefixed ids. `zepto_ad_campaign_daily` carries the name
    on every row (no separate lifetime campaigns table the way Blinkit's and
    Instamart's do), so this just picks the latest one per campaign rather
    than looking anything up elsewhere."""
    rows = (
        await session.execute(
            select(AdDaily.campaign_id, AdDaily.campaign_name)
            .where(AdDaily.tenant_id == tenant_id)
            .distinct(AdDaily.campaign_id)
            .order_by(AdDaily.campaign_id, AdDaily.date.desc())
        )
    ).all()
    return {f"zepto:{cid}": name for cid, name in rows if name}
