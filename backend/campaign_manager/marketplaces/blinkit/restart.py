"""The Blinkit RESTART payload — resuming a stopped campaign.

Blinkit has no "set status" endpoint. Stopping is a bodiless `DELETE`, but **resuming is
a full campaign re-submission**: `PUT /adservice/v3/campaigns` with
`campaign_request_type: "RESTART"`, carrying the budget, the keywords, their bids, the
pids and the dates. Every one of those fields is rewritten by the call, which is why
`build()` is a pure function with a golden test pinned to a real captured payload
(tests/test_restart_payload.py) — a silent drift here silently rewrites a live campaign.

Its shape differs from BOTH existing builders in `client.py` (`update_campaign` and
`update_keyword_bids`), so it is deliberately separate rather than a third branch inside
them: `campaign_data` carries `products`/`brand_ids`/`category_ids`/`ro_details`, and
`campaign_targeting` omits `negative_keywords` and `repeat_order_suggestion`.

Two values are NOT taken from the campaign, because Blinkit's own dashboard doesn't send
them on a restart (docs/campaign-activation.md AD4):
  - `advertiser_id` is **0** — the server derives the account from the token + campaign
    for this request type (a budget UPDATE sends the real advertiser id).
  - `brand_name` is empty.

And two are deliberately ours:
  - `campaign_start` is **today** — Blinkit resets it on every restart; we cannot avoid it.
  - `campaign_end` is always the `12/31/9999` infinite sentinel (AD5), so a restarted
    campaign never carries an end date that could expire under a nightly automation.
"""
from datetime import datetime, timedelta, timezone

_IST = timezone(timedelta(hours=5, minutes=30))

RESTART_ADVERTISER_ID = 0          # AD4 — what the dashboard sends; not our stored id
NO_END_DATE = "12/31/9999"         # AD5 — Blinkit's "no end date" sentinel


def _fmt_date(d: datetime) -> str:
    """Blinkit wants M/D/YYYY with no zero padding."""
    return f"{d.month}/{d.day}/{d.year}"


def _num(value) -> int | float:
    """Send 200 rather than 200.0 when the value is whole — matches the captured payload."""
    f = float(value)
    return int(f) if f.is_integer() else f


def extract_pids(detail: dict) -> str:
    """The campaign's product ids as Blinkit's comma-separated string.

    `pids` comes back as a string on some campaigns and a list on others, and is absent
    entirely on a few — hence the fallback through the products list.
    """
    raw = detail.get("pids")
    if isinstance(raw, str) and raw:
        return raw
    if isinstance(raw, list) and raw:
        return ",".join(str(p) for p in raw if p)
    return ",".join(
        str(p.get("pid") or p.get("id") or p.get("sku_id"))
        for p in detail.get("products", [])
        if p.get("pid") or p.get("id") or p.get("sku_id")
    )


def extract_keywords(detail: dict) -> list[dict]:
    """Keyword targeting, normalised to the shape the PUT expects.

    Blinkit returns keywords in two places depending on the campaign; read the nested
    one first and fall back to the top level (same order as `adapter.read_bids`).
    """
    existing = (
        (detail.get("campaign_targeting") or {}).get("keyword_targeting", {}).get("keywords", [])
    ) or detail.get("keywords", []) or []

    out = []
    for kw in existing:
        name = kw.get("keyword", "")
        if not name:
            continue
        bids = []
        for b in kw.get("bids", []) or []:
            match = b.get("match_type", "EXACT")
            bids.append({
                "match_type": "EXACT" if match == "EXACT_MATCH" else match,
                "cpm": int(b.get("cpm", 0)),
                "max_boost": b.get("max_boost"),
            })
        out.append({"keyword": name, "bids": bids})
    return out


def _city_ids(detail: dict) -> str:
    """City targeting, preserved from the campaign.

    ⚠️ The captured payload sends `"-1"` (all cities) — but that campaign *is* all-India.
    Sending -1 for a city-targeted campaign would silently broaden its reach, so we
    preserve `region_ids` when the campaign has them. This is the one place we knowingly
    diverge from "mimic the capture", and it collapses back to `"-1"` for any campaign
    that is genuinely untargeted (including the captured one, so the golden test holds).
    """
    raw = detail.get("region_ids")
    if isinstance(raw, list):
        return ",".join(str(r) for r in raw) if raw else "-1"
    return str(raw) if raw is not None else "-1"


def build(detail: dict, *, campaign_id: int, budget: float, requested_by: str,
          today: datetime | None = None) -> dict:
    """The exact body to PUT to /adservice/v3/campaigns to resume `campaign_id`.

    `detail` must be a FRESH `get_campaign_detail` read (AD9) — everything in it is about
    to be written back, so a stale one reverts whatever changed in the meantime.
    """
    now = today or datetime.now(_IST)
    pids = extract_pids(detail)
    campaign_data = detail.get("campaign_data") or {}
    ro = campaign_data.get("ro_details") or {
        "ro_number": None, "ro_amount": None, "ro_issue_date": None, "proof_url": None,
    }

    return {
        "source_platform": "diy_dashboard_web",
        "requested_by": requested_by,
        "advertiser_id": RESTART_ADVERTISER_ID,
        "brand_name": "",
        "campaign_id": campaign_id,
        "objective_type": detail.get("objective_type", "PERFORMANCE"),
        "asset_type": detail.get("campaign_type", ""),
        "image_url": "",
        "header_title": detail.get("header_title", ""),
        "creative_type": detail.get("creative_type", ""),
        "highlighted_pids": pids,
        "collection_id": detail.get("collection_id", ""),
        "store_name": detail.get("store_name", ""),
        "name": detail.get("name", ""),
        "campaign_start": _fmt_date(now),
        "campaign_end": NO_END_DATE,
        "cpm": detail.get("cpm", 0),
        "campaign_data": {
            "brand_ids": campaign_data.get("brand_ids", ""),
            "category_ids": campaign_data.get("category_ids") or "",
            "pids": pids,
            "products": [],
            "ro_details": ro,
        },
        "bidding_strategy": {
            "total_budget": _num(budget),
            "pacing_type": detail.get("pacing_type", "DAILY"),
        },
        "campaign_targeting": {
            "city_ids": _city_ids(detail),
            "is_extendable": False,
            "keyword_targeting": {"keywords": extract_keywords(detail)},
        },
        "campaign_request_type": "RESTART",
        "preview_image_url": "",
    }


def overwrites(detail: dict, *, budget: float) -> dict:
    """A short summary of what this restart will re-submit, for the AD9 audit line.

    Not a full diff — just the fields a stale read would silently revert, in a form that
    is readable in Cloud Logging and cheap to scan when a bid mysteriously drops.
    """
    keywords = extract_keywords(detail)
    bids = {k["keyword"]: k["bids"][0]["cpm"] for k in keywords if k["bids"]}
    return {
        "budget": f"{detail.get('campaign_budget')}→{_num(budget)}",
        "keywords": len(keywords),
        "bids": ",".join(f"{k}:{v}" for k, v in sorted(bids.items())) or "none",
        "pids": extract_pids(detail) or "none",
        "start_date": f"→{_fmt_date(datetime.now(_IST))} (reset by Blinkit)",
    }
