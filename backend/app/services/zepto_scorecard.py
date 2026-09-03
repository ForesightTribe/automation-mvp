"""Zepto-side reads for the Scorecard page.

⚠️ THE ONE STRUCTURAL DIFFERENCE FROM BLINKIT

Blinkit *publishes* a seller scorecard, so `blinkit_scorecard_weekly` /
`_facilities` / `_key_skus` are scraped tables — the numbers arrive ready-made.

**Zepto publishes nothing of the kind.** There is no scorecard page on the seller
portal, so every figure here is DERIVED from the PO tables at read time:

    zepto_grn        po_qty vs grn_qty per receipt  -> fill rate
    zepto_po_items   unit_price per SKU             -> value weighting, loss
    zepto_asn        asn_qty between the two        -> ship vs accept split
    zepto_seller_sales_summary                      -> GMV

That is why this module adds no tables and needs no migration: there is nothing
to store that is not already stored. It also means the numbers move when the PO
data is re-scraped, which the Blinkit ones do not.

────────────────────────────────────────────────────────────────────────────────
WHAT ZEPTO CANNOT HAVE: `manufacturer_rank`

Blinkit tells a supplier it is 123rd overall and 2nd in its category. That needs
every OTHER supplier's fill rate, which only the platform can see. Zepto does not
publish it and it cannot be computed from our own data at any price.

The key is therefore OMITTED from responses rather than sent as null, following
the same convention `overview_service` uses for public-only marketplaces: a
missing key lets the UI say "not published by this marketplace", while a null
renders as a blank where a number should be.

────────────────────────────────────────────────────────────────────────────────
WHAT ZEPTO HAS THAT BLINKIT DOES NOT

Blinkit reports ordered and received, with no shipping step, so a shortfall is
undiagnosable — "we never sent it" and "we sent it and the dock rejected it" look
identical. Zepto exposes the ASN in between, so `ship_pct` / `accept_pct` splits
the loss by whose side it happened on. Measured across 356 deliveries
(Apr-Aug 2026): 100.0% shipped, 70.0% accepted. That single split is the most
actionable number on the page and Blinkit cannot produce it.

────────────────────────────────────────────────────────────────────────────────
WEEK GRAIN

Weeks are Monday-anchored via `date_trunc('week')`, matching Blinkit's
`from_date_ist`, so the page's week picker works identically for both.

A GRN counts in the week it was RECEIVED, not the week its PO was raised — those
differ for 94% of deliveries (usually by one day, occasionally three). Receiving
is the event fill rate is about.
"""
import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.schemas.common import Page
from app.schemas.scorecard import FacilityPoRow, FacilityRow, KeySkuRow
# THE metric packer, not a copy of it. This module used to define its own, whose
# docstring claimed it matched this one and did not: it returned `delta_pct` as a
# PERCENTAGE (36.2) where every other service returns a FRACTION (0.362).
# DeltaBadge multiplies by 100, so the Zepto scorecard rendered "+3620%".
# scorecard_service imports the same function for Blinkit — which is exactly why
# Blinkit was never affected. Import it; never re-implement it.
from app.services.analytics_service import _metric

SLUG = "zepto"


def wants_zepto(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Zepto."""
    return marketplaces is None or SLUG in marketplaces


# One row per week of receipts. `weighted_fill` values each unit at what Zepto
# pays for it, so a shortfall on a Rs 178 cheese counts for more than one on a
# Rs 53 loaf — the same distinction Blinkit draws with
# `weighted_fill_rate_percent`.
_WEEKLY = """
select date_trunc('week', g.grn_date)::date            as from_date,
       count(*)                                        as receipts,
       coalesce(sum(g.po_qty), 0)                      as total_po_quantity,
       coalesce(sum(g.grn_qty), 0)                     as total_grn_quantity,
       round((100.0 * sum(g.grn_qty)
              / nullif(sum(g.po_qty), 0))::numeric, 2) as fill_rate
from zepto_grn g
where g.tenant_id = :t
group by 1
order by 1 desc
"""

# Value-weighted figures come from the LINE ITEMS, not the GRN header: only the
# lines carry unit_price. Joined to the PO for its date, then bucketed by the
# receipt week so both halves of a week line up.
_WEEKLY_VALUE = """
select date_trunc('week', g.grn_date)::date as from_date,
       round(sum((i.po_qty - coalesce(i.grn_qty, 0)) * i.unit_price)::numeric, 2)
           as potential_loss,
       round((100.0 * sum(coalesce(i.grn_qty, 0) * i.unit_price)
              / nullif(sum(i.po_qty * i.unit_price), 0))::numeric, 2)
           as weighted_fill_rate_percent
from zepto_po_items i
join zepto_po  p on p.po_id = i.po_id and p.tenant_id = i.tenant_id
join zepto_grn g on g.po_id = i.po_id and g.tenant_id = i.tenant_id
where i.tenant_id = :t and i.grn_qty is not null
group by 1
"""

_WEEKLY_GMV = """
select date_trunc('week', date)::date as from_date,
       round(coalesce(sum(gmv), 0)::numeric, 2) as total_gmv
from zepto_seller_sales_summary
where tenant_id = :t
group by 1
"""

# Category fill. Zepto's GRN carries no category, and neither do the PO lines —
# but `product_variant_id` is the SAME id `zepto_seller_sales` keys on, so the
# category comes across by joining on it. No name matching, no sku_map bridge.
#
# Grouped on SUBcategory, matching sales_by_category: `categoryName` is one broad
# bucket for this account ("Dairy, Bread & Eggs" covers every SKU), so grouping on
# it yields a single useless row. Subcategory is the level that distinguishes.
_WEEKLY_CATEGORIES = """
-- Bucketed on the RECEIPT week, like every other query here. It used to use
-- p.po_date, which put a category in a different week from the fill rate it
-- was meant to explain: the two dates differ for 94% of deliveries, and the
-- 24-Aug week came out Rs 8,876 apart between the tiles and this panel.
select date_trunc('week', g.grn_date)::date as from_date,
       coalesce(s.subcategory_name, s.category_name, 'Uncategorized') as proxy_category,
       count(distinct i.product_variant_id) as skus,
       sum(i.po_qty)                        as total_po_quantity,
       sum(coalesce(i.grn_qty, 0))          as total_grn_quantity,
       round((100.0 * sum(coalesce(i.grn_qty, 0))
              / nullif(sum(i.po_qty), 0))::numeric, 2)             as fill_rate,
       round(sum((i.po_qty - coalesce(i.grn_qty, 0)) * i.unit_price)::numeric, 2)
                                                                    as potential_loss
from zepto_po_items i
join zepto_po  p on p.po_id = i.po_id and p.tenant_id = i.tenant_id
join zepto_grn g on g.po_id = i.po_id and g.tenant_id = i.tenant_id
left join (select distinct product_variant_id, subcategory_name, category_name
           from zepto_seller_sales where tenant_id = :t) s
  on s.product_variant_id = i.product_variant_id
where i.tenant_id = :t and i.grn_qty is not null
group by 1, 2
order by 1 desc, total_po_quantity desc
"""


# The ship-vs-accept split. Only rows with BOTH an ASN and a GRN can answer it,
# so this is scoped to matched deliveries rather than all receipts.
_WEEKLY_SPLIT = """
select date_trunc('week', g.grn_date)::date as from_date,
       round((100.0 * sum(a.asn_qty) / nullif(sum(a.po_qty), 0))::numeric, 1)
           as ship_pct,
       round((100.0 * sum(g.grn_qty) / nullif(sum(a.asn_qty), 0))::numeric, 1)
           as accept_pct
from zepto_asn a
join zepto_grn g on g.po_id = a.po_id and g.tenant_id = a.tenant_id
where a.tenant_id = :t
group by 1
"""


async def _weeks_map(session: AsyncSession, tenant_id: uuid.UUID) -> dict[date, dict]:
    """Every week's figures, keyed by week start. One pass, four queries."""
    p = {"t": tenant_id}
    out: dict[date, dict] = {}
    for row in (await session.execute(text(_WEEKLY), p)).mappings():
        out[row["from_date"]] = dict(row)
    for sql in (_WEEKLY_VALUE, _WEEKLY_GMV, _WEEKLY_SPLIT):
        for row in (await session.execute(text(sql), p)).mappings():
            # A week can have sales but no receipts (or vice versa); only enrich
            # weeks that already have a fill-rate row, so the page never shows a
            # scorecard week built from GMV alone.
            if row["from_date"] in out:
                out[row["from_date"]].update(
                    {k: v for k, v in row.items() if k != "from_date"}
                )
    return out


async def _categories(
    session: AsyncSession, tenant_id: uuid.UUID
) -> dict[date, list[dict]]:
    """Per-week category rows, keyed by week start."""
    out: dict[date, list[dict]] = {}
    for row in (
        await session.execute(text(_WEEKLY_CATEGORIES), {"t": tenant_id})
    ).mappings():
        out.setdefault(row["from_date"], []).append(
            {k: v for k, v in row.items() if k != "from_date"}
        )
    return out


async def get_weeks(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[date]:
    """Weeks with receipts, newest first — the page's week picker."""
    rows = await session.execute(
        text(
            "select distinct date_trunc('week', grn_date)::date d "
            "from zepto_grn where tenant_id = :t order by d desc"
        ),
        {"t": tenant_id},
    )
    return [r[0] for r in rows.all()]


_METRIC_KEYS = (
    "fill_rate",
    "weighted_fill_rate_percent",
    "potential_loss",
    "total_gmv",
    "total_po_quantity",
    "total_grn_quantity",
)


async def get_weekly(
    session: AsyncSession, *, tenant_id: uuid.UUID, from_date: date | None = None
) -> dict | None:
    """The selected (or latest) week, plus growth against the week before.

    `manufacturer_rank` is absent by design — see the module docstring.
    `ship_pct` / `accept_pct` are extra, and have no Blinkit counterpart.
    """
    weeks = await _weeks_map(session, tenant_id)
    if not weeks:
        return None

    ordered = sorted(weeks, reverse=True)
    if from_date:
        ordered = [w for w in ordered if w <= from_date]
        if not ordered:
            return None

    cur_key = ordered[0]
    prev_key = ordered[1] if len(ordered) > 1 else None
    cur = weeks[cur_key]
    prev = weeks.get(prev_key, {}) if prev_key else {}

    cats = (await _categories(session, tenant_id)).get(cur_key, [])
    # Blinkit's "best category" is its best-RANKED one; with no rank available the
    # honest analogue is the best-performing one we can see — highest fill among
    # categories that actually had orders.
    best = max(cats, key=lambda c: c["fill_rate"] or 0) if cats else None

    return {
        "from_date": cur_key,
        "prev_from_date": prev_key,
        "overall": {k: cur.get(k) for k in _METRIC_KEYS},
        "metrics": {k: _metric(cur.get(k), prev.get(k)) for k in _METRIC_KEYS},
        # Zepto-only: where the shortfall happened.
        "ship_pct": cur.get("ship_pct"),
        "accept_pct": cur.get("accept_pct"),
        # Category comes from the PO lines joined to sales on product_variant_id —
        # see _WEEKLY_CATEGORIES. Bucketed by the PO's week, not the receipt's,
        # because the line items hang off the order.
        "best_category": best,
        "categories": cats,
    }


async def get_trend(
    session: AsyncSession, *, tenant_id: uuid.UUID, weeks: int = 12
) -> list[dict]:
    """Oldest-first series for the trend chart, mirroring the Blinkit shape."""
    all_weeks = await _weeks_map(session, tenant_id)
    out = []
    for w in sorted(all_weeks)[-weeks:]:
        row = all_weeks[w]
        out.append(
            {
                "from_date": w,
                **{k: row.get(k) for k in _METRIC_KEYS},
                "manufacturer_rank": None,  # never published by Zepto
            }
        )
    return out


# Per-warehouse fill AND the rupees behind it.
#
# The value half is a separate aggregate over the line items, joined back on
# location, because unit_price lives only on `zepto_po_items` while the fill
# quantities live on the GRN header. Attempting both in one GROUP BY would
# multiply the header quantities by the number of lines on each PO.
#
# This used to send potential_loss=0.0 and weighted_fill_rate_percent=fill_rate
# as placeholders. A hardcoded zero reads as "this warehouse lost nothing",
# which is the opposite of the truth for the worst ones — HOSKOTE NEW alone is
# ~59% of all shortfall. Both are now real.
_FACILITIES = """
with value as (
    select g.location,
           sum((i.po_qty - coalesce(i.grn_qty, 0)) * i.unit_price) as potential_loss,
           sum(coalesce(i.grn_qty, 0) * i.unit_price)              as received_value,
           sum(i.po_qty * i.unit_price)                            as ordered_value
    from zepto_po_items i
    join zepto_po  p on p.po_id = i.po_id and p.tenant_id = i.tenant_id
    join zepto_grn g on g.po_id = i.po_id and g.tenant_id = i.tenant_id
    where i.tenant_id = :t and i.grn_qty is not null
      and (cast(:week as date) is null
           or date_trunc('week', g.grn_date)::date = cast(:week as date))
    group by g.location
)
select g.location                                       as facility_id,
       g.location                                       as facility_name,
       max(p.city)                                      as city_name,
       coalesce(sum(g.po_qty), 0)                       as total_po_quantity,
       coalesce(sum(g.grn_qty), 0)                      as total_grn_quantity,
       round((100.0 * sum(g.grn_qty)
              / nullif(sum(g.po_qty), 0))::numeric, 2)  as fill_rate,
       round(coalesce(max(v.potential_loss), 0)::numeric, 2) as potential_loss,
       round((100.0 * max(v.received_value)
              / nullif(max(v.ordered_value), 0))::numeric, 2)
                                                        as weighted_fill_rate_percent
from zepto_grn g
left join zepto_po p on p.po_id = g.po_id and p.tenant_id = g.tenant_id
left join value  v on v.location = g.location
where g.tenant_id = :t
  and (cast(:week as date) is null
       or date_trunc('week', g.grn_date)::date = cast(:week as date))
group by g.location
order by coalesce(max(v.potential_loss), 0) desc,
         (coalesce(sum(g.po_qty), 0) - coalesce(sum(g.grn_qty), 0)) desc
"""


async def get_facilities(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    from_date: date | None = None,
) -> Page[FacilityRow]:
    """Per-warehouse fill and loss, most expensive shortfall first.

    Zepto has no facility id separate from the location NAME
    (`KWPL_BLR-FRESH-HOSKOTE NEW`), so the name serves as both. Blinkit's
    numeric `facility_id` has no equivalent.

    Both value figures come from the `value` CTE in the query — a second pass
    over the line items, since only they carry `unit_price`. `potential_loss`
    is null-safe: a warehouse whose POs have no scraped line items yet returns
    0 rather than dropping out of the list.
    """
    rows = (
        await session.execute(
            text(_FACILITIES), {"t": tenant_id, "week": from_date}
        )
    ).mappings().all()

    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(
        [
            FacilityRow(
                facility_id=r["facility_id"] or "",
                facility_name=r["facility_name"],
                city_name=r["city_name"],
                total_po_quantity=int(r["total_po_quantity"]),
                total_grn_quantity=int(r["total_grn_quantity"]),
                fill_rate=float(r["fill_rate"] or 0),
                weighted_fill_rate_percent=float(
                    r["weighted_fill_rate_percent"] or r["fill_rate"] or 0
                ),
                potential_loss=float(r["potential_loss"] or 0),
                manufacturer_rank=None,
            )
            for r in page
        ],
        total,
        pagination,
    )


_KEY_SKUS = """
select i.product_variant_id                              as item_id,
       max(i.sku_name)                                   as item_name,
       max(i.ean_no)                                     as upc,
       -- The SKU's retail subcategory, via the same product_variant_id join
       -- _WEEKLY_CATEGORIES uses. This was `max(i.brand)`, which is the BRAND:
       -- on a single-brand account every row read "Brik Oven", so the column
       -- carried no information at all. Subcategory, not category — Zepto's
       -- `categoryName` is one bucket ("Dairy, Bread & Eggs") covering
       -- everything this account sells.
       max(coalesce(s.subcategory_name, s.category_name, i.brand)) as proxy_category,
       round(sum((i.po_qty - coalesce(i.grn_qty, 0)) * i.unit_price)::numeric, 2)
           as potential_loss,
       coalesce(sum(i.po_qty) - sum(coalesce(i.grn_qty, 0)), 0) as units_short
from zepto_po_items i
join zepto_po  p on p.po_id = i.po_id and p.tenant_id = i.tenant_id
join zepto_grn g on g.po_id = i.po_id and g.tenant_id = i.tenant_id
left join (select distinct product_variant_id, subcategory_name, category_name
           from zepto_seller_sales where tenant_id = :t) s
  on s.product_variant_id = i.product_variant_id
where i.tenant_id = :t and i.grn_qty is not null
  -- Receipt week, not PO week. See the note on _WEEKLY_CATEGORIES: bucketing
  -- these on p.po_date made this panel describe a different set of POs from
  -- the tile directly above it.
  and (cast(:week as date) is null
       or date_trunc('week', g.grn_date)::date = cast(:week as date))
group by i.product_variant_id
order by potential_loss desc
"""


async def get_key_skus(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    from_date: date | None = None,
) -> Page[KeySkuRow]:
    """SKUs ranked by rupees left on the table — units short x what Zepto pays.

    `potential_loss` assumes every short unit would have sold, which is the same
    assumption Blinkit's own figure makes. It is a ceiling, not a certainty, and
    should be described that way to a client.

    Priced at COST (`unit_price`), not MRP: cost is what Zepto would have paid
    the vendor, and the retail margin was never the vendor's to lose.
    """
    rows = (
        await session.execute(text(_KEY_SKUS), {"t": tenant_id, "week": from_date})
    ).mappings().all()

    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(
        [
            KeySkuRow(
                item_id=r["item_id"] or "",
                item_name=r["item_name"],
                upc=r["upc"],
                variant_description=None,
                proxy_category=r["proxy_category"],
                potential_loss=float(r["potential_loss"] or 0),
                # Zepto has no per-SKU GMV worth reporting here, so this stays
                # null and `units_short` carries the figure. See KeySkuRow.
                total_gmv=None,
                units_short=int(r["units_short"] or 0),
            )
            for r in page
        ],
        total,
        pagination,
    )


_FACILITY_POS = """
select p.po_id                          as po_number,
       p.status                         as po_state,
       p.po_date                        as issue_date,
       p.total_qty                      as total_units_ordered,
       p.total_value                    as total_po_amount,
       (select sum(g.grn_qty) from zepto_grn g
         where g.po_id = p.po_id and g.tenant_id = p.tenant_id) as total_grn_quantity
from zepto_po p
where p.tenant_id = :t and p.location = :facility
order by p.po_date desc nulls last
"""


async def get_facility_pos(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    facility_id: str,
    pagination: Pagination,
) -> Page[FacilityPoRow]:
    """POs behind one warehouse's shortfall — the drill-down.

    `total_grn_quantity` is summed from `zepto_grn` rather than read off the PO:
    `zepto_po.total_grn_qty` exists but Zepto returns it null on every row
    (0 of 379 populated, measured 2026-08-31), so anything computed from it
    would be silently empty.

    Deliberately NOT week-scoped, matching Blinkit: a bad week traces back to
    POs raised before it.
    """
    rows = (
        await session.execute(
            text(_FACILITY_POS), {"t": tenant_id, "facility": facility_id}
        )
    ).mappings().all()

    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(
        [
            FacilityPoRow(
                po_number=r["po_number"],
                po_state=r["po_state"],
                issue_date=r["issue_date"],
                total_units_ordered=r["total_units_ordered"],
                total_grn_quantity=r["total_grn_quantity"],
                total_po_amount=r["total_po_amount"],
            )
            for r in page
        ],
        total,
        pagination,
    )
