"""Instamart ad-asset daily metrics — `POST /api/v1/advertiser/metrics`
(the same signed session as everything else in this package), account-wide,
split by DIMENSION_TYPE_AD_CANDIDATE (a product) or DIMENSION_TYPE_KEYWORD,
each paired with DIMENSION_TYPE_CAMPAIGN and DIMENSION_TYPE_DAY for a real
daily, per-campaign breakdown.

Discovered by driving the campaign-detail page's own network traffic with our
existing session rather than guessing: it made these same calls scoped to one
campaign for its Keyword/Products Performance tables. Dropping the campaign
FILTER (keeping campaign as a DIMENSION instead) widens the totals to the
whole account while still attributing each row to the campaign(s) it came
from — mirrors Zepto's own product/keyword tables in shape, but unlike them
this one DOES carry a campaign id per row.

There is no ad-type (campaign_type) filter or breakdown here — it existed
earlier and was removed: METRIC_FILTER_TYPE_CAMPAIGN_TYPE was verified live
to work once, then verified live to NOT discriminate between types at all
after a session re-login (ITEM/BANNER/COLLECTION_ADS all returned identical
totals), and the stored data showed the same campaigns triple-counted under
three type labels. Unreliable at the API level. DIMENSION_TYPE_CAMPAIGN is
unaffected by this and reconciles exactly against the proven-correct
unfiltered total (see _CHUNK_DAYS' comment) — only the TYPE FILTER was
unreliable, so only that was removed.

`candidate_id` is the same id `sku_snapshots.platform_product_id` already
carries for Instamart (verified: AEYU74I37R here is the same AEYU74I37R the
public scraper stores for Artisanal Sourdough Bread) — so product names are
resolved by joining that table in the service layer, not a separate
catalogue call.
"""
import datetime as dt

from app.utils.logger import logger
from scraper.platforms.instamart.dashboard_data.seller import endpoints as ep
from scraper.platforms.instamart.dashboard_data.seller.account_metrics import _epoch
from scraper.platforms.instamart.dashboard_data.seller.session import PortalSession

ADVERTISER_METRICS = "/api/v1/advertiser/metrics"
PAGE_SIZE = 500

_METRICS = [
    "METRIC_TYPE_GMV", "METRIC_TYPE_IMPRESSIONS", "METRIC_TYPE_CLICKS",
    "METRIC_TYPE_BUDGET_BURNT", "METRIC_TYPE_ADD_TO_CART_COUNT",
]


# ⚠️ METRIC_FILTER_TYPE_CAMPAIGN_TYPE was verified live EARLIER to genuinely
# narrow the product/keyword breakdown (BANNER: 9 products; SEARCH_AUTO_SUGGEST:
# 1, the brand-wide row). Re-verified LATER the same day, after a session
# re-login, and it no longer discriminated: ITEM/BANNER/COLLECTION_ADS all
# returned byte-identical totals for the same candidate, and the stored
# by-type rows showed the same two campaigns duplicated under three different
# type labels -- real spend triple-counted when summed. Unreliable at the API
# level, not something client-side chunking or retries can paper over, so the
# whole by-type breakdown (and the ad-type filter UI built on it) was removed
# rather than shipped on data that can't be trusted. If Instamart's filter
# becomes reliable again, `git log` has the removed CAMPAIGN_TYPES/
# fetch_*_by_type/parse_*_by_type code to revive.
#
# DIMENSION_TYPE_CAMPAIGN itself is unaffected by this -- it is a dimension,
# not a filter, and reconciled exactly against the proven-correct unfiltered
# total (verified live: 2-dim spend=15241.69 == 3-dim-with-campaign
# spend=15241.69 for the same candidate/window). So campaign ATTRIBUTION is
# safe to keep; only the TYPE filter was the unreliable part.


def _body(account_id: str, dimension: str, start: dt.date, end: dt.date, offset: int) -> dict:
    return {
        "account_id": account_id,
        "advertiser_metrics_query": {
            "metrics": [{"name": m} for m in _METRICS],
            "dimensions": [dimension, "DIMENSION_TYPE_CAMPAIGN", "DIMENSION_TYPE_DAY"],
            "filters": {"logical_operator": "LOGICAL_OPERATOR_AND", "filters": [
                {
                    "metric_filter": "METRIC_FILTER_TYPE_DATE",
                    "comparison_operator": "COMPARISON_OPERATOR_BETWEEN",
                    "values": [
                        {"i_value": _epoch(start)},
                        {"i_value": _epoch(end, end_of_day=True)},
                    ],
                },
            ]},
            "pagination_context": {"offset": str(offset), "size": PAGE_SIZE},
        },
    }


# `pagination_context.offset` does not actually advance past PAGE_SIZE on this
# endpoint -- verified live: a 30-day keyword query returned exactly 500 rows
# (silently only 25 Aug-3 Sept, ~10 of the 30 days) and a second page at
# offset=500 came back empty, even though far more rows genuinely exist for
# the full range. So instead of trusting offset for a wide range, each
# request is kept to a window small enough to reliably land under PAGE_SIZE
# in one page, and wider ranges are split into several such requests.
#
# Every row now also carries DIMENSION_TYPE_CAMPAIGN, which multiplies row
# count -- verified live: keywords at ~59 rows/day-of-account-history (vs
# ~10 for products), so a 7-day chunk would sit near ~413/500, too close for
# comfort on an account with more keywords than this one happened to have.
# 4 days keeps real margin (~236/500).
_CHUNK_DAYS = 4


async def _fetch_window(portal: PortalSession, account_id: str, dimension: str,
                         start: dt.date, end: dt.date) -> list[dict]:
    data = await portal.signed_post(
        ADVERTISER_METRICS, _body(account_id, dimension, start, end, 0)
    )
    page = data.get("metricsOnDimensionsList") or []
    logger.info(f"Instamart {dimension} daily {start}..{end}: {len(page)} row(s)")
    if len(page) >= PAGE_SIZE:
        logger.warning(
            f"Instamart {dimension} daily {start}..{end}: hit the {PAGE_SIZE}-row "
            f"cap -- some rows in this window were silently dropped. Narrow "
            f"_CHUNK_DAYS if this keeps happening."
        )
    return page


def _chunk_bounds(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """[(chunk_start, chunk_end), ...] covering [start, end], each at most
    _CHUNK_DAYS wide."""
    bounds: list[tuple[dt.date, dt.date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=_CHUNK_DAYS - 1), end)
        bounds.append((cur, chunk_end))
        cur = chunk_end + dt.timedelta(days=1)
    return bounds


async def _fetch(portal: PortalSession, account_id: str, dimension: str,
                  start: dt.date, end: dt.date) -> list[dict]:
    out: list[dict] = []
    for chunk_start, chunk_end in _chunk_bounds(start, end):
        out.extend(await _fetch_window(portal, account_id, dimension, chunk_start, chunk_end))
    return out


async def fetch_products_daily(portal: PortalSession, account_id: str,
                                start: dt.date, end: dt.date) -> list[dict]:
    return await _fetch(portal, account_id, "DIMENSION_TYPE_AD_CANDIDATE", start, end)


async def fetch_keywords_daily(portal: PortalSession, account_id: str,
                                start: dt.date, end: dt.date) -> list[dict]:
    return await _fetch(portal, account_id, "DIMENSION_TYPE_KEYWORD", start, end)


def _metrics_map(entry: dict) -> dict:
    return {m["name"]: m.get("value") for m in entry.get("metrics") or []}


def parse_products_daily(raw: list[dict]) -> list[dict]:
    """`campaign_id` splits a date+product into one row per contributing
    campaign (see module comment on DIMENSION_TYPE_CAMPAIGN)."""
    out: list[dict] = []
    for entry in raw:
        dims = {d["name"]: d["value"] for d in entry.get("dimensions") or []}
        cid, day = dims.get("DIMENSION_TYPE_AD_CANDIDATE"), dims.get("DIMENSION_TYPE_DAY")
        if not cid or not day:
            continue
        m = _metrics_map(entry)
        out.append({
            "date": dt.date.fromisoformat(day),
            "candidate_id": cid,
            "campaign_id": dims.get("DIMENSION_TYPE_CAMPAIGN"),
            "spend": m.get("METRIC_TYPE_BUDGET_BURNT") or 0.0,
            "gmv": m.get("METRIC_TYPE_GMV") or 0.0,
            "impressions": int(m.get("METRIC_TYPE_IMPRESSIONS") or 0),
            "clicks": int(m.get("METRIC_TYPE_CLICKS") or 0),
            "add_to_cart_count": int(m.get("METRIC_TYPE_ADD_TO_CART_COUNT") or 0),
        })
    return out


def parse_keywords_daily(raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for entry in raw:
        dims = {d["name"]: d["value"] for d in entry.get("dimensions") or []}
        kw, day = dims.get("DIMENSION_TYPE_KEYWORD"), dims.get("DIMENSION_TYPE_DAY")
        if not kw or not day:
            continue
        m = _metrics_map(entry)
        out.append({
            "date": dt.date.fromisoformat(day),
            "keyword": kw,
            "campaign_id": dims.get("DIMENSION_TYPE_CAMPAIGN"),
            "spend": m.get("METRIC_TYPE_BUDGET_BURNT") or 0.0,
            "gmv": m.get("METRIC_TYPE_GMV") or 0.0,
            "impressions": int(m.get("METRIC_TYPE_IMPRESSIONS") or 0),
            "clicks": int(m.get("METRIC_TYPE_CLICKS") or 0),
            "add_to_cart_count": int(m.get("METRIC_TYPE_ADD_TO_CART_COUNT") or 0),
        })
    return out


async def _save(session, model, rows: list[dict], tenant_id: str,
                 key_field: str, scrape_job_id=None) -> int:
    import uuid

    from sqlalchemy.dialects.postgresql import insert

    from app.utils.time import now_ist

    if not rows:
        return 0
    tid = uuid.UUID(str(tenant_id))
    stamped = now_ist()
    for r in rows:
        r["tenant_id"] = tid
        r["platform"] = "instamart"
        r["scrape_job_id"] = scrape_job_id
        r["scraped_at"] = stamped
        r.setdefault("campaign_id", None)
        # campaign_id splits one date+product/keyword into a row per
        # contributing campaign -- WITHOUT it in the key, two campaigns
        # advertising the same product on the same day would collide on the
        # same key and only the last-saved one would survive, silently
        # losing the other's spend.
        suffix = f"|{r['campaign_id']}" if r["campaign_id"] else ""
        r["upsert_key"] = f"instamart|{tid}|{r['date']}|{r[key_field]}{suffix}"

    deduped = {r["upsert_key"]: r for r in rows}
    rows = list(deduped.values())

    update_cols = [
        c.name for c in model.__table__.columns if c.name not in {"id", "upsert_key"}
    ]
    chunk = max(1, 32000 // max(1, len(model.__table__.columns)))
    for i in range(0, len(rows), chunk):
        stmt = (
            insert(model)
            .values(rows[i:i + chunk])
            .on_conflict_do_update(
                index_elements=["upsert_key"],
                set_={c: insert(model).excluded[c] for c in update_cols},
            )
        )
        await session.execute(stmt)
    return len(rows)


async def save_products_daily(session, tenant_id: str, rows: list[dict], scrape_job_id=None) -> int:
    from app.models import InstamartAdProductDaily
    n = await _save(session, InstamartAdProductDaily, rows, tenant_id, "candidate_id", scrape_job_id)
    logger.info(f"Instamart product-daily saved: {n} row(s)")
    return n


async def save_keywords_daily(session, tenant_id: str, rows: list[dict], scrape_job_id=None) -> int:
    from app.models import InstamartAdKeywordDaily
    n = await _save(session, InstamartAdKeywordDaily, rows, tenant_id, "keyword", scrape_job_id)
    logger.info(f"Instamart keyword-daily saved: {n} row(s)")
    return n


PRODUCTS_BATCH = "/api/v1/products/batch"
IMAGE_CDN_PREFIX = "https://media-assets.swiggy.com/swiggy/image/upload/fl_lossy,f_auto,q_auto,w_200/"


async def fetch_product_catalog(portal: PortalSession, account_id: str,
                                  candidate_ids: list[str]) -> list[dict]:
    """Product name + image for a set of candidate ids. `account_id` is
    unused by this endpoint (no account_id field in the captured request)
    but kept in the signature for symmetry with every other fetch here."""
    import uuid as _uuid

    body = {
        "request_context": {
            "request_id": str(_uuid.uuid4()),
            "request_time": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "client_id": "IM_ADS_EXTERNAL_DASHBOARD",
        },
        "ids": candidate_ids,
    }
    data = await portal.signed_post(PRODUCTS_BATCH, body)
    return data.get("products") or []


def parse_product_catalog(raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for p in raw:
        cid = p.get("id")
        if not cid:
            continue
        images = []
        for v in p.get("variations") or []:
            images.extend(v.get("images") or [])
        out.append({
            "candidate_id": cid,
            "product_name": p.get("parentProductName"),
            "image_url": (IMAGE_CDN_PREFIX + images[0]) if images else None,
        })
    return out


async def save_product_catalog(session, tenant_id: str, rows: list[dict]) -> int:
    import uuid

    from sqlalchemy.dialects.postgresql import insert

    from app.models import InstamartProductCatalog
    from app.utils.time import now_ist

    if not rows:
        return 0
    tid = uuid.UUID(str(tenant_id))
    stamped = now_ist()
    for r in rows:
        r["tenant_id"] = tid
        r["scraped_at"] = stamped

    stmt = (
        insert(InstamartProductCatalog)
        .values(rows)
        .on_conflict_do_update(
            index_elements=["tenant_id", "candidate_id"],
            set_={
                "product_name": insert(InstamartProductCatalog).excluded.product_name,
                "image_url": insert(InstamartProductCatalog).excluded.image_url,
                "scraped_at": insert(InstamartProductCatalog).excluded.scraped_at,
            },
        )
    )
    await session.execute(stmt)
    logger.info(f"Instamart product catalog saved: {len(rows)} row(s)")
    return len(rows)
