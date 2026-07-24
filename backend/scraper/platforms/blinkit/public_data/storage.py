import uuid

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search import SearchSnapshot, SearchListing
from app.utils.logger import logger
from app.utils.time import now_ist
from scraper.utils.pack import pack_fields, combo_from_pack
from scraper.utils.storage import ensure_refs


def _as_uuid(value) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


async def save(session: AsyncSession, result: dict, tenant_id, job_id=None, ensured: set | None = None) -> int:
    """Persist one search as a header (`search_snapshots`) + N detail rows
    (`search_listings`), tagged with `tenant_id` + `job_id`. Returns rows written.

    Append-only (public data is never upserted). `ensure_refs` upserts the brand
    rows for the own brand and every competitor slug so the FKs resolve. `ensured`
    is a per-run cache of already-upserted slugs, so we call `ensure_refs` once per
    brand per run instead of on every save (avoids ~7 redundant brand upserts per
    save — a large DB-round-trip saving over a long run).
    """
    tid = _as_uuid(tenant_id)
    jid = _as_uuid(job_id)
    listings = result.get("listings", [])
    scraped_at = now_ist()

    slugs = {result["brand_slug"]} | {
        l["brand_slug"] for l in listings if l.get("brand_slug")
    }
    new_slugs = slugs - ensured if ensured is not None else slugs

    async def _write() -> None:
        """Persist the header + its listings in one transaction.

        Deliberately re-runnable: every ORM object is built fresh on each call,
        because a rolled-back attempt discards the pending objects *and* the
        flushed `snapshot.id` the listing FKs hang off. `ensure_refs` is redone
        for the same reason — its writes share this transaction. `new_slugs` is
        still valid on a retry since `ensured` is only updated after a commit.
        """
        for slug in new_slugs:
            await ensure_refs(session, slug, "blinkit")

        snapshot = SearchSnapshot(
            tenant_id=tid,
            job_id=jid,
            brand_slug=result["brand_slug"],
            mp_slug="blinkit",
            keyword=result["keyword"],
            city=result.get("city", ""),
            zone=result.get("zone", ""),
            pincode=result.get("pincode", ""),
            lat=result.get("lat"),
            lon=result.get("lon"),
            merchant_id=result.get("merchant_id", ""),
            scraped_at=scraped_at,
            brand_rank=result.get("brand_rank"),
            brand_sov=result.get("brand_sov_pct"),
            total_results=result.get("total_results"),
        )
        session.add(snapshot)
        await session.flush()  # assign snapshot.id for the FK below

        for l in listings:
            pack = pack_fields(l.get("unit"))
            session.add(
                SearchListing(
                    snapshot_id=snapshot.id,
                    tenant_id=tid,
                    job_id=jid,
                    mp_slug="blinkit",
                    brand_slug=l.get("brand_slug"),
                    keyword=result["keyword"],
                    city=result.get("city", ""),
                    zone=result.get("zone", ""),
                    pincode=result.get("pincode", ""),
                    scraped_at=scraped_at,
                    position=l.get("position"),
                    product_name=l.get("name", ""),
                    is_brand=l.get("is_brand", False),
                    # pack_count is the reliable combo signal (name misses ~13%);
                    # combo_from_pack falls back to the name when the unit is unparsed.
                    is_combo=combo_from_pack(l.get("name", ""), pack["pack_count"]),
                    price=l.get("price"),
                    mrp=l.get("mrp"),
                    discount_pct=l.get("discount_pct"),
                    pack_raw=pack["pack_raw"],
                    pack_size=pack["pack_size"],
                    pack_uom=pack["pack_uom"],
                    pack_count=pack["pack_count"],
                    in_stock=l.get("in_stock", True),
                    inventory=l.get("inventory"),
                    platform_product_id=l.get("product_id") or None,
                    # Per-product, not per-snapshot: one response spans several stores.
                    merchant_id=l.get("merchant_id") or "",
                    merchant_type=l.get("merchant_type") or "",
                    extra={
                        "group_id": l.get("group_id"),
                        "unit": l.get("unit"),
                        "ptype": l.get("ptype"),
                        "category": l.get("category"),
                        "match_reason": l.get("match_reason"),
                        "image_url": l.get("image_url"),
                    },
                )
            )

        await session.commit()

    # A pooled connection held across slow browser work can be silently dropped by
    # the Supabase pooler / a home-network NAT, surfacing here as a disconnect at
    # commit — which would otherwise fail the whole run (and tear down the shared
    # browser with it). On a *connection-level* drop, roll back to discard the dead
    # connection and retry once; the pool then hands us a fresh one. Safe because
    # public data is append-only and the failed attempt never committed.
    for attempt in (1, 2):
        try:
            await _write()
            break
        except DBAPIError as e:
            # Only retry a genuine dropped connection — real SQL errors must raise.
            if not e.connection_invalidated or attempt == 2:
                raise
            await session.rollback()
            logger.warning(
                f"blinkit public | DB connection dropped mid-write "
                f"(tenant={tid} kw='{result['keyword']}' city={result.get('city', '')}) "
                f"— retrying once"
            )

    if ensured is not None:
        ensured |= new_slugs  # mark ensured only after a successful commit
    written = 1 + len(listings)
    logger.debug(
        f"blinkit public | saved snapshot + {len(listings)} listings "
        f"tenant={tid} kw='{result['keyword']}' "
        f"rank={result.get('brand_rank')} sov={result.get('brand_sov_pct')}%"
    )
    return written
