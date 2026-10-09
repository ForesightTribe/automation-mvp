"""Instamart-side reads for the Products page.

Kept out of `product_service.py` for the same reason Zepto is: the sources are
shaped differently. Blinkit has one item x city x day sales table plus an SOH
feed; Zepto has a per-SKU window table carrying its own stock; Instamart has
sales at day x store x item with **no stock in the private feed at all**.

WHERE STOCK COMES FROM, AND WHY IT IS JOINED BY NAME
====================================================
The Brand Portal's sales report carries no inventory, so shelf stock comes from
the PUBLIC own-SKU scrape (`sku_snapshots`) — the same data the Inventory page
uses. The two sides do not share a product id:

    private sales report : ITEM_CODE, numeric   e.g. "42609"
    public search API    : spinId, 10-char      e.g. "AEYU74I37R"

Nothing we can fetch maps one to the other, but both sides carry Instamart's own
`product_name` and pack string verbatim, and those DO match exactly — checked
2026-09-23: 7/7 selling SKUs joined on (lower(trim(name)), lower(trim(pack))).
So the join is on name+pack; a SKU that fails to match is warned about loudly
(see below).

AN UNMATCHED SKU IS LOGGED, NEVER SILENT
========================================
`product_service.cover_status` treats `frontend_qty <= 0` as OUT OF STOCK, and
`ProductListRow.frontend_qty` is a required int, so there is no "unknown" to
report. An unmatched SKU would therefore read as out-of-stock while selling
fine — the most misleading answer available. Nothing hits this today (7/7
match), so rather than invent a status the UI cannot render, every miss is
WARNED with the name and pack that failed to join. If that warning ever appears,
fix the mapping; do not let the row stand.

STOCK IS AS-OF ITS OWN SCRAPE, NOT THE SALES WINDOW
===================================================
Stock is a forward-only "now" figure: the latest public scrape is the only
meaningful value, so it is read from the most recent snapshot regardless of the
sales window. Scoping it to the window instead would report 0 — and therefore
"out of stock" — for every window that happens not to contain an inventory
scrape, which is a reporting artefact, not a fact about the shelf.
"""
import uuid
from datetime import date, datetime, time

from sqlalchemy import func, or_ as sa_or, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instamart_po import InstamartPO, InstamartPOItem
from app.models.instamart_seller import InstamartSellerStoreDaily as Store
from app.models.search import SkuSnapshot
from app.utils.logger import logger

# Which marketplace slug routes to these tables.
SLUG = "instamart"


def wants_instamart(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Instamart."""
    return marketplaces is None or SLUG in marketplaces


def _conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    return [Store.tenant_id == tenant_id, Store.date >= start, Store.date <= end]


def _key(name: str | None, pack: str | None) -> tuple[str, str]:
    """The join key both planes agree on. Lowercased and stripped because the
    public side keeps Instamart's raw pack string and the private side its own
    VARIANT column, which differ only in whitespace and case."""
    return ((name or "").strip().lower(), (pack or "").strip().lower())


async def _latest_stock_by_name(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> dict[tuple[str, str], int]:
    """(name, pack) -> shelf units on the most recent own-SKU scrape.

    Summed across stores: one row per store per SKU, so the total is the units
    sitting on shelves across the scraped city. Deliberately NOT window-scoped —
    see the module docstring.
    """
    latest = (
        await session.execute(
            select(func.max(func.date(SkuSnapshot.scraped_at))).where(
                SkuSnapshot.tenant_id == tenant_id,
                SkuSnapshot.mp_slug == SLUG,
            )
        )
    ).scalar()
    if latest is None:
        return {}

    rows = (
        await session.execute(
            select(
                SkuSnapshot.product_name,
                SkuSnapshot.pack_raw,
                func.coalesce(func.sum(SkuSnapshot.inventory), 0),
            )
            .where(
                SkuSnapshot.tenant_id == tenant_id,
                SkuSnapshot.mp_slug == SLUG,
                func.date(SkuSnapshot.scraped_at) == latest,
            )
            .group_by(SkuSnapshot.product_name, SkuSnapshot.pack_raw)
        )
    ).all()
    return {_key(name, pack): int(qty) for name, pack, qty in rows}


async def list_agg(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    search: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """One dict per SKU: window sales summed over every store, plus shelf stock.

    Mirrors the shape `product_service.get_products` builds its rows from, so it
    can extend its own list and run one sort/paginate over all marketplaces.

    A SKU with no sales in the window is absent, not zero — the report only
    contains rows where something sold, the same as Blinkit and Zepto.
    """
    conds = _conds(tenant_id, start, end)
    if search:
        conds.append(Store.product_name.ilike(f"%{search}%"))
    if category:
        conds.append(
            func.coalesce(Store.l2_category, Store.l1_category) == category
        )

    rows = (
        await session.execute(
            select(
                Store.item_code,
                func.max(Store.product_name),
                func.max(Store.variant),
                func.max(Store.l2_category),
                func.max(Store.l1_category),
                func.coalesce(func.sum(Store.gmv), 0.0),
                func.coalesce(func.sum(Store.units_sold), 0),
                func.max(Store.date),
            )
            .where(*conds)
            .group_by(Store.item_code)
        )
    ).all()

    stock = await _latest_stock_by_name(session, tenant_id=tenant_id)

    out: list[dict] = []
    for code, name, variant, l2, l1, rev, units, last in rows:
        qty = stock.get(_key(name, variant))
        if qty is None:
            # Loud, because the row that follows will read as out-of-stock.
            logger.warning(
                f"Instamart products: no public stock matched "
                f"{name!r} ({variant!r}) — item_code {code}. It will render as "
                f"out of stock; fix the name/pack join."
            )
            qty = 0
        out.append({
            "item_id": code,
            # The pack rides in the name so the list distinguishes two variants
            # of one product, which is how Instamart itself lists them.
            "item_name": f"{name} ({variant})" if name and variant else name,
            "category": l2 or l1,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
            "last_sold": last,
            "frontend_qty": qty,
            # Instamart exposes no warehouse/backend split, only shelf stock.
            "backend_qty": 0,
        })
    return out


async def categories(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[str]:
    """Distinct categories for the filter dropdown, matching `list_agg`."""
    rows = (
        await session.execute(
            select(func.coalesce(Store.l2_category, Store.l1_category))
            .where(*_conds(tenant_id, start, end))
            .distinct()
        )
    ).scalars().all()
    return sorted(c for c in rows if c)


async def detail_agg(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: str,
    start: date,
    end: date,
) -> dict | None:
    """Totals, daily trend and stock for one SKU, in the shape the Blinkit
    branch of `product_service.get_product_detail` returns.

    `item_id` is Instamart's ITEM_CODE — what `list_agg` put in the list, so
    what the UI navigates with. None when the SKU had no sales in the window, so
    the route 404s exactly as it does for the other marketplaces.
    """
    conds = [*_conds(tenant_id, start, end), Store.item_code == item_id]

    name, variant, l2, l1, rev, units, count = (
        await session.execute(
            select(
                func.max(Store.product_name),
                func.max(Store.variant),
                func.max(Store.l2_category),
                func.max(Store.l1_category),
                func.coalesce(func.sum(Store.gmv), 0.0),
                func.coalesce(func.sum(Store.units_sold), 0),
                func.count(),
            ).where(*conds)
        )
    ).one()
    if count == 0:
        return None

    day_rows = (
        await session.execute(
            select(
                Store.date,
                func.coalesce(func.sum(Store.units_sold), 0),
                func.coalesce(func.sum(Store.gmv), 0.0),
            )
            .where(*conds)
            .group_by(Store.date)
            .order_by(Store.date)
        )
    ).all()
    trend = [
        {"date": d, "units_sold": int(u), "revenue": round(float(g), 2)}
        for d, u, g in day_rows
    ]

    # One stock reading per public own-SKU scrape date. Usually a single point:
    # the public scrape is not (yet) daily, so this is a series of one until it
    # runs on a schedule. Shown as a series anyway so the chart fills in by
    # itself once it does.
    stock_rows = (
        await session.execute(
            select(
                func.date(SkuSnapshot.scraped_at),
                func.coalesce(func.sum(SkuSnapshot.inventory), 0),
            )
            .where(
                SkuSnapshot.tenant_id == tenant_id,
                SkuSnapshot.mp_slug == SLUG,
                func.lower(func.trim(SkuSnapshot.product_name)) == (name or "").strip().lower(),
                func.lower(func.trim(SkuSnapshot.pack_raw)) == (variant or "").strip().lower(),
            )
            .group_by(func.date(SkuSnapshot.scraped_at))
            .order_by(func.date(SkuSnapshot.scraped_at))
        )
    ).all()
    stock_trend = [
        {"date": d, "backend_qty": 0, "frontend_qty": int(q)} for d, q in stock_rows
    ]
    stock = None
    if stock_trend:
        last = stock_trend[-1]
        stock = {"date": last["date"], "backend_qty": 0,
                 "frontend_qty": last["frontend_qty"]}

    return {
        "item_id": item_id,
        "item_name": f"{name} ({variant})" if name and variant else name,
        "category": l2 or l1,
        "revenue": round(float(rev), 2),
        "units_sold": int(units),
        "stock": stock,
        "frontend_qty": stock["frontend_qty"] if stock else 0,
        "trend": trend,
        "stock_trend": stock_trend,
        # Instamart publishes neither a warehouse split nor a lost-sales figure.
        "facilities": [],
        "potential_loss": None,
    }


async def cities(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: str,
    start: date,
    end: date,
) -> list[dict]:
    """Per-city units and revenue for one SKU — genuinely per-SKU, because the
    report carries the store (and therefore its city) on every sales row."""
    rows = (
        await session.execute(
            select(
                Store.city,
                func.coalesce(func.sum(Store.units_sold), 0),
                func.coalesce(func.sum(Store.gmv), 0.0),
            )
            .where(*_conds(tenant_id, start, end), Store.item_code == item_id,
                   Store.city.isnot(None))
            .group_by(Store.city)
            .order_by(func.sum(Store.gmv).desc())
        )
    ).all()
    return [
        {"city": city, "units_sold": int(u), "revenue": round(float(g), 2)}
        for city, u, g in rows
    ]


async def stores(
    session: AsyncSession, *, tenant_id: uuid.UUID, item_id: str, limit: int = 50
) -> list[dict]:
    """Per-STORE stock for one SKU, shaped like `FacilityStock`.

    Blinkit's "Stock by facility" panel lists backend warehouses. Instamart has
    no warehouse tier at all — it ships from the dark store itself — so the
    equivalent unit here is the store, and `backend_qty` is always 0.

    Reads the most recent own-SKU scrape (not the sales window; stock is a "now"
    figure — see the module docstring). The product is matched by name+pack
    because the private ITEM_CODE and the public spinId do not share an id
    space; the name is looked up from the sales table for this item_id.

    Lowest stock first: the point of the panel is to show where it is running
    out, not where it is comfortable.

    ONLY STORES WHOSE STOCK WE ACTUALLY KNOW ARE LISTED. Instamart reveals depth
    through the cart limit, and for ~5% of rows it gives only a per-order cap
    ("Only N per order") instead of the real remainder ("That's all we have").
    Those rows are IN STOCK with an unknown quantity — so they are left out
    rather than shown as 0, which would put a healthy store at the top of a
    list sorted by scarcity and read as "out of stock". A store reporting
    `in_stock = false` IS listed at 0: that is a real, known fact.
    """
    name_row = (
        await session.execute(
            select(Store.product_name, Store.variant)
            .where(Store.tenant_id == tenant_id, Store.item_code == item_id)
            .limit(1)
        )
    ).first()
    if not name_row:
        return []
    name, pack = name_row

    latest = (
        await session.execute(
            select(func.max(func.date(SkuSnapshot.scraped_at))).where(
                SkuSnapshot.tenant_id == tenant_id, SkuSnapshot.mp_slug == SLUG
            )
        )
    ).scalar()
    if latest is None:
        return []

    rows = (
        await session.execute(
            select(
                SkuSnapshot.merchant_id,
                SkuSnapshot.city,
                func.coalesce(func.sum(SkuSnapshot.inventory), 0),
            )
            .where(
                SkuSnapshot.tenant_id == tenant_id,
                SkuSnapshot.mp_slug == SLUG,
                func.date(SkuSnapshot.scraped_at) == latest,
                func.lower(func.trim(SkuSnapshot.product_name))
                == (name or "").strip().lower(),
                func.lower(func.trim(SkuSnapshot.pack_raw))
                == (pack or "").strip().lower(),
                SkuSnapshot.merchant_id.isnot(None),
                # Known quantity, or a known zero. Never a guessed zero.
                sa_or(
                    SkuSnapshot.inventory.isnot(None),
                    SkuSnapshot.in_stock.is_(False),
                ),
            )
            .group_by(SkuSnapshot.merchant_id, SkuSnapshot.city)
            .order_by(func.coalesce(func.sum(SkuSnapshot.inventory), 0).asc())
            .limit(limit)
        )
    ).all()

    # The area name is the human-readable label a person recognises; it lives on
    # the sales rows, so fill it where this store has sold something.
    areas = dict(
        (
            await session.execute(
                select(Store.store_id, func.max(Store.area_name)).where(
                    Store.tenant_id == tenant_id,
                    Store.store_id.in_([r[0] for r in rows] or [""]),
                ).group_by(Store.store_id)
            )
        ).all()
    )

    return [
        {
            "facility_id": mid,
            "facility_name": (areas.get(mid) or city or mid),
            "backend_qty": 0,
            "frontend_qty": int(qty),
        }
        for mid, city, qty in rows
    ]


async def po_lines(
    session: AsyncSession, *, tenant_id: uuid.UUID, item_id: str,
    offset: int = 0, limit: int = 10,
) -> tuple[list[dict], int]:
    """(rows, total) of PO lines for one SKU, newest order first — the
    Instamart side of the product page's PO history, same shape as
    `zepto_products.po_lines`.

    Matched on `external_item_code`, which is the same ITEM_CODE the sales
    table keys on (verified 2026-10-09: 42609 in both), so no name matching.
    Joined to `instamart_po` for the date, status and facility.

    Received is the bulk-CSV `received_qty` only — never `qty - pending_qty`:
    `pending_qty` resets to 0 once a PO closes (see `InstamartPOItem`), which
    would show every closed PO as fully received. Unsynced lines read "—".
    """
    conds = [
        InstamartPOItem.tenant_id == tenant_id,
        InstamartPOItem.external_item_code == item_id,
    ]
    total = (
        await session.execute(
            select(func.count()).select_from(InstamartPOItem).where(*conds)
        )
    ).scalar_one()

    rows = (
        await session.execute(
            select(
                InstamartPOItem.purchase_order_id,
                InstamartPO.status,
                InstamartPO.po_date,
                InstamartPO.facility_name,
                InstamartPOItem.qty,
                InstamartPOItem.received_qty,
                InstamartPOItem.balanced_qty,
                InstamartPOItem.line_cost_excluding_tax,
            )
            .join(
                InstamartPO,
                (InstamartPO.tenant_id == InstamartPOItem.tenant_id)
                & (InstamartPO.purchase_order_id == InstamartPOItem.purchase_order_id),
                isouter=True,
            )
            .where(*conds)
            .order_by(InstamartPO.po_date.desc().nullslast(),
                      InstamartPOItem.purchase_order_id)
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return (
        [
            {
                "po_number": po_id,
                # "STATUS_CONFIRMED" -> "CONFIRMED"
                "po_state": status.removeprefix("STATUS_") if status else None,
                # The schema wants a datetime; the PO carries a calendar day.
                "issue_date": (
                    datetime.combine(po_date, time.min) if po_date else None
                ),
                "facility_name": facility,
                "units_ordered": qty,
                "received_qty": received,
                "remaining_quantity": balanced,
                # The stored cost is a LINE total (see InstamartPOItem).
                "cost_price": (
                    round(line_cost / qty, 2) if line_cost is not None and qty else None
                ),
                "total_amount": line_cost,
            }
            for (po_id, status, po_date, facility, qty, received,
                 balanced, line_cost) in rows
        ],
        int(total),
    )
