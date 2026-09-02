"""Build and maintain `sku_map`: private `item_id` ↔ public `platform_product_id`.

The two Blinkit id systems share no key (verified: seller item_id is 8-digit, the
consumer product_id is 6-digit, zero overlap, and the consumer API exposes no UPC),
so the bridge is built by NORMALIZED NAME matching. Private names carry a container
suffix "(PET Bottle)"/"(Cup)" the public ones don't, and public combos carry
"- Pack of N" markers, so normalization strips parentheticals and non-alphanumerics
but keeps pack markers — that way a private single maps to a public single and never
to a multipack. Whatever doesn't auto-resolve is left for manual confirmation.
"""
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blinkit_seller import BlinkitSellerSale
from app.models.zepto_seller import ZeptoSellerSales
from app.models.search import SkuMap, SkuSnapshot
from app.models.tenant import TenantWatchlist
from app.utils.time import now_ist

_PAREN = re.compile(r"\([^)]*\)")
_NONALNUM = re.compile(r"[^a-z0-9]+")


def _norm(name: str) -> str:
    """Lowercase, strip parentheticals (container type), collapse non-alphanumerics.
    Pack markers ('pack of 2') are kept so singles never normalize onto multipacks."""
    s = _PAREN.sub(" ", (name or "").lower())
    s = _NONALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


async def _own_aliases(session: AsyncSession, tenant_id: uuid.UUID) -> set[str]:
    rows = (await session.execute(
        select(TenantWatchlist).where(
            TenantWatchlist.tenant_id == tenant_id,
            TenantWatchlist.relationship == "own",
        )
    )).scalars().all()
    aliases: set[str] = set()
    for r in rows:
        aliases.add(r.brand_slug.replace("-", " ").lower())
        aliases.update((a or "").lower() for a in (r.aliases or []))
    return {a for a in aliases if a}


async def build_map(session: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Auto-match own private items to public products by normalized name, upserting
    `sku_map`. Preserves existing `manual` mappings. Returns a report."""
    aliases = await _own_aliases(session, tenant_id)

    # Private items (own only — filter out other brands the seller also stocks).
    priv = (await session.execute(
        select(BlinkitSellerSale.item_id, BlinkitSellerSale.item_name)
        .where(BlinkitSellerSale.tenant_id == tenant_id)
        .distinct()
    )).all()

    # Zepto's private ids live in their own table, and its id systems are just as
    # disjoint as Blinkit's: the seller dashboard calls Artisinal Sourdough
    # `5e4a9b9b-…` while the shopper app calls it `06d0fc37-…`. Same table, same
    # name-matching — only the source of the private list differs.
    #
    # `sku_map` carries no marketplace column, so a tenant selling on BOTH
    # marketplaces would have the two fight over one row per item_id. No tenant
    # does today; adding `mp_slug` is the fix when one does.
    priv = [
        *priv,
        *(await session.execute(
            select(
                ZeptoSellerSales.product_variant_id,
                # `product_name`, NOT `sku_name`. sku_name carries the pack
                # ("… 400.0 GRAM") which the public listing omits, so matching on
                # it fails every row. product_name is already the pack-free form
                # the shopper app uses, so the two normalise identically.
                ZeptoSellerSales.product_name,
            )
            .where(ZeptoSellerSales.tenant_id == tenant_id)
            .distinct()
        )).all(),
    ]
    own_priv = [
        (str(iid), name) for iid, name in priv
        if any(a in (name or "").lower() for a in aliases)
    ]

    # Public products, indexed by normalized name (prefer singles over combos).
    pub = (await session.execute(
        select(
            SkuSnapshot.platform_product_id,
            SkuSnapshot.product_name,
            SkuSnapshot.is_combo,
        ).where(SkuSnapshot.tenant_id == tenant_id).distinct()
    )).all()
    by_norm: dict[str, list[tuple]] = {}
    for pid, name, is_combo in pub:
        by_norm.setdefault(_norm(name), []).append((pid, name, is_combo))

    existing = {
        m.item_id: m
        for m in (await session.execute(
            select(SkuMap).where(SkuMap.tenant_id == tenant_id)
        )).scalars().all()
    }

    matched = unmatched = preserved = 0
    now = now_ist()
    for item_id, item_name in own_priv:
        cur = existing.get(item_id)
        if cur and cur.match_method == "manual":
            preserved += 1
            continue

        cands = by_norm.get(_norm(item_name), [])
        singles = [c for c in cands if not c[2]]
        pick = None
        if len(singles) == 1:
            pick = singles[0]
        elif len(cands) == 1:
            pick = cands[0]

        pid = pick[0] if pick else None
        pname = pick[1] if pick else ""
        if pid:
            matched += 1
        else:
            unmatched += 1

        if cur:
            cur.platform_product_id = pid
            cur.item_name = item_name
            cur.product_name = pname
            cur.match_method = "auto" if pid else ""
            cur.confidence = 1.0 if pid else None
            cur.updated_at = now
        else:
            session.add(SkuMap(
                tenant_id=tenant_id, item_id=item_id, platform_product_id=pid,
                item_name=item_name, product_name=pname,
                match_method="auto" if pid else "", confidence=1.0 if pid else None,
            ))

    await session.commit()
    return {
        "private_own_items": len(own_priv),
        "matched": matched,
        "unmatched": unmatched,
        "preserved_manual": preserved,
    }


async def list_map(session: AsyncSession, tenant_id: uuid.UUID) -> list[SkuMap]:
    return (await session.execute(
        select(SkuMap).where(SkuMap.tenant_id == tenant_id).order_by(SkuMap.item_name)
    )).scalars().all()


async def apply_corrections(
    session: AsyncSession, tenant_id: uuid.UUID, pairs: list[tuple[str, str]]
) -> dict:
    """Set `platform_product_id` (method='manual') for the given (item_id,
    platform_product_id) pairs — the human-confirmed corrections. Fills
    `product_name` from the public snapshot where available."""
    pub = {
        str(pid): name
        for pid, name in (await session.execute(
            select(SkuSnapshot.platform_product_id, SkuSnapshot.product_name)
            .where(SkuSnapshot.tenant_id == tenant_id).distinct()
        )).all()
    }
    existing = {
        m.item_id: m
        for m in (await session.execute(
            select(SkuMap).where(SkuMap.tenant_id == tenant_id)
        )).scalars().all()
    }

    applied = 0
    now = now_ist()
    for item_id, pid in pairs:
        item_id, pid = str(item_id), (str(pid) if pid else None)
        if not pid:
            continue
        cur = existing.get(item_id)
        if cur:
            cur.platform_product_id = pid
            cur.product_name = pub.get(pid, cur.product_name)
            cur.match_method = "manual"
            cur.confidence = None
            cur.updated_at = now
        else:
            session.add(SkuMap(
                tenant_id=tenant_id, item_id=item_id, platform_product_id=pid,
                product_name=pub.get(pid, ""), match_method="manual",
            ))
        applied += 1

    await session.commit()
    return {"applied": applied}
