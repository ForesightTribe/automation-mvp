"""Client-scoped inventory: stock-on-hand (blinkit_soh) and PO fill-rate
(blinkit_scorecard_facilities)."""
import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import Integer, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.utils.time import now_ist
from app.models.blinkit_seller import BlinkitSOH, BlinkitScorecardFacility
from app.models.search import MarketplaceLocation, SkuSnapshot
from app.schemas.common import Page
from app.schemas.inventory import AvailabilityRow, SohRow
from app.services import watchlist_service
from scraper.utils.pack import per_unit_price

SOH = BlinkitSOH
FAC = BlinkitScorecardFacility


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None else None


def _kind_cond(kind: str) -> list:
    """Combo/multipack filter. Combos are stocked selectively, so they're analysed
    apart from singular main SKUs. `main` (default) = singles only, `combo` = combos
    only, `all` = both."""
    if kind == "combo":
        return [SkuSnapshot.is_combo.is_(True)]
    if kind == "all":
        return []
    return [SkuSnapshot.is_combo.is_(False)]


async def get_soh(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    on_date: date | None = None,
) -> Page[SohRow]:
    target = on_date
    if target is None:
        target = (
            await session.execute(
                select(func.max(SOH.date)).where(SOH.tenant_id == tenant_id)
            )
        ).scalar()
    if target is None:
        return Page.build([], 0, pagination)

    cond = [SOH.tenant_id == tenant_id, SOH.date == target]
    total = (
        await session.execute(
            select(func.count(distinct(SOH.item_id))).where(*cond)
        )
    ).scalar_one()

    frontend = func.coalesce(func.sum(SOH.frontend_inv_qty), 0)
    rows = (
        await session.execute(
            select(
                SOH.item_id,
                func.max(SOH.item_name),
                func.coalesce(func.sum(SOH.backend_inv_qty), 0),
                frontend,
                func.count(distinct(SOH.backend_facility_id)),
            )
            .where(*cond)
            .group_by(SOH.item_id)
            .order_by(frontend.asc())  # lowest frontend stock first
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).all()

    items = [
        SohRow(
            item_id=i,
            item_name=n,
            backend_qty=int(b),
            frontend_qty=int(f),
            facilities=int(fac),
            date=target,
        )
        for i, n, b, f, fac in rows
    ]
    return Page.build(items, total, pagination)


async def get_fill_rate(
    session: AsyncSession, *, tenant_id: uuid.UUID, from_date: date | None = None
) -> dict:
    target = from_date
    if target is None:
        target = (
            await session.execute(
                select(func.max(FAC.from_date_ist)).where(FAC.tenant_id == tenant_id)
            )
        ).scalar()
    if target is None:
        return {
            "from_date": None,
            "total_po_quantity": 0,
            "total_grn_quantity": 0,
            "fill_rate": 0.0,
            "potential_loss": 0.0,
            "facilities_count": 0,
        }

    cond = [FAC.tenant_id == tenant_id, FAC.from_date_ist == target]
    po, grn, loss, count = (
        await session.execute(
            select(
                func.coalesce(func.sum(FAC.total_po_quantity), 0),
                func.coalesce(func.sum(FAC.total_grn_quantity), 0),
                func.coalesce(func.sum(FAC.potential_loss), 0.0),
                func.count(),
            ).where(*cond)
        )
    ).one()

    return {
        "from_date": target,
        "total_po_quantity": int(po),
        "total_grn_quantity": int(grn),
        "fill_rate": round(grn / po, 4) if po else 0.0,
        "potential_loss": round(float(loss), 2),
        "facilities_count": int(count),
    }


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive calendar dates -> the half-open datetime window [start 00:00,
    end+1 00:00). Public metrics filter on this window rather than "last N days from
    now": the latest scrape may be a day or two old, so anchoring to `now` would slide
    the cutoff PAST the selected window and drop its data — the bug behind a 2-day
    range showing nothing. See PeriodDep + docs/darkstores.md.
    """
    return (
        datetime.combine(start, time.min),
        datetime.combine(end + timedelta(days=1), time.min),
    )


def _store_cond(tenant_id, own, window, city, marketplaces, kind="main") -> list:
    """The filters every store-grain public query shares.

    `merchant_id != ""` is NOT optional. Rows scraped before 2026-07-18 predate the
    store columns and carry an empty merchant_id; without this filter they all collapse
    into one phantom store and surface in the UI as a real one. History was
    deliberately not backfilled, so excluding it is the honest read — "we don't know
    which store served this". See docs/darkstores.md.
    """
    lo, hi = window
    cond = [
        SkuSnapshot.tenant_id == tenant_id,
        SkuSnapshot.brand_slug.in_(own),
        SkuSnapshot.scraped_at >= lo,
        SkuSnapshot.scraped_at < hi,
        SkuSnapshot.merchant_id != "",
        *_kind_cond(kind),
    ]
    if city:
        cond.append(SkuSnapshot.city == city)
    if marketplaces:
        cond.append(SkuSnapshot.mp_slug.in_(marketplaces))
    return cond


def _latest_per_store(tenant_id, own, window, city, marketplaces, kind="main"):
    """Subquery: the latest sku_snapshots row per (product × dark store) in the window.

    Keyed on `merchant_id`, not `(lat, lon)`: a coordinate can return several stores
    (express plus longtail hubs) and one store can answer several coordinates when the
    catalog drifts — on 2026-07-19, 20 stores were probed twice — so a coordinate key
    both splits and double-counts. The store is the physical unit; the same
    `merchant_id` seen from two coordinates reports identical inventory and price.
    """
    return (
        select(
            SkuSnapshot.platform_product_id.label("pid"),
            SkuSnapshot.product_name.label("name"),
            SkuSnapshot.merchant_id.label("merchant_id"),
            SkuSnapshot.merchant_type.label("merchant_type"),
            SkuSnapshot.city.label("city"),
            SkuSnapshot.in_stock.label("in_stock"),
            SkuSnapshot.inventory.label("inventory"),
            SkuSnapshot.price.label("price"),
            SkuSnapshot.discount_pct.label("discount_pct"),
            SkuSnapshot.pack_size.label("pack_size"),
            SkuSnapshot.pack_uom.label("pack_uom"),
            SkuSnapshot.scraped_at.label("scraped_at"),
        )
        .where(*_store_cond(tenant_id, own, window, city, marketplaces, kind))
        .distinct(SkuSnapshot.platform_product_id, SkuSnapshot.merchant_id)
        .order_by(
            SkuSnapshot.platform_product_id,
            SkuSnapshot.merchant_id,
            SkuSnapshot.scraped_at.desc(),
        )
        .subquery()
    )


async def _denominators(
    session: AsyncSession, tenant_id, own, window, city, marketplaces, kind="main"
) -> tuple[int, int, dict[str, int]]:
    """(stores_scraped, active_range, stores_per_tier) for the window.

    Both denominators are *observed*, never configured: `stores_scraped` counts the
    stores that actually answered, `active_range` the SKUs seen at >= 1 store. A store
    that failed to respond is excluded rather than counted as a zero — we don't know
    its shelf, and assuming empty would understate the brand.
    """
    cond = _store_cond(tenant_id, own, window, city, marketplaces, kind)
    row = (
        await session.execute(
            select(
                func.count(distinct(SkuSnapshot.merchant_id)),
                func.count(distinct(SkuSnapshot.platform_product_id)),
            ).where(*cond)
        )
    ).first()
    tiers = dict(
        (
            await session.execute(
                select(
                    SkuSnapshot.merchant_type,
                    func.count(distinct(SkuSnapshot.merchant_id)),
                )
                .where(*cond)
                .group_by(SkuSnapshot.merchant_type)
            )
        ).all()
    )
    return int(row[0] or 0), int(row[1] or 0), {k or "unknown": int(v) for k, v in tiers.items()}


async def _store_names(session: AsyncSession, merchant_ids: set[str],
                       mp_slugs: list[str] | None = None) -> dict[str, str]:
    """merchant_id -> human label from the store catalog. Stores discovered by a
    scrape but absent from the catalog (longtail hubs, newly opened) have no name —
    the UI falls back to the id. Cosmetic only; the inventory is exact either way.

    Catalogs are per-marketplace and keyed on (mp_slug, merchant_id), so pass the
    caller's marketplace filter when it has one. Without it, ids are matched across
    every marketplace — a collision would mislabel a store, never miscount it.
    """
    if not merchant_ids:
        return {}
    q = (
        select(MarketplaceLocation.merchant_id, MarketplaceLocation.location_name)
        .where(MarketplaceLocation.merchant_id.in_(merchant_ids))
    )
    if mp_slugs:
        q = q.where(MarketplaceLocation.mp_slug.in_(mp_slugs))
    rows = (await session.execute(q)).all()
    return {m: n for m, n in rows if n}


async def get_availability(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    start: date,
    end: date,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    kind: str = "main",
) -> Page[AvailabilityRow]:
    """Public stock-out monitoring — latest row per (product × dark store),
    out-of-stock first. Sourced from sku_snapshots (the targeted own-SKU scrape)."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return Page.build([], 0, pagination)

    window = _bounds(start, end)
    rows = (
        await session.execute(
            select(SkuSnapshot)
            .where(*_store_cond(tenant_id, own, window, city, marketplaces, kind))
            .order_by(
                SkuSnapshot.platform_product_id,
                SkuSnapshot.merchant_id,
                SkuSnapshot.scraped_at.desc(),
            )
            .distinct(SkuSnapshot.platform_product_id, SkuSnapshot.merchant_id)
        )
    ).scalars().all()

    rows.sort(key=lambda r: (r.in_stock, r.platform_product_id))  # OOS first
    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    names = await _store_names(session, {r.merchant_id for r in page}, marketplaces)
    out = []
    for r in page:
        item = AvailabilityRow.model_validate(r)
        item.store_name = names.get(r.merchant_id)
        out.append(item)
    return Page.build(out, total, pagination)


async def get_distribution(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    kind: str = "main",
) -> dict:
    """Per own SKU, at dark-store grain:

        reach_pct        = stores listed   / stores_scraped   (is it on the shelf)
        distribution_pct = stores in stock / stores listed    (is it in stock there)

    Two different problems: a SKU absent from a store is a range/listing gap, one
    listed-but-empty is a replenishment gap. Worst reach first."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    empty = {"period_days": (end - start).days + 1, "as_of": None, "stores_scraped": 0,
             "active_range": 0, "tiers": {}, "skus": []}
    if not own:
        return empty

    window = _bounds(start, end)
    stores_scraped, active_range, tiers = await _denominators(
        session, tenant_id, own, window, city, marketplaces, kind
    )
    latest = _latest_per_store(tenant_id, own, window, city, marketplaces, kind)
    rows = (
        await session.execute(
            select(
                latest.c.pid,
                func.max(latest.c.name),
                func.count(),
                func.sum(cast(latest.c.in_stock, Integer)),
                func.avg(latest.c.price),
                func.avg(latest.c.discount_pct),
                func.max(latest.c.scraped_at),
            ).group_by(latest.c.pid)
        )
    ).all()
    if not rows:
        return empty

    skus = [
        {
            "platform_product_id": pid,
            "product_name": name,
            "stores_listed": int(listed),
            "stores_in_stock": int(in_stock or 0),
            "stores_out_of_stock": int(listed) - int(in_stock or 0),
            "reach_pct": _round(int(listed) / stores_scraped * 100, 1) if stores_scraped else 0.0,
            "distribution_pct": _round(int(in_stock or 0) / listed * 100, 1) if listed else 0.0,
            "avg_price": _round(price),
            "avg_discount": _round(disc, 1),
        }
        for pid, name, listed, in_stock, price, disc, _ in rows
    ]
    skus.sort(key=lambda s: (s["reach_pct"], s["distribution_pct"]))  # widest gaps first
    return {
        "period_days": (end - start).days + 1,
        "as_of": max(r[6] for r in rows),
        "stores_scraped": stores_scraped,
        "active_range": active_range,
        "tiers": tiers,
        "skus": skus,
    }


async def get_availability_history(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    days: int = 84,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    kind: str = "main",
) -> dict:
    """Weekly on-shelf availability % for own SKUs — the stock-out trend."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return {"period_days": days, "points": []}

    # A trend is anchored to the present, not the reporting window: look back `days`
    # from now (the route passes weeks*7). See the get_availability_history docstring.
    now = now_ist()
    window = (now - timedelta(days=days), now + timedelta(days=1))
    cond = _store_cond(tenant_id, own, window, city, marketplaces, kind)

    # `stores` counts the distinct dark stores sampled that week — the honest sample
    # size behind the percentage. The ratio itself is duplication-safe: a store probed
    # from two coordinates returns identical in_stock both times.
    week = func.date_trunc("week", SkuSnapshot.scraped_at).label("week")
    rows = (
        await session.execute(
            select(
                week,
                func.avg(cast(SkuSnapshot.in_stock, Integer)),
                func.count(distinct(SkuSnapshot.merchant_id)),
            )
            .where(*cond)
            .group_by(week)
            .order_by(week)
        )
    ).all()
    points = [
        {
            "week": w.date() if hasattr(w, "date") else w,
            "availability_pct": _round(float(avail) * 100, 1),
            "oos_pct": _round((1 - float(avail)) * 100, 1),
            "stores": n,
        }
        for w, avail, n in rows
    ]
    return {"period_days": days, "points": points}


async def get_pricing(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    kind: str = "main",
) -> dict:
    """Per own SKU: price dispersion across stores (min/median/max) + avg discount,
    using the latest snapshot per store. `unit_price_*` mirror the rupee band at the
    pack's UOM basis (₹/100 ml, ₹/100 g, ₹/piece) — a product's pack is constant
    across stores, so each rupee bound divides by the same pack_size."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    empty = {"period_days": (end - start).days + 1, "as_of": None, "stores_scraped": 0, "skus": []}
    if not own:
        return empty

    window = _bounds(start, end)
    stores_scraped, _, _ = await _denominators(
        session, tenant_id, own, window, city, marketplaces, kind
    )
    latest = _latest_per_store(tenant_id, own, window, city, marketplaces, kind)
    rows = (
        await session.execute(
            select(
                latest.c.pid,
                func.max(latest.c.name),
                func.count(),
                func.min(latest.c.price),
                func.percentile_cont(0.5).within_group(latest.c.price.asc()),
                func.max(latest.c.price),
                func.avg(latest.c.discount_pct),
                func.max(latest.c.scraped_at),
                func.max(latest.c.pack_size),
                func.max(latest.c.pack_uom),
            )
            .where(latest.c.price.is_not(None))
            .group_by(latest.c.pid)
        )
    ).all()
    if not rows:
        return empty

    skus = [
        {
            "platform_product_id": pid,
            "product_name": name,
            "stores": int(n),
            "min_price": _round(mn),
            "median_price": _round(med),
            "max_price": _round(mx),
            "avg_discount": _round(disc, 1),
            "pack_size": _round(psize),
            "pack_uom": puom or "",
            "unit_price_min": per_unit_price(mn, psize, puom or ""),
            "unit_price_median": per_unit_price(med, psize, puom or ""),
            "unit_price_max": per_unit_price(mx, psize, puom or ""),
        }
        for pid, name, n, mn, med, mx, disc, _, psize, puom in rows
    ]
    return {
        "period_days": (end - start).days + 1,
        "as_of": max(r[7] for r in rows),
        "stores_scraped": stores_scraped,
        "skus": skus,
    }


# ── Store-grain views (the dark-store model; see docs/darkstores.md) ─────────

async def get_stores(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    kind: str = "main",
    tier: str | None = None,
) -> dict:
    """Availability per dark store — which shops are letting the brand down.

    Per store: SKUs listed / in stock / out of stock, plus reach against the brand's
    active range. Worst (most out-of-stock, then least reach) first.
    """
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    empty = {"period_days": (end - start).days + 1, "as_of": None, "stores_scraped": 0,
             "active_range": 0, "tiers": {}, "stores": []}
    if not own:
        return empty

    window = _bounds(start, end)
    stores_scraped, active_range, tiers = await _denominators(
        session, tenant_id, own, window, city, marketplaces, kind
    )
    latest = _latest_per_store(tenant_id, own, window, city, marketplaces, kind)
    q = select(
        latest.c.merchant_id,
        func.max(latest.c.merchant_type),
        func.max(latest.c.city),
        func.count(),
        func.sum(cast(latest.c.in_stock, Integer)),
        func.max(latest.c.scraped_at),
    ).group_by(latest.c.merchant_id)
    if tier:
        q = q.where(latest.c.merchant_type == tier)
    rows = (await session.execute(q)).all()
    if not rows:
        return empty

    names = await _store_names(session, {r[0] for r in rows}, marketplaces)
    stores = [
        {
            "merchant_id": mid,
            "store_name": names.get(mid),
            "merchant_type": mtype,
            "city": city_,
            "skus_listed": int(listed),
            "skus_in_stock": int(ok or 0),
            "skus_out_of_stock": int(listed) - int(ok or 0),
            "skus_not_listed": max(active_range - int(listed), 0),
            "reach_pct": _round(int(listed) / active_range * 100, 1) if active_range else 0.0,
            "distribution_pct": _round(int(ok or 0) / listed * 100, 1) if listed else 0.0,
        }
        for mid, mtype, city_, listed, ok, _ in rows
    ]
    stores.sort(key=lambda s: (-s["skus_out_of_stock"], s["reach_pct"]))
    return {
        "period_days": (end - start).days + 1,
        "as_of": max(r[5] for r in rows),
        "stores_scraped": stores_scraped,
        "active_range": active_range,
        "tiers": tiers,
        "stores": stores,
    }


async def get_cities(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    kind: str = "main",
) -> dict:
    """City rollup — the same numbers one level up, for the exec view."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    empty = {"period_days": (end - start).days + 1, "as_of": None, "stores_scraped": 0,
             "active_range": 0, "cities": []}
    if not own:
        return empty

    window = _bounds(start, end)
    stores_scraped, active_range, _ = await _denominators(
        session, tenant_id, own, window, None, marketplaces, kind
    )
    latest = _latest_per_store(tenant_id, own, window, None, marketplaces, kind)
    rows = (
        await session.execute(
            select(
                latest.c.city,
                func.count(distinct(latest.c.merchant_id)),
                func.count(),
                func.sum(cast(latest.c.in_stock, Integer)),
                func.max(latest.c.scraped_at),
            ).group_by(latest.c.city)
        )
    ).all()
    if not rows:
        return empty

    cities = [
        {
            "city": c,
            "stores": int(n_stores),
            "skus_listed": int(listed),
            "skus_in_stock": int(ok or 0),
            "skus_out_of_stock": int(listed) - int(ok or 0),
            # Store × SKU slots in this city where the product is absent from the
            # shelf — the listing gap, the complement of skus_listed.
            "skus_not_listed": max(active_range * int(n_stores) - int(listed), 0),
            # Reach across the city's whole store x SKU matrix.
            "reach_pct": _round(int(listed) / (active_range * int(n_stores)) * 100, 1)
            if active_range and n_stores else 0.0,
            "distribution_pct": _round(int(ok or 0) / listed * 100, 1) if listed else 0.0,
        }
        for c, n_stores, listed, ok, _ in rows
    ]
    cities.sort(key=lambda c: -c["stores"])
    return {
        "period_days": (end - start).days + 1,
        "as_of": max(r[4] for r in rows),
        "stores_scraped": stores_scraped,
        "active_range": active_range,
        "cities": cities,
    }


async def get_actions(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    action: str = "oos",
    start: date,
    end: date,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    kind: str = "main",
) -> Page:
    """The work queue: one row per problem, each naming a store and a product.

    action=oos         - listed but out of stock  (replenishment / supply)
    action=not-listed  - absent from the shelf    (range / commercial)

    Deliberately two lists, not one: they go to different teams. Measured all-India
    on 2026-07-19 the split was 1,064 stockouts vs 4,586 unlisted, i.e. the larger
    opportunity was listings — a signal that disappears if they are merged.
    """
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return Page.build([], 0, pagination)

    window = _bounds(start, end)
    latest = _latest_per_store(tenant_id, own, window, city, marketplaces, kind)
    rows = (await session.execute(select(latest))).all()
    if not rows:
        return Page.build([], 0, pagination)

    by_store: dict[str, dict] = {}
    catalogue: dict[str, str] = {}
    for r in rows:
        catalogue[r.pid] = r.name
        by_store.setdefault(r.merchant_id, {"city": r.city, "type": r.merchant_type, "items": {}})
        by_store[r.merchant_id]["items"][r.pid] = r

    names = await _store_names(session, set(by_store), marketplaces)
    out: list[dict] = []
    if action == "not-listed":
        for mid, s in by_store.items():
            for pid, pname in catalogue.items():
                if pid not in s["items"]:
                    out.append({
                        "merchant_id": mid, "store_name": names.get(mid),
                        "merchant_type": s["type"], "city": s["city"],
                        "platform_product_id": pid, "product_name": pname,
                        "issue": "not-listed", "inventory": None, "price": None,
                        "scraped_at": None,
                    })
    else:
        for mid, s in by_store.items():
            for pid, r in s["items"].items():
                if not (r.in_stock and (r.inventory or 0) > 0):
                    out.append({
                        "merchant_id": mid, "store_name": names.get(mid),
                        "merchant_type": s["type"], "city": s["city"],
                        "platform_product_id": pid, "product_name": r.name,
                        "issue": "out-of-stock", "inventory": r.inventory,
                        "price": r.price, "scraped_at": r.scraped_at,
                    })

    out.sort(key=lambda x: (x["city"] or "", x["store_name"] or x["merchant_id"], x["product_name"] or ""))
    total = len(out)
    return Page.build(out[pagination.offset: pagination.offset + pagination.limit], total, pagination)


async def get_store_detail(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    merchant_id: str,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    kind: str = "main",
) -> dict:
    """One dark store's whole shelf — every own SKU, listed or not.

    Backs the store drawer: absent SKUs appear with `listed=False`, so the range gap
    sits alongside the stockouts instead of being invisible.
    """
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    empty = {"merchant_id": merchant_id, "store_name": None, "city": None,
             "merchant_type": None, "as_of": None, "active_range": 0, "skus": []}
    if not own:
        return empty

    window = _bounds(start, end)
    latest = _latest_per_store(tenant_id, own, window, None, marketplaces, kind)
    rows = (await session.execute(select(latest))).all()
    if not rows:
        return empty

    catalogue = {r.pid: r.name for r in rows}
    here = {r.pid: r for r in rows if r.merchant_id == merchant_id}
    if not here:
        return {**empty, "active_range": len(catalogue)}

    any_row = next(iter(here.values()))
    names = await _store_names(session, {merchant_id}, marketplaces)
    skus = [
        {
            "platform_product_id": pid,
            "product_name": name,
            "listed": pid in here,
            "in_stock": bool(here[pid].in_stock and (here[pid].inventory or 0) > 0) if pid in here else False,
            "inventory": here[pid].inventory if pid in here else None,
            "price": here[pid].price if pid in here else None,
            "discount_pct": here[pid].discount_pct if pid in here else None,
        }
        for pid, name in sorted(catalogue.items(), key=lambda kv: kv[1] or "")
    ]
    return {
        "merchant_id": merchant_id,
        "store_name": names.get(merchant_id),
        "city": any_row.city,
        "merchant_type": any_row.merchant_type,
        "as_of": max(r.scraped_at for r in here.values()),
        "active_range": len(catalogue),
        "skus": skus,
    }


async def get_product_detail(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_id: str,
    start: date,
    end: date,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    kind: str = "main",
) -> dict:
    """One product across every dark store — the mirror of get_store_detail.

    Backs the product drawer: stores where the product is absent appear with
    `listed=False`, so the range gap (where you could sell but don't) sits next to
    the stockouts. Worst-first: out of stock, then not carried, then in stock.
    """
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    empty = {"platform_product_id": product_id, "product_name": None, "as_of": None,
             "stores_scraped": 0, "stores_listed": 0, "stores_in_stock": 0, "stores": []}
    if not own:
        return empty

    window = _bounds(start, end)
    latest = _latest_per_store(tenant_id, own, window, city, marketplaces, kind)
    rows = (await session.execute(select(latest))).all()
    if not rows:
        return empty

    all_stores = {}     # merchant_id -> (city, type) seen for ANY product
    here = {}           # merchant_id -> this product's row
    name = None
    for r in rows:
        all_stores[r.merchant_id] = (r.city, r.merchant_type)
        if r.pid == product_id:
            here[r.merchant_id] = r
            name = r.name
    if not here:
        return {**empty, "stores_scraped": len(all_stores)}

    names = await _store_names(session, set(all_stores), marketplaces)

    def rank(mid):
        r = here.get(mid)
        if r is None:
            return 1              # not carried
        if not (r.in_stock and (r.inventory or 0) > 0):
            return 0              # out of stock — most urgent
        return 2                  # in stock

    stores = [
        {
            "merchant_id": mid,
            "store_name": names.get(mid),
            "city": all_stores[mid][0],
            "merchant_type": all_stores[mid][1],
            "listed": mid in here,
            "in_stock": bool(here[mid].in_stock and (here[mid].inventory or 0) > 0) if mid in here else False,
            "inventory": here[mid].inventory if mid in here else None,
            "price": here[mid].price if mid in here else None,
        }
        for mid in all_stores
    ]
    stores.sort(key=lambda s: (rank(s["merchant_id"]), s["city"] or "", s["store_name"] or s["merchant_id"]))
    in_stock = sum(1 for s in stores if s["in_stock"])
    return {
        "platform_product_id": product_id,
        "product_name": name,
        "as_of": max(r.scraped_at for r in here.values()),
        "stores_scraped": len(all_stores),
        "stores_listed": len(here),
        "stores_in_stock": in_stock,
        "stores": stores,
    }
