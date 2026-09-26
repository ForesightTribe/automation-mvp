"""Instamart account-wide daily ad metrics — `POST
/api/v1/advertiser/metrics/batch` with `dimensions: ["DIMENSION_TYPE_DAY"]`,
on the same signed data host and session as campaigns.py and the sales
report. This is the endpoint the portal's own trend chart uses.

Unlike `/api/v1/campaigns` (campaigns.py), spend genuinely respects the date
filter here: verified live, 8 days summed matched the portal's windowed
dashboard exactly on GMV, impressions AND spend (₹1,04,434.39, 3,08,311,
₹3,04,272 -- all exact). So this is the source for anything that needs a real
window -- the KPI strip's growth and the daily trend chart -- while
campaigns.py remains the source for per-campaign identity and lifetime totals.

One call covers the whole requested range (no per-day looping), so a backfill
of however much history the account has is a single request, not N.
"""
import datetime as dt

from app.utils.logger import logger
from scraper.platforms.instamart.dashboard_data.seller import endpoints as ep
from scraper.platforms.instamart.dashboard_data.seller.session import PortalSession

_IST_OFFSET = dt.timedelta(hours=5, minutes=30)

_METRICS = [
    "METRIC_TYPE_BUDGET_BURNT", "METRIC_TYPE_IMPRESSIONS", "METRIC_TYPE_CLICKS",
    "METRIC_TYPE_CTR", "METRIC_TYPE_ROI", "METRIC_TYPE_CONVERSION_RATE",
    "METRIC_TYPE_GMV", "METRIC_TYPE_CONVERSIONS", "METRIC_TYPE_ADD_TO_CART_COUNT",
]


def _epoch(d: dt.date, end_of_day: bool = False) -> int:
    """IST calendar date -> UTC epoch seconds, matching how the portal itself
    builds this filter (verified against a captured request: its 16-23 Sept
    IST window is exactly epoch 1789497000..1790188199)."""
    t = dt.time.max if end_of_day else dt.time.min
    local = dt.datetime.combine(d, t) - _IST_OFFSET
    return int(local.replace(tzinfo=dt.timezone.utc).timestamp())


def _body(account_id: str, start: dt.date, end: dt.date) -> dict:
    return {
        "account_id": account_id,
        "advertiser_metrics_queries": [
            {
                "query_id": "GRAPH_QUERY",
                "metrics": [{"name": m} for m in _METRICS],
                "dimensions": ["DIMENSION_TYPE_DAY"],
                "filters": {
                    "logical_operator": "LOGICAL_OPERATOR_AND",
                    "filters": [
                        {
                            "metric_filter": "METRIC_FILTER_TYPE_DATE",
                            "comparison_operator": "COMPARISON_OPERATOR_BETWEEN",
                            "values": [
                                {"i_value": _epoch(start)},
                                {"i_value": _epoch(end, end_of_day=True)},
                            ],
                        },
                    ],
                },
                "sort": {"sort_order": "SORT_ORDER_ASC", "dimension": "DIMENSION_TYPE_DAY"},
            }
        ],
    }


async def fetch_daily(portal: PortalSession, account_id: str,
                       start: dt.date, end: dt.date) -> list[dict]:
    """Every day's row in the range, one call."""
    data = await portal.signed_post(
        ep.ADVERTISER_METRICS_BATCH, _body(account_id, start, end)
    )
    for q in data.get("getAdvertiserMetricsResponse") or []:
        if q.get("queryId") == "GRAPH_QUERY":
            rows = q.get("metricsOnDimensionsList") or []
            logger.info(f"Instamart account daily: {len(rows)} day(s)")
            return rows
    return []


def parse_daily(raw: list[dict]) -> list[dict]:
    """One dict per day, shaped for `InstamartAdAccountDaily`."""
    out: list[dict] = []
    for grp in raw:
        dims = grp.get("dimensions") or []
        if len(dims) != 1 or dims[0].get("name") != "DIMENSION_TYPE_DAY":
            continue
        day = dt.date.fromisoformat(dims[0]["value"])
        m = {x["name"]: x.get("value") for x in grp.get("metrics") or []}
        out.append({
            "date": day,
            "spend": m.get("METRIC_TYPE_BUDGET_BURNT") or 0.0,
            "gmv": m.get("METRIC_TYPE_GMV") or 0.0,
            "impressions": int(m.get("METRIC_TYPE_IMPRESSIONS") or 0),
            "clicks": int(m.get("METRIC_TYPE_CLICKS") or 0),
            "ctr": m.get("METRIC_TYPE_CTR"),
            "add_to_cart_count": int(m.get("METRIC_TYPE_ADD_TO_CART_COUNT") or 0),
            "conversions": int(m.get("METRIC_TYPE_CONVERSIONS") or 0),
            "conversion_rate": m.get("METRIC_TYPE_CONVERSION_RATE"),
            "roi": m.get("METRIC_TYPE_ROI"),
        })
    return out


async def save_daily(session, tenant_id: str, rows: list[dict], scrape_job_id=None) -> int:
    import uuid

    from sqlalchemy.dialects.postgresql import insert

    from app.models import InstamartAdAccountDaily
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
        r["upsert_key"] = f"instamart|{tid}|{r['date']}"

    update_cols = [
        c.name for c in InstamartAdAccountDaily.__table__.columns
        if c.name not in {"id", "upsert_key"}
    ]
    stmt = (
        insert(InstamartAdAccountDaily)
        .values(rows)
        .on_conflict_do_update(
            index_elements=["upsert_key"],
            set_={c: insert(InstamartAdAccountDaily).excluded[c] for c in update_cols},
        )
    )
    await session.execute(stmt)
    logger.info(f"Instamart account daily saved: {len(rows)} row(s)")
    return len(rows)
