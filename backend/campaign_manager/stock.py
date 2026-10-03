"""Stock per measurement store — the input that tells a stock-out from being outbid.

One BRAND search per store lists our catalogue there with availability
(`adapter.read_store_catalog`). A bid run loads stock once, before its rule loop, for every
store any rule will measure at: a cached answer younger than `CM_STOCK_MAX_AGE_MINUTES` is
reused, anything older is re-read. One read serves every keyword and every campaign at that
store, so the cost is per store per hour, not per keyword per tick.

Fail-open everywhere. A marketplace without a catalogue read, a store we can't identify, a
client with no own brand configured, a failed or empty read — each simply leaves that store
without stock, which `coverage.eligibility` treats as UNKNOWN: the store still counts, and a
raise is never stopped by what we failed to learn. A failed read is not cached, so the next
run tries again.
"""
import uuid
from datetime import datetime, timedelta

from campaign_manager import config, coverage, logs, repo


def _short_name(name: str, brand_names=()) -> str:
    """`Brik Oven Sour Cream` → `Sour Cream` when the brand is already understood."""
    low = (name or "").lower()
    for b in sorted((b for b in brand_names if b), key=len, reverse=True):
        if low.startswith(b.lower() + " "):
            return name[len(b) + 1:]
    return name


def _stock_said(where: str, products: list[dict], available: int, complete: bool,
                brand_names=()) -> str:
    """The store-level stock line. It covers the client's WHOLE brand at the store, so it names
    what is listed — whether a particular campaign's products are among them is said per
    automation, right after: `stock at J. P. Nagar: brand has 2 (Sour Cream, Whey Ricotta
    Cheese) · 2 in stock`."""
    if not products:
        said = "brand has nothing listed"
    else:
        names = [_short_name(p.get("name") or p.get("pid") or "", brand_names)
                 for p in products]
        shown = ", ".join(names[:3]) + (f" +{len(names) - 3} more" if len(names) > 3 else "")
        said = f"brand has {len(products)} ({shown}) · {available} in stock"
    return (f"stock at {where}: {said}"
            + ("" if complete else " · partial read"))


def _fresh(stock: coverage.StoreStock | None, now: datetime) -> bool:
    return bool(stock and stock.checked_at
                and now - stock.checked_at < timedelta(minutes=config.STOCK_MAX_AGE_MINUTES))


async def cached(tenant_id: uuid.UUID, platform: str, stores, *,
                 now: datetime) -> dict[str, coverage.StoreStock]:
    """`{merchant_id: StoreStock}` for the stores whose cached read is still fresh — no
    searches at all. The rotation (campaign_manager/rotation.py) starts from this and reads
    a store only when our ad is missing there. Never raises: no cache = nothing known."""
    ids = {s.merchant_id for s in stores if getattr(s, "merchant_id", "")}
    if not ids:
        return {}
    try:
        got = await repo.get_store_stock(tenant_id, platform, ids)
    except Exception:
        return {}
    return {mid: st for mid, st in got.items() if _fresh(st, now)}


async def load(adapter, session, tenant_id: uuid.UUID, platform: str, stores, *,
               now: datetime, run_id: str, dry_run: bool,
               indent: bool = False) -> tuple[dict[str, coverage.StoreStock], int]:
    """`({merchant_id: StoreStock}, brand searches made)` for the stores a run measures at —
    cached where fresh, re-read where stale. A store absent from the dict has no known stock.

    Never raises. Stock only ever REMOVES stores from a decision, so the safe failure is to
    know nothing: every store then counts, exactly as before stock existed."""
    try:
        return await _load(adapter, session, tenant_id, platform, stores,
                           now=now, run_id=run_id, dry_run=dry_run, indent=indent)
    except Exception as e:
        logs.note(run_id, f"stock check failed ({e}) · every store counts",
                  dry_run=dry_run, level="warning", indent=indent)
        return {}, 0


async def _load(adapter, session, tenant_id: uuid.UUID, platform: str, stores, *,
                now: datetime, run_id: str, dry_run: bool,
                indent: bool = False) -> tuple[dict[str, coverage.StoreStock], int]:
    by_id: dict[str, object] = {}
    for s in stores:
        if getattr(s, "merchant_id", "") and s.merchant_id not in by_id:
            by_id[s.merchant_id] = s
    if not by_id:
        return {}, 0

    reader = getattr(adapter, "read_store_catalog", None)
    if reader is None:
        logs.note(run_id, f"stock not checked on {platform.title()} · every store counts",
                  dry_run=dry_run, indent=indent)
        return {}, 0

    cached = await repo.get_store_stock(tenant_id, platform, set(by_id))
    from_cache = {mid: st for mid, st in cached.items() if _fresh(st, now)}
    out = dict(from_cache)
    stale = [s for mid, s in by_id.items() if mid not in out]

    brands = await repo.get_own_brands(tenant_id, platform) if stale else []
    if stale and not brands:
        logs.note(run_id, "no own brand configured · stock not checked",
                  dry_run=dry_run, level="warning", indent=indent)
        stale = []

    rows, searches = [], 0
    for store in stale:
        products: list[dict] = []
        complete, served_by, error = True, "", None
        # A client may sell under several brand names; each is its own search, and a store is
        # only known once every one of them read cleanly.
        for query, cap, names in brands:
            searches += 1
            try:
                # The store id binds a Zepto search to its store (Blinkit ignores it).
                res = await reader(session, query, store.lat, store.lon, cap=cap, names=names,
                                   merchant_id=store.merchant_id)
            except Exception as e:                      # a read failure is not a run failure
                res = {"ok": False, "error": str(e) or type(e).__name__}
            if not res.get("ok"):
                error = res.get("error") or "the brand search failed"
                break
            products.extend(res["products"])
            complete = complete and bool(res["complete"])
            served_by = served_by or res.get("served_by") or ""
        if error is not None:
            logs.note(run_id, f"stock at {store.label or store.merchant_id}: unreadable — "
                              f"{error} · still counts",
                      dry_run=dry_run, level="warning", indent=indent)
            continue

        in_stock = {p["pid"]: bool(p["in_stock"]) for p in products}
        out[store.merchant_id] = coverage.StoreStock(complete=complete, in_stock=in_stock,
                                                     checked_at=now)
        available = sum(1 for v in in_stock.values() if v)
        brand_names = {n for _, _, ns in brands for n in ns}
        logs.note(run_id, _stock_said(store.label or store.merchant_id, products, available,
                                      complete, brand_names),
                  dry_run=dry_run, indent=indent)
        rows.append({"merchant_id": store.merchant_id, "served_by": served_by,
                     "complete": complete, "products": products, "checked_at": now})

    await repo.upsert_store_stock(tenant_id, platform, rows)

    # One line that says where this run's stock came from. Without it a reused 40-minute-old
    # read and a fresh one look identical in the log.
    parts = []
    if from_cache:
        oldest = max(int((now - st.checked_at).total_seconds() // 60)
                     for st in from_cache.values())
        parts.append(f"{len(from_cache)} from cache (up to {oldest} min old)")
    if rows:
        parts.append(f"{len(rows)} re-read")
    unknown = len(by_id) - len(out)
    if unknown:
        parts.append(f"{unknown} unknown, counted anyway")
    # DEBUG unless something is unknown: the per-store lines above already say what was read.
    logs.note(run_id, f"stock for {len(by_id)} store{'s' if len(by_id) != 1 else ''}: "
                      + ", ".join(parts),
              dry_run=dry_run, level="warning" if unknown else "debug", indent=indent)
    return out, searches
