"""`build_report(db, spec)` — turn a `ReportSpec` into a rendered-ready `Report`.

It owns three things and delegates everything else:

  1. the **cover** — who this is for, what window, and how old the data is;
  2. running the **registry's** sections for the requested group;
  3. collecting the **glossary** for exactly the terms those sections used.

No aggregation lives here. Sections call the read services; this assembles.
"""
from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search import SearchSnapshot, SkuSnapshot
from app.models.tenant import Tenant
from exports import glossary, registry, text
from exports import sections as _sections  # noqa: F401 — registers the sections
from app.schemas.exports import MetaItem, Report, ReportSpec
from app.services import watchlist_service
from app.utils.logger import logger

# The window and combo filters are imported rather than re-derived. `_bounds`
# encodes the "selected dates, not N days from now" rule whose absence once made
# a two-day range return nothing; `_kind_cond` encodes the main/combo split. A
# second copy of either is a second thing to get wrong.
from app.services.inventory_service import _bounds, _kind_cond  # noqa: PLC2701


async def _coverage(db: AsyncSession, spec: ReportSpec, own: list[str]) -> dict:
    """What the scrapes actually saw in this window — the cover's honest N."""
    lo, hi = _bounds(spec.start, spec.end)
    empty = {"stores": 0, "skus": 0, "keywords": 0, "sku_as_of": None, "search_as_of": None}
    if not own:
        return empty

    sku_cond = [
        SkuSnapshot.tenant_id == spec.tenant_id,
        SkuSnapshot.brand_slug.in_(own),
        SkuSnapshot.scraped_at >= lo,
        SkuSnapshot.scraped_at < hi,
        SkuSnapshot.merchant_id != "",   # pre-2026-07-18 rows have no store; excluding them is the honest read
        *_kind_cond(spec.kind),
    ]
    if spec.city:
        sku_cond.append(SkuSnapshot.city == spec.city)
    if spec.marketplace:
        sku_cond.append(SkuSnapshot.mp_slug == spec.marketplace)

    stores, skus, sku_as_of = (
        await db.execute(
            select(
                func.count(distinct(SkuSnapshot.merchant_id)),
                func.count(distinct(SkuSnapshot.platform_product_id)),
                func.max(SkuSnapshot.scraped_at),
            ).where(*sku_cond)
        )
    ).one()

    search_cond = [
        SearchSnapshot.tenant_id == spec.tenant_id,
        SearchSnapshot.scraped_at >= lo,
        SearchSnapshot.scraped_at < hi,
    ]
    if spec.city:
        search_cond.append(SearchSnapshot.city == spec.city)
    if spec.marketplace:
        search_cond.append(SearchSnapshot.mp_slug == spec.marketplace)

    keywords, search_as_of = (
        await db.execute(
            select(
                func.count(distinct(SearchSnapshot.keyword)),
                func.max(SearchSnapshot.scraped_at),
            ).where(*search_cond)
        )
    ).one()

    return {
        "stores": stores or 0,
        "skus": skus or 0,
        "keywords": keywords or 0,
        "sku_as_of": sku_as_of,
        "search_as_of": search_as_of,
    }


def _meta(spec: ReportSpec, client: str, cov: dict, *, today: date | None = None) -> list[MetaItem]:
    latest = max((d for d in (cov["sku_as_of"], cov["search_as_of"]) if d), default=None)
    scraped, age = text.freshness(latest, today=today)
    return [
        MetaItem(label="Client", value=client),
        MetaItem(label="Marketplace", value=(spec.marketplace or "All").title()),
        MetaItem(label="Date range", value=text.window_label(spec.start, spec.end),
                 note="the dates you selected"),
        MetaItem(label="Cities", value=spec.city.title() if spec.city else "All covered cities"),
        MetaItem(label="Product filter", value=text.kind_label(spec.kind)),
        MetaItem(label="Data freshness", value=scraped, note=age),
        MetaItem(label="Stores observed", value=cov["stores"],
                 note="dark stores that answered a scrape"),
        MetaItem(label="Products tracked", value=cov["skus"]),
        MetaItem(label="Search terms", value=cov["keywords"]),
    ]


async def client_name(db: AsyncSession, tenant_id) -> str | None:
    """The client's display name, or None if there is no such client."""
    return (
        await db.execute(select(Tenant.name).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()


async def build_report(db: AsyncSession, spec: ReportSpec) -> Report:
    """Build every section the spec asks for. Sections with no data in the window
    are dropped rather than rendered empty."""
    client = await client_name(db, spec.tenant_id)
    if client is None:
        raise ValueError(f"No client with id {spec.tenant_id}.")

    own = await watchlist_service.get_brands_by_relationship(db, spec.tenant_id, "own")
    if not own:
        logger.warning(f"{client} has no 'own' brand on its watchlist — the shelf sheets will be empty.")

    cov = await _coverage(db, spec, own)

    built, terms, windowed = [], [], 0
    for entry in registry.resolve(spec):
        section = await entry["build"](db, spec)
        if section is None:
            logger.info(f"section '{entry['key']}' — no data in this window, skipped")
            continue
        built.append(section)
        terms.extend(entry["terms"])
        windowed += bool(entry["window_scoped"])

    if built and not windowed:
        # Everything that respects the selected dates came back empty; the only
        # survivors are now-anchored trends. Shipping those alone would hand a
        # client a workbook covering dates they did not ask for, which reads as
        # data rather than as an empty result. Treat the report as empty.
        logger.warning(
            f"no window-scoped section had data for {spec.start}..{spec.end} — "
            f"dropping {len(built)} trend-only sheet(s) rather than shipping the wrong dates"
        )
        built, terms = [], []

    return Report(
        title=f"{client} — Shelf & Search Report",
        subtitle=f"{(spec.marketplace or 'all marketplaces').title()} · "
                 f"{text.window_label(spec.start, spec.end)}"
                 + (f" · {spec.label}" if spec.label else ""),
        filename_stem=f"{client.replace(' ', '_')}_public_{spec.end:%Y-%m-%d}",
        meta=_meta(spec, client, cov),
        sections=built,
        glossary=glossary.collect(*terms),
    )


async def latest_window(db: AsyncSession, tenant_id, days: int = 7) -> tuple[date, date] | None:
    """The most recent `days`-long window that actually contains data.

    Defaulting a report to "the last 7 days from today" is the trap that once
    made a valid range return nothing: public scrapes run weekly, so today minus
    six days can easily sit entirely after the last scrape. Anchor to the data.
    """
    latest = (
        await db.execute(
            select(func.max(SkuSnapshot.scraped_at)).where(SkuSnapshot.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if latest is None:
        return None
    end = latest.date()
    return (end - timedelta(days=days - 1), end)
