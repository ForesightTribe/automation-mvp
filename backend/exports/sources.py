"""Memoized service reads, scoped to one report run.

Several sheets are different views of the same query — the Shelf Summary and
Product Shelf Presence both need `get_distribution`, and Search Visibility and
the position grid both need `get_rank_matrix`. Calling the service twice would
double the most expensive queries in the report for identical results.

The cache lives on the SQLAlchemy session's `info` dict, so it is created and
discarded with the session — there is no process-wide state to go stale, and a
second report on a second session shares nothing with the first. Keys carry every
argument that changes the answer, so two specs can never collide.
"""
from app.schemas.exports import ReportSpec
from app.services import competition_service, inventory_service


async def _once(db, key, factory):
    store = db.info.setdefault("_export_cache", {})
    if key not in store:
        store[key] = await factory()
    return store[key]


def _scope(spec: ReportSpec) -> tuple:
    return (str(spec.tenant_id), spec.start, spec.end, spec.marketplace, spec.city, spec.kind)


async def distribution(db, spec: ReportSpec) -> dict:
    """Per own product: how widely carried, how often in stock."""
    return await _once(
        db, ("distribution", *_scope(spec)),
        lambda: inventory_service.get_distribution(
            db, tenant_id=spec.tenant_id, start=spec.start, end=spec.end,
            city=spec.city, marketplace=spec.marketplace, kind=spec.kind,
        ),
    )


async def rank_matrix(db, spec: ReportSpec) -> dict:
    """Average position + share of search per (search term, city)."""
    return await _once(
        db, ("rank_matrix", *_scope(spec)),
        lambda: competition_service.get_rank_matrix(
            db, tenant_id=spec.tenant_id, marketplace=spec.marketplace,
            start=spec.start, end=spec.end,
        ),
    )
