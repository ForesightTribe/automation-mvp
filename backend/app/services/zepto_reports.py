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

One thing to know about the pivot's week axis: it counts only whole Mon–Sun
weeks, so a window like 27–28 Aug (Thu–Fri) yields no weekly columns at all.
That is the existing Blinkit behaviour and applies identically to Zepto — it is
not a gap in this module.
"""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zepto_seller import ZeptoSellerProductPerf as Prod
from app.models.zepto_seller import ZeptoSellerSalesDaily as Daily

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

    `zepto_seller_sales_daily` rather than summing the per-SKU table: it is a
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
