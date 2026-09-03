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
them on a restart (docs/campaign-manager.md §8.4):
  - `advertiser_id` is **0** — the server derives the account from the token + campaign
    for this request type (a budget UPDATE sends the real advertiser id).
  - `brand_name` is empty.

And two are deliberately ours:
  - `campaign_start` is **today**, because that is what the dashboard sends. Blinkit then
    IGNORES it — the campaign keeps its original start date (verified across two restarts
    of 574687, 2026-08-07). We send it for fidelity to the capture, not for effect.
  - `campaign_end` is always the `12/31/9999` infinite sentinel (AD5), so a restarted
    campaign never carries an end date that could expire under a nightly automation.
"""
from datetime import datetime, timedelta, timezone

from campaign_manager.marketplaces.blinkit import payload

_IST = timezone(timedelta(hours=5, minutes=30))

RESTART_ADVERTISER_ID = 0          # AD4 — what the dashboard sends; not our stored id
NO_END_DATE = "12/31/9999"         # AD5 — Blinkit's "no end date" sentinel


def _fmt_date(d: datetime) -> str:
    """Blinkit's M/D/YYYY. Delegates — `build.fmt_date` is the one formatter."""
    from campaign_manager.marketplaces.blinkit import build as builder
    return builder.fmt_date(d)


def _num(value) -> int | float:
    """Send 200 rather than 200.0 when the value is whole — matches the captured payload."""
    f = float(value)
    return int(f) if f.is_integer() else f


def extract_pids(detail: dict) -> str:
    """The campaign's product ids as Blinkit's comma-separated string. Delegates to
    `build.pids`; kept as a name because `overwrites()` and `cli cm status` call it."""
    from campaign_manager.marketplaces.blinkit import build as builder
    return builder.pids(detail)


def extract_keywords(detail: dict) -> list[dict]:
    """Keyword targeting in the shape the PUT expects. Delegates to `build.keywords`."""
    from campaign_manager.marketplaces.blinkit import build as builder
    return builder.keywords(detail, nested_first=True)


def build(detail: dict, *, campaign_id: int, budget: float, requested_by: str,
          today: datetime | None = None) -> dict:
    """The exact body to PUT to /adservice/v3/campaigns to resume `campaign_id`.

    Now a thin call into the shared field table (`build.py`) — the restart's differences
    from an UPDATE (advertiser 0, empty brand_name, today's start, the infinite end
    sentinel) are declared as rows there rather than as a separate hand-written dict. The
    golden test below still pins the result against the real captured payload, so the
    delegation cannot drift.

    `detail` must be a FRESH `get_campaign_detail` read (AD9) — everything in it is about
    to be written back, so a stale one reverts whatever changed in the meantime.
    """
    from campaign_manager.marketplaces.blinkit import build as builder

    return builder.build(detail, shape=builder.RESTART, campaign_id=campaign_id,
                         requested_by=requested_by, budget=_num(budget), today=today)


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
