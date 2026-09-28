"""The Action Center: what is worth acting on, ranked by what it is worth.

Each generator owns one source and returns zero or more insights. A generator
attaches a rupee `impact` only when its source supports one:

  - fill loss      the marketplace's own figure, taken as given          (high)
  - availability   OOS SKUs x their own recent daily revenue             (medium)
  - ads            spend that did not come back: spend minus ad sales, on
                   campaigns returning under 1x. Arithmetic on two observed
                   numbers, not a judgement against a target — this product
                   has no target RoAS, and inventing one would be a guess
  - visibility     reported in percentage points; no rupee conversion
  - automations    reported as counts of what was changed; no rupee conversion

Visibility is deliberate: turning a rank into revenue needs an attribution model
this product has not validated, and an invented number is worth less than an
honest observation. The same holds for a bid change: what it earned is not
separable from everything else that moved that day.
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blinkit_seller import BlinkitSOH, BlinkitScorecardKeySku
from app.models.search import SkuMap, SkuSnapshot
from app.utils.time import now_ist
from app.services import watchlist_service
from app.services.analytics_service import _market_agg

# How far back to read sell-through when valuing an out-of-stock SKU.
SELL_THROUGH_DAYS = 28
# Campaign types Blinkit attributes NO sales to. Judging them on return would
# mark every one of them a failure for a reason that has nothing to do with how
# they performed — 17 banner campaigns carry 208k impressions and exactly zero
# attributed sales.
NO_REVENUE_TYPES = ("BANNER_LISTING", "BANNER_DIY", "SHELF_DIY")
# Spending under this share of the daily budget is underuse worth surfacing.
UNDERSPEND_RATIO = 0.6
# At or above this share of budget, the campaign is capped rather than choosing
# to stop — demand it could have served went unserved.
CAPPED_RATIO = 0.95
# A visibility move smaller than this is noise, not news.
SOV_MIN_MOVE_PP = 2.0
# How far back to look for the automations' most recent day of work. A run log
# older than this is history rather than something to act on this morning.
AUTOMATION_LOOKBACK_DAYS = 7
# Run-log actions that actually wrote a new value to the marketplace. `no-op`
# and `skip` are decisions to leave the bid alone, which is the automation
# working, not the automation idle.
AUTOMATION_WRITE_ACTIONS = ("apply", "drift", "recover", "reset")
# What counts as a tick that could not complete.
#
# ⚠️ The `success` column cannot be used for this. It is false on 133 `skip`
# rows reading "stop · window ended" and on `reset` rows returning a bid to its
# floor — both of which are the engine doing exactly its job. Only `error`
# means the check itself failed and the value was left as it was.
AUTOMATION_ERROR_ACTION = "error"

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _rank_key(insight: dict) -> tuple:
    """Rank by money first, then severity, then how much is affected.

    Deliberately NOT a single blended score: the caller can see why one card sits
    above another, which a hidden weighting would take away.
    """
    impact = insight.get("impact") or {}
    rupees = impact.get("value") if impact.get("unit") == "INR" else None
    where = insight.get("where") or {}
    breadth = max(
        where.get("stores") or 0,
        where.get("skus") or 0,
        where.get("campaigns") or 0,
        where.get("keywords") or 0,
    )
    return (
        0 if rupees else 1,
        -(rupees or 0),
        _SEVERITY_RANK.get(insight["severity"], 9),
        -breadth,
    )


async def _fill_loss(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[dict]:
    """The marketplace's own potential-loss figure for the latest scorecard week."""
    week = (
        await session.execute(
            select(func.max(BlinkitScorecardKeySku.from_date_ist)).where(
                BlinkitScorecardKeySku.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if not week:
        return []

    rows = (
        await session.execute(
            select(
                BlinkitScorecardKeySku.item_name,
                BlinkitScorecardKeySku.potential_loss,
            )
            .where(
                BlinkitScorecardKeySku.tenant_id == tenant_id,
                BlinkitScorecardKeySku.from_date_ist == week,
                BlinkitScorecardKeySku.potential_loss > 0,
            )
            .order_by(BlinkitScorecardKeySku.potential_loss.desc())
        )
    ).all()
    if not rows:
        return []
    loss = sum(float(r[1]) for r in rows)
    skus = len(rows)
    items = [
        {"label": name or "Unnamed SKU", "value": round(float(v)), "unit": "INR"}
        for name, v in rows
    ]

    return [
        {
            "id": f"fill-loss-{week}",
            "type": "issue",
            "severity": "high" if loss >= 100_000 else "medium",
            "title": f"Under-supply on {skus} key SKU{'s' if skus > 1 else ''}",
            "what": (
                f"{skus} key SKU{'s were' if skus > 1 else ' was'} under-supplied "
                "last week. Fulfilling the open POs can recover the shortfall."
            ),
            "where": {"platform": "blinkit", "skus": skus},
            "impact": {
                "type": "fill_loss",
                "value": round(float(loss)),
                "unit": "INR",
                "confidence": "high",
            },
            "evidence": [
                {
                    "metric": "fill_loss",
                    "value": round(float(loss)),
                    "unit": "INR",
                    "period": f"week of {week}",
                },
                {"metric": "affected_skus", "value": skus, "unit": "count"},
            ],
            "items": items,
            "item_label": "Shortfall",
            "source": "Blinkit scorecard",
            "method": (
                f"Blinkit's own potential-loss figure for key SKUs in the week "
                f"of {week}."
            ),
            "href": "/purchase-orders?status=open",
            "cta": "Open Purchase Orders",
            "as_of": f"week of {week}",
        }
    ]


async def _availability(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[dict]:
    """Where our SKUs are not on sale, at both layers of the chain.

    Two separate facts, kept separate: `blinkit_soh` reports stock at Blinkit's
    FEEDER WAREHOUSES (~55 nationally, named "… Feeder Warehouse" in their own
    data), while the public scrape reports whether a shopper could actually buy
    the SKU at a DARK STORE (~1,900). Upstream supply and shelf presence are not
    the same thing and a feeder can be dry while its stores still hold stock.

    No rupee figure is attached. Converting a shelf gap into lost revenue needs
    assumptions about what would have sold where, which we do not measure.
    """
    snapshot = (
        await session.execute(
            select(func.max(BlinkitSOH.date)).where(BlinkitSOH.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not snapshot:
        return []

    # Denominator is the feeders that CARRY the SKU, not all of them — breadth
    # differs per SKU, so "41 of 49" and "5 of 54" are different denominators.
    coverage = (
        await session.execute(
            select(
                BlinkitSOH.item_id,
                func.max(BlinkitSOH.item_name),
                func.count(distinct(BlinkitSOH.backend_facility_id)),
                func.count(distinct(BlinkitSOH.backend_facility_id)).filter(
                    BlinkitSOH.frontend_inv_qty == 0
                ),
            )
            .where(BlinkitSOH.tenant_id == tenant_id, BlinkitSOH.date == snapshot)
            .group_by(BlinkitSOH.item_id)
        )
    ).all()
    empty_rows = [r for r in coverage if r[3]]
    if not empty_rows:
        return []

    # Dark-store shelf presence, joined through sku_map. Unmapped SKUs simply
    # carry no store line rather than being dropped or counted as zero.
    since = now_ist() - timedelta(days=10)
    shelf = {
        item: (out, listed)
        for item, out, listed in (
            await session.execute(
                select(
                    SkuMap.item_id,
                    func.count(distinct(SkuSnapshot.merchant_id)).filter(
                        SkuSnapshot.in_stock.is_(False)
                    ),
                    func.count(distinct(SkuSnapshot.merchant_id)),
                )
                .join(
                    SkuSnapshot,
                    SkuSnapshot.platform_product_id == SkuMap.platform_product_id,
                )
                .where(
                    SkuMap.tenant_id == tenant_id,
                    SkuSnapshot.tenant_id == tenant_id,
                    SkuSnapshot.scraped_at >= since,
                )
                .group_by(SkuMap.item_id)
            )
        ).all()
    }

    # Product shots live on the PUBLIC listings, not on sku_snapshots — the
    # latter carries no image key at all. Latest listing per product wins.
    images = {
        item: url
        for item, url in (
            await session.execute(
                text(
                    """
                    select distinct on (m.item_id)
                           m.item_id,
                           l.extra::jsonb->>'image_url'
                    from sku_map m
                    join search_listings l
                      on l.platform_product_id = m.platform_product_id
                     and l.tenant_id = m.tenant_id
                    where m.tenant_id = :tenant
                      and l.scraped_at > now() - interval '21 days'
                    order by m.item_id, l.scraped_at desc
                    """
                ),
                {"tenant": tenant_id},
            )
        ).all()
        if url
    }

    # Category comes from the seller feed; pack size from the public listing's
    # parsed unit, which is why it is only present for matched SKUs.
    meta = {
        item: (cat, size, uom)
        for item, cat, size, uom in (
            await session.execute(
                text(
                    """
                    select distinct on (s.item_id)
                           s.item_id, s.category,
                           k.pack_size, k.pack_uom
                    from blinkit_seller_sales s
                    left join sku_map m
                      on m.item_id = s.item_id and m.tenant_id = s.tenant_id
                    left join lateral (
                        select pack_size, pack_uom from sku_snapshots
                        where tenant_id = s.tenant_id
                          and platform_product_id = m.platform_product_id
                          and pack_size is not null
                        order by scraped_at desc limit 1
                    ) k on true
                    where s.tenant_id = :tenant
                    order by s.item_id, s.date desc
                    """
                ),
                {"tenant": tenant_id},
            )
        ).all()
    }

    def sub(item_id: str) -> str | None:
        cat, size, uom = meta.get(item_id, (None, None, None))
        pack = (
            f"{size:g} {uom}" if size is not None and uom else None
        )
        return " · ".join(x for x in (cat, pack) if x) or None

    gaps = sum(r[3] for r in empty_rows)
    items = []
    for item_id, name, carried, empty in sorted(
        empty_rows, key=lambda r: -(r[3] / r[2] if r[2] else 0)
    ):
        store = shelf.get(item_id)
        items.append(
            {
                "label": name or item_id,
                "sublabel": sub(item_id),
                # The headline ratio is the DARK STORE one — shelf presence is
                # what a shopper meets. The feeder gap that flagged the SKU is
                # kept in the note so the reason it is listed stays visible.
                "count": store[0] if store else None,
                "total": store[1] if store else None,
                "secondary_count": empty,
                "secondary_total": carried,
                "image": images.get(item_id),
            }
        )

    return [
        {
            "id": f"oos-{snapshot}",
            "type": "issue",
            "severity": "high",
            "title": f"{len(empty_rows)} SKUs with availability gaps",
            "what": (
                f"{len(empty_rows)} SKUs are out at one or more feeder "
                "warehouses. The dark store figures show how many stores are "
                "also out of stock."
            ),
            "where": {"platform": "blinkit", "skus": len(empty_rows)},
            "impact": {
                "type": "availability",
                "value": gaps,
                "unit": "count",
                "confidence": "high",
            },
            "evidence": [
                {
                    "metric": "skus_with_a_gap",
                    "value": len(empty_rows),
                    "unit": "count",
                },
                {
                    "metric": "sku_feeder_warehouse_gaps",
                    "value": gaps,
                    "unit": "count",
                    "period": f"snapshot of {snapshot}",
                },
            ],
            "items": items,
            "item_label": "Dark stores",
            "item_secondary_label": "Feeders",
            "source": "Internal inventory",
            "method": (
                "SKUs are flagged when inventory is zero in one or more feeder "
                "warehouses in the selected snapshot."
            ),
            "href": "/inventory",
            "cta": "Open Inventory",
            "as_of": f"snapshot of {snapshot}",
        }
    ]


async def _ads(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> list[dict]:
    """Campaigns that returned less than they cost.

    The bar is 1x on REVENUE, not a target RoAS: there is no target in this
    product and no universal break-even, so the only defensible line is the one
    arithmetic draws. A campaign under 1x spent more than the sales it is
    credited with, whatever the brand's margin. Note this understates the real
    bar — 1x on revenue is still a loss once cost of goods is counted.
    """
    from app.services import ads_service
    from app.schemas.common import Pagination

    page = await ads_service.get_campaigns(
        session,
        tenant_id=tenant_id,
        pagination=Pagination(page=1, limit=200),
        start=start,
        end=end,
        marketplaces=None,
        status=None,
        sort="spend",
        order="desc",
        recent_only=True,
    )
    weak = [
        c
        for c in page.items
        if (c.budget_consumed or 0) > 0
        and (c.roas or 0) < 1
        and (c.type or "") not in NO_REVENUE_TYPES
    ]
    if not weak:
        return []

    spend = sum(c.budget_consumed for c in weak)
    sales = sum(c.ad_sales for c in weak)
    shortfall = round(max(0.0, spend - sales))
    # Blended across the flagged campaigns, not an average of their ratios: a
    # mean of RoAS would weight a ₹6 campaign the same as a ₹9,000 one.
    blended = (sales / spend) if spend else 0.0
    # Spend is the sortable figure; revenue and return sit beside it, so the
    # row says what was put in, what came back, and the ratio between them.
    items = [
        {
            "label": c.name or str(c.campaign_id),
            "value": round(c.budget_consumed),
            "unit": "INR",
            "note": (
                f"₹{round(c.ad_sales):,} revenue · {c.roas:.2f}× RoAS"
            ),
        }
        for c in sorted(weak, key=lambda c: -c.budget_consumed)
    ]

    return [
        {
            "id": "ads-below-breakeven",
            "type": "issue",
            "severity": "high" if shortfall >= 50_000 else "medium",
            "title": f"{len(weak)} campaigns below break-even return",
            "what": (
                f"{len(weak)} campaigns returned {blended:.2f}× last week — "
                f"₹{round(spend):,} spent for ₹{round(sales):,} back. Pausing or "
                "re-bidding them stops the spend that is not coming back."
            ),
            "where": {"campaigns": len(weak)},
            "impact": {
                "type": "inefficient_spend",
                "value": shortfall,
                "unit": "INR",
                "confidence": "high",
            }
            if shortfall
            else None,
            "evidence": [
                {"metric": "campaigns_below_1x", "value": len(weak), "unit": "count"},
                {"metric": "spend", "value": round(spend), "unit": "INR"},
                {"metric": "ad_sales", "value": round(sales), "unit": "INR"},
                {"metric": "blended_roas", "value": round(blended, 2)},
            ],
            "items": items,
            "item_label": "Spend",
            "source": "Blinkit ads",
            "method": (
                "Campaigns that spent in the window and were credited with less "
                "in sales than they cost, before cost of goods. Banner and shelf "
                "campaigns are excluded: Blinkit attributes no sales to them, so "
                "a return cannot be measured."
            ),
            "href": "/ads?max_roas=1",
            "cta": "Open Ads",
            "as_of": f"{start} to {end}",
        }
    ]


async def _underspend(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> list[dict]:
    """Active campaigns spending well under their daily budget.

    Paced against the DAILY BUDGET across the window, not against a campaign
    flight: Blinkit gives us no start or end date, so "ahead of schedule" is not
    something we can know. Under-use of a standing daily budget is.
    """
    from app.services import ads_service
    from app.schemas.common import Pagination

    page = await ads_service.get_campaigns(
        session,
        tenant_id=tenant_id,
        pagination=Pagination(page=1, limit=200),
        start=start,
        end=end,
        marketplaces=None,
        status="ACTIVE",
        sort="spend",
        order="desc",
        recent_only=True,
    )
    days = max(1, (end - start).days + 1)
    rows = []
    for c in page.items:
        budget = (c.daily_budget or 0) * days
        if budget <= 0:
            continue
        used = (c.budget_consumed or 0) / budget
        if used >= UNDERSPEND_RATIO:
            continue
        rows.append((c, budget, used))
    if not rows:
        return []

    rows.sort(key=lambda r: r[1] - (r[0].budget_consumed or 0), reverse=True)
    unspent = round(sum(b - (c.budget_consumed or 0) for c, b, _ in rows))

    return [
        {
            "id": "ads-underspend",
            "type": "opportunity",
            "severity": "medium",
            "title": f"{len(rows)} campaigns under-spending their budget",
            "what": (
                f"{len(rows)} active campaigns used less than "
                f"{UNDERSPEND_RATIO * 100:.0f}% of their daily budget. Raising "
                "bids or widening targeting puts the rest to work."
            ),
            "where": {"campaigns": len(rows)},
            "impact": {
                "type": "inefficient_spend",
                "value": unspent,
                "unit": "INR",
                "confidence": "high",
            },
            "evidence": [
                {"metric": "campaigns", "value": len(rows), "unit": "count"},
                {"metric": "budget_unspent", "value": unspent, "unit": "INR"},
            ],
            "items": [
                {
                    "label": c.name or str(c.campaign_id),
                    "value": round(used * 100),
                    "unit": "percent",
                }
                for c, b, used in rows
            ],
            "item_label": "Budget utilisation",
            "source": "Blinkit ads",
            "method": (
                "Spend against the daily budget across the selected window. "
                "Blinkit provides no campaign start or end date, so this is "
                "under-use of a standing budget, not pace against a flight."
            ),
            "href": "/ads",
            "cta": "Open Ads",
            "as_of": f"{start} to {end}",
        }
    ]


async def _active_campaigns(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
):
    """Active campaigns as the marketplace last reported them.

    `recent_only` matters more than it looks: without it the list carries rows
    last scraped in July, and four of them hold budgets big enough to dominate
    any figure built from this.
    """
    from app.services import ads_service
    from app.schemas.common import Pagination

    page = await ads_service.get_campaigns(
        session,
        tenant_id=tenant_id,
        pagination=Pagination(page=1, limit=200),
        start=start,
        end=end,
        marketplaces=None,
        status="ACTIVE",
        sort="spend",
        order="desc",
        recent_only=True,
    )
    return page.items


async def _capped(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Campaigns that spent their whole budget — they stopped because the money
    ran out, not because demand did."""
    days = max(1, (end - start).days + 1)
    rows = []
    for c in await _active_campaigns(
        session, tenant_id=tenant_id, start=start, end=end
    ):
        budget = (c.daily_budget or 0) * days
        spent = c.budget_consumed or 0
        if budget <= 0 or spent < budget * CAPPED_RATIO:
            continue
        rows.append((c, budget, spent / budget))
    if not rows:
        return []

    rows.sort(key=lambda r: -(r[0].budget_consumed or 0))
    return [
        {
            "id": "ads-capped",
            "type": "opportunity",
            "severity": "medium",
            "title": f"{len(rows)} campaigns exhausted their budget",
            "what": (
                f"{len(rows)} campaigns spent effectively all of their budget. "
                "They stopped on money rather than demand, so raising the budget "
                "would buy more of what they were already winning."
            ),
            "where": {"campaigns": len(rows)},
            "evidence": [
                {"metric": "campaigns", "value": len(rows), "unit": "count"},
            ],
            "items": [
                {
                    "label": c.name or str(c.campaign_id),
                    "value": round(c.budget_consumed or 0),
                    "unit": "INR",
                    "note": (
                        f"{used * 100:.0f}% of budget · {c.roas:.2f}x return"
                        if c.roas
                        else f"{used * 100:.0f}% of budget"
                    ),
                }
                for c, _, used in rows
            ],
            "item_label": "Spent",
            "source": "Blinkit ads",
            "method": (
                f"Spend at or above {CAPPED_RATIO * 100:.0f}% of the daily budget "
                "across the selected window."
            ),
            "href": "/ads",
            "cta": "Open Ads",
            "as_of": f"{start} to {end}",
        }
    ]


async def _not_running(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Campaigns switched on, funded, and serving nothing at all."""
    rows = [
        c
        for c in await _active_campaigns(
            session, tenant_id=tenant_id, start=start, end=end
        )
        if (c.daily_budget or 0) > 0
        and not (c.budget_consumed or 0)
        and not (c.impressions or 0)
    ]
    if not rows:
        return []

    # When each last actually spent. We cannot see WHY a campaign stopped — a
    # low bid, narrow targeting, an out-of-stock product and a marketplace-side
    # block all look identical from here — but when it last ran is observable,
    # and it separates "never started" from "stopped in June".
    last_spend = {
        cid: when
        for cid, when in (
            await session.execute(
                text(
                    """
                    select campaign_id, max(date)
                    from blinkit_ad_campaign_daily
                    where tenant_id = :tenant and budget_consumed > 0
                    group by campaign_id
                    """
                ),
                {"tenant": tenant_id},
            )
        ).all()
    }

    rows.sort(key=lambda c: -(c.daily_budget or 0))
    idle = round(sum(c.daily_budget or 0 for c in rows))
    return [
        {
            "id": "ads-not-running",
            "type": "issue",
            "severity": "high",
            "title": f"{len(rows)} campaigns are live but not serving",
            "what": (
                f"{len(rows)} campaigns are active with a budget set and "
                "recorded no spend or impressions in this window. When each last "
                "ran is shown below; why they stopped is not something this data "
                "can tell us."
            ),
            "where": {"campaigns": len(rows)},
            "impact": {
                "type": "inefficient_spend",
                "value": idle,
                "unit": "INR",
                "confidence": "high",
            },
            "evidence": [
                {"metric": "campaigns", "value": len(rows), "unit": "count"},
                {"metric": "daily_budget_idle", "value": idle, "unit": "INR"},
            ],
            "items": [
                {
                    "label": c.name or str(c.campaign_id),
                    "value": c.daily_budget,
                    "unit": "INR",
                    "note": (
                        f"last spent {last_spend[c.campaign_id]}"
                        if last_spend.get(c.campaign_id)
                        else "never recorded any spend"
                    ),
                }
                for c in rows
            ],
            "item_label": "Daily budget",
            "source": "Blinkit ads",
            "method": (
                "Campaigns the marketplace reports as ACTIVE with a daily budget, "
                "which recorded neither spend nor impressions in the window. "
                "Campaign records last scraped before the most recent sync are "
                "excluded, since stale rows keep budgets that no longer exist. "
                "The cause is not visible in this data: a low bid, narrow "
                "targeting, an out-of-stock product and a marketplace-side block "
                "all look the same from here."
            ),
            "href": "/ads",
            "cta": "Open Ads",
            "as_of": f"{start} to {end}",
        }
    ]


async def _automations(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[dict]:
    """What the bid, budget and activation automations did on their last day.

    Reported as counts, never as rupees. A bid change and the revenue that
    followed it are not separable in this data — the same day carries price
    moves, stock changes and every competitor's bidding — so a figure here would
    be a guess wearing a currency symbol.

    Dry-run ticks are excluded from the counts. A rule in dry run decided
    something but changed nothing, and counting it as work done would report
    activity the marketplace never saw.
    """
    day = (
        await session.execute(
            text(
                """
                select max(date(timestamp))
                from cm_run_log
                where tenant_id = :tenant
                  and dry_run = false
                  and timestamp >= now() - (:days * interval '1 day')
                """
            ),
            {"tenant": tenant_id, "days": AUTOMATION_LOOKBACK_DAYS},
        )
    ).scalar_one_or_none()
    if not day:
        return []

    rows = (
        await session.execute(
            text(
                """
                select campaign_id, campaign_name, kind, action, count(*) as n
                from cm_run_log
                where tenant_id = :tenant
                  and dry_run = false
                  and date(timestamp) = :day
                group by campaign_id, campaign_name, kind, action
                """
            ),
            {"tenant": tenant_id, "day": day},
        )
    ).all()
    if not rows:
        return []

    # The latest decision on each campaign, which is the one line that explains
    # where its bid ended up. The engine already writes these for people to read.
    latest = {
        cid: reason
        for cid, reason in (
            await session.execute(
                text(
                    """
                    select distinct on (campaign_id) campaign_id, reason
                    from cm_run_log
                    where tenant_id = :tenant
                      and dry_run = false
                      and date(timestamp) = :day
                      and reason is not null
                    order by campaign_id, timestamp desc
                    """
                ),
                {"tenant": tenant_id, "day": day},
            )
        ).all()
    }

    by_campaign: dict[int | None, dict] = {}
    for r in rows:
        c = by_campaign.setdefault(
            r.campaign_id,
            {"name": r.campaign_name, "checks": 0, "writes": 0, "failed": 0},
        )
        if r.campaign_name and not c["name"]:
            c["name"] = r.campaign_name
        c["checks"] += r.n
        if r.action in AUTOMATION_WRITE_ACTIONS:
            c["writes"] += r.n
        if r.action == AUTOMATION_ERROR_ACTION:
            c["failed"] += r.n

    writes = sum(c["writes"] for c in by_campaign.values())
    checks = sum(c["checks"] for c in by_campaign.values())
    failed = sum(c["failed"] for c in by_campaign.values())
    kinds = sorted({r.kind for r in rows})

    what = (
        f"Automations ran {checks} checks on {day} and changed a value "
        f"{writes} times; the rest were decisions to hold. Covering "
        f"{', '.join(kinds)}."
    )
    if failed:
        what += (
            f" {failed} checks could not complete and left the value "
            "unchanged — each is retried on the next tick."
        )

    items = sorted(
        by_campaign.items(), key=lambda kv: -kv[1]["writes"]
    )
    return [
        {
            "id": "automations-yesterday",
            "type": "issue" if failed else "change",
            "severity": "medium" if failed else "low",
            "title": (
                f"Automations made {writes} "
                f"{'change' if writes == 1 else 'changes'} across "
                f"{len(by_campaign)} "
                f"{'campaign' if len(by_campaign) == 1 else 'campaigns'}"
            ),
            "what": what,
            "where": {"campaigns": len(by_campaign), "platform": "blinkit"},
            "evidence": [
                {"metric": "checks", "value": checks, "unit": "count"},
                {"metric": "values_changed", "value": writes, "unit": "count"},
                {"metric": "checks_failed", "value": failed, "unit": "count"},
            ],
            "items": [
                {
                    "label": c["name"] or str(cid),
                    "count": c["writes"],
                    "total": c["checks"],
                    # Only when something actually failed — a column of zeros
                    # reads as a metric worth watching rather than as nothing.
                    "secondary_count": c["failed"] if failed else None,
                    "secondary_total": c["checks"] if failed else None,
                    "note": latest.get(cid),
                }
                for cid, c in items
            ],
            "item_label": "Changed",
            "item_secondary_label": "Failed" if failed else None,
            "source": "Campaign automation run log",
            "method": (
                "Every automation tick on the most recent day it ran, live runs "
                "only. A change is a tick that wrote a new bid, budget or status; "
                "a hold is the automation deciding the current value is right. "
                "The note is that campaign's latest decision, in the engine's own "
                "words. No revenue figure is attached: a bid change cannot be "
                "separated from everything else that moved the same day."
            ),
            "href": "/ads/automation",
            "cta": "Open Ad Automation",
            "as_of": str(day),
        }
    ]


async def _visibility(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> list[dict]:
    """Share of voice against the previous window. Reported in percentage points —
    no rupee value, because nothing here connects a rank to incremental revenue."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return []

    sov, _ = await _market_agg(
        session, own_brands=own, start=start, end=end, marketplaces=None
    )
    prev_sov, _ = await _market_agg(
        session, own_brands=own, start=prev_start, end=prev_end, marketplaces=None
    )
    if sov is None or prev_sov is None:
        return []

    move = sov - prev_sov
    if abs(move) < SOV_MIN_MOVE_PP:
        return []

    falling = move < 0
    return [
        {
            "id": "visibility-move",
            "type": "issue" if falling else "win",
            "severity": "medium" if falling else "low",
            "title": (
                f"Search visibility declined {abs(move):.1f}pp"
                if falling
                else f"Search visibility improved {move:.1f}pp"
            ),
            "what": (
                f"Search visibility moved from {prev_sov:.1f}% to {sov:.1f}% against "
                "the window before. Worth checking which keywords moved."
            ),
            "where": {},
            "impact": {
                "type": "visibility",
                "value": round(move, 1),
                "unit": "percentage_points",
                "confidence": "high",
            },
            "evidence": [
                {
                    "metric": "share_of_voice",
                    "current": round(sov, 1),
                    "baseline": round(prev_sov, 1),
                    "change": round(move, 1),
                    "unit": "percent",
                    "period": f"{start} to {end}",
                }
            ],
            "source": "Public search scrape",
            "method": (
                "Share of voice for own brands across tracked keywords, this "
                "window against the one before. No revenue figure is attached: we "
                "have no validated model linking rank to revenue."
            ),
            "href": "/competition",
            "cta": "See keywords",
            "as_of": f"{start} to {end}",
        }
    ]


async def get_insights(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> list[dict]:
    """Every generator, ranked. An empty list means nothing needs attention."""
    insights: list[dict] = []
    insights += await _fill_loss(session, tenant_id=tenant_id)
    insights += await _availability(session, tenant_id=tenant_id)
    insights += await _ads(session, tenant_id=tenant_id, start=start, end=end)
    insights += await _underspend(
        session, tenant_id=tenant_id, start=start, end=end
    )
    insights += await _capped(session, tenant_id=tenant_id, start=start, end=end)
    insights += await _not_running(
        session, tenant_id=tenant_id, start=start, end=end
    )
    insights += await _automations(session, tenant_id=tenant_id)
    insights += await _visibility(
        session,
        tenant_id=tenant_id,
        start=start,
        end=end,
        prev_start=prev_start,
        prev_end=prev_end,
    )
    return sorted(insights, key=_rank_key)
