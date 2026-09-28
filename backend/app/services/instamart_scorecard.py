"""Instamart-side reads for the Scorecard page.

Same reasoning as `zepto_scorecard.py`: Instamart publishes no seller
scorecard, so every figure here is DERIVED at read time from the Supply
Portal PO tables (`instamart_po` / `instamart_po_item`, see
`app/models/instamart_po.py`). This module adds no tables and needs no
migration.

TWO STRUCTURAL DIFFERENCES FROM ZEPTO
======================================
1. **No separate GRN document.** Zepto splits PO / GRN / ASN into three
   documents joined by po_id; Instamart's `searchPurchaseOrder` puts
   `total_quantity` / `pending_quantity` / `grn_quantity` directly on the PO
   header row. Fill rate needs no join at the header level — only the
   value-weighted figures (which need `instamart_po_item`'s per-line cost)
   do.

2. **No receipt-EVENT date, so weeks bucket on when the PO was raised, not
   a receipt date.** Zepto's `zepto_grn.grn_date` is a real per-receipt
   event date, so its weeks mean "the week something arrived." Instamart's
   PO only carries a raised date and `completed_date` (set once, only when
   the WHOLE po finishes) — there is no per-quantity received-on date
   anywhere. So a week here means "the week the PO was raised," an honest
   proxy, not the same measurement Zepto's week is. `grn_quantity` is still
   a live, correct CURRENT count (this is a snapshot table, re-scraped over
   time), so the WEEK label is the only place this shows up, not the
   fill-rate numbers themselves.

   ⚠️ "Raised" is `created_at` (IST), NOT `po_date`. Verified live
   2026-09-25 against all 2053 scraped POs: `po_date` is exactly one
   calendar day behind `created_at` (IST), 100% of the time — a real
   Instamart business field (likely a batch/cutoff date), not the creation
   timestamp. A user cross-checked our week buckets against Instamart's own
   bulk-export CSV and found POs a day off and some missing from their true
   week. `_RAISED_DATE`/`_RAISED_DATE_P` below convert `created_at` (UTC)
   to its IST calendar date — that's what matches the portal's own
   `PoCreatedAt` column, and what every query in this module uses now.

WHAT INSTAMART CANNOT HAVE
===========================
`manufacturer_rank` (not published — same gap as Zepto) and `ship_pct`/
`accept_pct` (no ASN-equivalent document exists in the Supply Portal API —
Zepto-only, see that module's docstring). Both omitted from responses
entirely rather than sent as null, following the same convention.

PER-UNIT COST IS DERIVED, NOT STORED
======================================
`instamart_po_item.line_cost_excluding_tax` is a LINE TOTAL despite its API
name (verified live 2026-09-25 — see the model's docstring), so every query
below divides it by `qty` to get a per-unit rate before using it for
value-weighted figures. `qty > 0` is required everywhere this happens to
avoid a division by zero on a malformed line.

⚠️ `instamart_po_item.pending_qty` IS NOT TRUSTWORTHY ONCE A PO CLOSES
==========================================================================
Verified live 2026-09-25 (same finding as `instamart_po_service.py`, see its
docstring for the full detail): for every one of 675 closed POs whose HEADER
shows a real shortfall, every line's `pending_qty` is 0 — Instamart resets it
to 0 on settlement regardless of what actually arrived. The header fields
(`total_quantity`, `grn_quantity`) stay correct; only line-level detail is
lost. `_LINE_SHORT` below trusts `pending_qty` while a PO is open
(STATUS_CONFIRMED — verified genuinely granular there, not just proportional
to `qty`) and falls back to allocating the header's shortfall across lines
by each line's share of `qty` once it's closed.
"""
import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.schemas.common import Page
from app.schemas.scorecard import FacilityPoRow, FacilityRow, KeySkuRow
from app.services.analytics_service import _metric

SLUG = "instamart"

# A per-line shortfall quantity: real while the PO is open, a proportional
# estimate from the (trustworthy) header once it's closed — see the module
# docstring's warning. Used wherever a query below needs "how much of this
# LINE is short", never assume `i.pending_qty` alone is safe to use.
_LINE_SHORT = (
    "(case when i.received_qty is not null then i.qty - i.received_qty "
    "when p.status = 'STATUS_CONFIRMED' then i.pending_qty "
    "else i.qty * (p.total_quantity - p.grn_quantity)::numeric "
    "/ nullif(p.total_quantity, 0) end)"
)

# "When the PO was raised" — see the module docstring's warning: this is
# `created_at` (IST calendar date), NOT the `po_date` column. Two spellings
# for the two ways this module joins instamart_po: unqualified (no alias)
# and aliased `p.` (joined against instamart_po_item as `i`).
_RAISED_DATE = "(created_at + interval '5 hours 30 minutes')::date"
_RAISED_DATE_P = "(p.created_at + interval '5 hours 30 minutes')::date"


def wants_instamart(marketplaces: list[str] | None) -> bool:
    return marketplaces is None or SLUG in marketplaces


_WEEKLY = f"""
select date_trunc('week', {_RAISED_DATE})::date         as from_date,
       count(*)                                        as receipts,
       coalesce(sum(total_quantity), 0)                as total_po_quantity,
       coalesce(sum(grn_quantity), 0)                   as total_grn_quantity,
       round((100.0 * sum(grn_quantity)
              / nullif(sum(total_quantity), 0))::numeric, 2) as fill_rate
from instamart_po
where tenant_id = :t and created_at is not null
group by 1
order by 1 desc
"""

_WEEKLY_VALUE = f"""
select date_trunc('week', {_RAISED_DATE_P})::date as from_date,
       round(sum({_LINE_SHORT} * (i.line_cost_excluding_tax / nullif(i.qty, 0)))::numeric, 2)
           as potential_loss,
       round((100.0 * sum((i.qty - {_LINE_SHORT}) * (i.line_cost_excluding_tax / nullif(i.qty, 0)))
              / nullif(sum(i.line_cost_excluding_tax), 0))::numeric, 2)
           as weighted_fill_rate_percent
from instamart_po_item i
join instamart_po p on p.purchase_order_id = i.purchase_order_id and p.tenant_id = i.tenant_id
where i.tenant_id = :t and i.qty > 0 and p.created_at is not null
group by 1
"""

_WEEKLY_GMV = """
select date_trunc('week', date)::date as from_date,
       round(coalesce(sum(gmv), 0)::numeric, 2) as total_gmv
from instamart_seller_store_daily
where tenant_id = :t
group by 1
"""

# category_id lives directly on the PO line, unlike Zepto (which has to join
# to a sales table by product_variant_id to get one at all).
_WEEKLY_CATEGORIES = f"""
select date_trunc('week', {_RAISED_DATE_P})::date as from_date,
       coalesce(i.category_id, 'Uncategorized') as proxy_category,
       count(distinct i.external_item_code) as skus,
       sum(i.qty)                as total_po_quantity,
       sum(i.qty - {_LINE_SHORT}) as total_grn_quantity,
       round((100.0 * sum(i.qty - {_LINE_SHORT})
              / nullif(sum(i.qty), 0))::numeric, 2)             as fill_rate,
       round(sum({_LINE_SHORT} * (i.line_cost_excluding_tax / nullif(i.qty, 0)))::numeric, 2)
                                                                  as potential_loss
from instamart_po_item i
join instamart_po p on p.purchase_order_id = i.purchase_order_id and p.tenant_id = i.tenant_id
where i.tenant_id = :t and i.qty > 0 and p.created_at is not null
group by 1, 2
order by 1 desc, total_po_quantity desc
"""


async def _weeks_map(session: AsyncSession, tenant_id: uuid.UUID) -> dict[date, dict]:
    p = {"t": tenant_id}
    out: dict[date, dict] = {}
    for row in (await session.execute(text(_WEEKLY), p)).mappings():
        out[row["from_date"]] = dict(row)
    for sql in (_WEEKLY_VALUE, _WEEKLY_GMV):
        for row in (await session.execute(text(sql), p)).mappings():
            if row["from_date"] in out:
                out[row["from_date"]].update(
                    {k: v for k, v in row.items() if k != "from_date"}
                )
    return out


async def _categories(
    session: AsyncSession, tenant_id: uuid.UUID
) -> dict[date, list[dict]]:
    out: dict[date, list[dict]] = {}
    for row in (
        await session.execute(text(_WEEKLY_CATEGORIES), {"t": tenant_id})
    ).mappings():
        out.setdefault(row["from_date"], []).append(
            {k: v for k, v in row.items() if k != "from_date"}
        )
    return out


async def get_weeks(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[date]:
    """Weeks with a PO raised, newest first."""
    rows = await session.execute(
        text(
            f"select distinct date_trunc('week', {_RAISED_DATE})::date d "
            "from instamart_po where tenant_id = :t and created_at is not null "
            "order by d desc"
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
    Unlike Zepto, there is no `ship_pct`/`accept_pct` (no ASN equivalent).
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
    best = max(cats, key=lambda c: c["fill_rate"] or 0) if cats else None

    return {
        "from_date": cur_key,
        "prev_from_date": prev_key,
        "overall": {k: cur.get(k) for k in _METRIC_KEYS},
        "metrics": {k: _metric(cur.get(k), prev.get(k)) for k in _METRIC_KEYS},
        "best_category": best,
        "categories": cats,
    }


async def get_trend(
    session: AsyncSession, *, tenant_id: uuid.UUID, weeks: int = 12
) -> list[dict]:
    """Oldest-first series for the trend chart, mirroring Blinkit/Zepto's shape."""
    all_weeks = await _weeks_map(session, tenant_id)
    out = []
    for w in sorted(all_weeks)[-weeks:]:
        row = all_weeks[w]
        out.append(
            {
                "from_date": w,
                **{k: row.get(k) for k in _METRIC_KEYS},
                "manufacturer_rank": None,  # never published by Instamart
            }
        )
    return out


_FACILITIES = f"""
with value as (
    select p.facility_name,
           sum({_LINE_SHORT} * (i.line_cost_excluding_tax / nullif(i.qty, 0))) as potential_loss,
           sum((i.qty - {_LINE_SHORT}) * (i.line_cost_excluding_tax / nullif(i.qty, 0))) as received_value,
           sum(i.line_cost_excluding_tax) as ordered_value
    from instamart_po_item i
    join instamart_po p on p.purchase_order_id = i.purchase_order_id and p.tenant_id = i.tenant_id
    where i.tenant_id = :t and i.qty > 0
      and (cast(:week as date) is null
           or date_trunc('week', {_RAISED_DATE_P})::date = cast(:week as date))
    group by p.facility_name
)
select p.facility_name                                 as facility_id,
       p.facility_name                                 as facility_name,
       coalesce(sum(p.total_quantity), 0)               as total_po_quantity,
       coalesce(sum(p.grn_quantity), 0)                 as total_grn_quantity,
       round((100.0 * sum(p.grn_quantity)
              / nullif(sum(p.total_quantity), 0))::numeric, 2) as fill_rate,
       round(coalesce(max(v.potential_loss), 0)::numeric, 2)   as potential_loss,
       round((100.0 * max(v.received_value)
              / nullif(max(v.ordered_value), 0))::numeric, 2)
                                                         as weighted_fill_rate_percent
from instamart_po p
left join value v on v.facility_name = p.facility_name
where p.tenant_id = :t and p.facility_name is not null
  and (cast(:week as date) is null
       or date_trunc('week', {_RAISED_DATE_P})::date = cast(:week as date))
group by p.facility_name
order by coalesce(max(v.potential_loss), 0) desc,
         (coalesce(sum(p.total_quantity), 0) - coalesce(sum(p.grn_quantity), 0)) desc
"""


async def get_facilities(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    from_date: date | None = None,
) -> Page[FacilityRow]:
    """Per-facility fill and loss, most expensive shortfall first.

    Instamart's PO carries no separate city field (unlike Zepto's), so
    `city_name` stays null rather than guessing one out of `facility_name`.
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
                city_name=None,
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


_KEY_SKUS = f"""
select i.external_item_code                             as item_id,
       max(i.description)                                as item_name,
       max(i.category_id)                                as proxy_category,
       round(sum({_LINE_SHORT} * (i.line_cost_excluding_tax / nullif(i.qty, 0)))::numeric, 2)
           as potential_loss,
       coalesce(round(sum({_LINE_SHORT})), 0)              as units_short
from instamart_po_item i
join instamart_po p on p.purchase_order_id = i.purchase_order_id and p.tenant_id = i.tenant_id
where i.tenant_id = :t and i.qty > 0
  and (cast(:week as date) is null
       or date_trunc('week', {_RAISED_DATE_P})::date = cast(:week as date))
group by i.external_item_code
order by potential_loss desc
"""


async def get_key_skus(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    from_date: date | None = None,
) -> Page[KeySkuRow]:
    """SKUs ranked by rupees left on the table — units short x per-unit cost.

    Priced at COST (derived `line_cost_excluding_tax / qty`), not MRP —
    same reasoning as Zepto: cost is what Instamart would have paid, and the
    retail margin was never the vendor's to lose. No UPC is captured in the
    Supply Portal response, so that field stays null.
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
                upc=None,
                variant_description=None,
                proxy_category=r["proxy_category"],
                potential_loss=float(r["potential_loss"] or 0),
                total_gmv=None,
                units_short=int(r["units_short"] or 0),
            )
            for r in page
        ],
        total,
        pagination,
    )


_FACILITY_POS = f"""
select p.purchase_order_id as po_number,
       p.status             as po_state,
       {_RAISED_DATE_P}     as issue_date,
       p.total_quantity     as total_units_ordered,
       p.value              as total_po_amount,
       p.grn_quantity       as total_grn_quantity
from instamart_po p
where p.tenant_id = :t and p.facility_name = :facility
order by {_RAISED_DATE_P} desc nulls last
"""


async def get_facility_pos(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    facility_id: str,
    pagination: Pagination,
) -> Page[FacilityPoRow]:
    """POs behind one facility's shortfall — the drill-down. Not week-scoped,
    matching Blinkit/Zepto: a bad week traces back to POs raised before it."""
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
