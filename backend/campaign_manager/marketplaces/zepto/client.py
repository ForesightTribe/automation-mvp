"""Typed calls against Zepto's ads API.

Thin: each function is one request plus enough unwrapping to hand back something
useful. All the awkwardness — the WAF token, the three load-bearing headers, the
401/429 recovery — lives in `transport.py`, so nothing here has to think about it.

Writes live in this module too but are only ever reached through
`campaign_manager/writes.py` (policy) and `adapter.py` (the one-field-diff
invariant). Nothing should call `update_campaign` directly.
"""
from datetime import timedelta
from typing import Any

import httpx

from app.utils.logger import logger
from app.utils.time import now_ist
from campaign_manager.marketplaces.zepto import endpoints as ep
from campaign_manager.marketplaces.zepto.transport import ZeptoClient
from campaign_manager.writes import SessionExpired, WriteRefused, WriteUnverified

# Zepto's own key for the response envelope. Most endpoints wrap in `data`; the
# campaign DETAIL does not, which is a real inconsistency worth handling once here
# rather than at every call site.
def _unwrap(body: dict) -> dict:
    inner = body.get("data")
    return inner if isinstance(inner, dict) else body


async def get_campaigns(client: ZeptoClient, days: int = 90) -> list[dict]:
    """Every campaign on the account (all tabs — `categoryType` is ignored), all pages.

    ⚠️ The list is DATE-SCOPED. A narrow window silently omits campaigns rather than
    erroring, so anything reading this to decide "what exists" must pass a generous
    window — the same hazard `cm sync-campaigns` guards with MIN_DAYS on Blinkit.

    ⚠️ PAGED, and `limit` is ignored: this used to ask once with `limit=200` and got the
    first page only (a recorded dashboard call: 8 of 21, `has_next: true`). Only `page`
    works (1-based) — the private scraper established that by elimination. The loop stops
    on `total_count`, on a page that adds no new ids, or at `_MAX_PAGES`: `has_next` alone
    has been seen staying true after the last campaign.
    """
    today = now_ist().date()
    by_id: dict = {}
    total = None
    for page in range(1, _MAX_PAGES + 1):
        params = {
            "selectedBrand": client.brand_id,
            "brand_id": client.brand_id,
            "categoryType": "sponsored_products",
            "campaign_category": "sponsored_products",
            "from_date": str(today - timedelta(days=days)),
            "to_date": str(today),
            "page": str(page),
            "sort_field": "nudges",
            "sort_order": "ASC",
            "date_field": "",
            "campaign_sub_types": "",
        }
        data = _unwrap(await client.get_json(ep.CAMPAIGNS, params=params))
        rows = data.get("campaigns") or []
        if total is None:
            total = data.get("total_count")
        before = len(by_id)
        for r in rows:
            if r.get("campaign_id") is not None:
                by_id[r["campaign_id"]] = r
        if not rows or len(by_id) == before or (total and len(by_id) >= total):
            break
    campaigns = list(by_id.values())
    if total and len(campaigns) < total:
        logger.warning(f"Zepto returned {len(campaigns)} of {total} campaigns — paging "
                       "stopped early; treat this as a partial account.")
    return campaigns


# A bound, not an expectation: rows come ~10 a page, so 30 pages = ~300 campaigns.
_MAX_PAGES = 30


async def get_keyword_floors(client: ZeptoClient, keywords: list[tuple[str, str]]
                             ) -> dict[tuple[str, str], int]:
    """Zepto's minimum bid per `(keyword, match_type)` — one request per
    `ep.KEYWORD_CONFIG_MAX` keywords (Zepto refuses a larger list with a 400).

    `POST /ads-bff/api/v1/keyword/config` {"keywords": [{keyword, match_type}]} →
    {"keywords": [{keyword, match_type, min_bid}]}. The direct analogue of Blinkit's
    `keywords/attributes`. Answers EXACT, PHRASE and BROAD (verified 2026-09-21 — an
    earlier note that it was EXACT-only was wrong or out of date).

    A keyword Zepto leaves out is simply ABSENT from the result. Absent means "unknown",
    never "no floor" — `pink toffee` was once absent and a write was still refused at ₹10.
    """
    out: dict[tuple[str, str], int] = {}
    for i in range(0, len(keywords), ep.KEYWORD_CONFIG_MAX):
        batch = keywords[i:i + ep.KEYWORD_CONFIG_MAX]
        body = {"keywords": [{"keyword": k, "match_type": m} for k, m in batch]}
        r = await client.request("POST", ep.KEYWORD_CONFIG, json=body)
        if r.status_code != 200:
            raise RuntimeError(f"Zepto keyword/config -> {r.status_code}: {r.text[:200]}")
        for k in (r.json() or {}).get("keywords") or []:
            if k.get("keyword") and k.get("match_type") and k.get("min_bid") is not None:
                try:
                    out[(k["keyword"], k["match_type"])] = int(round(float(k["min_bid"])))
                except (TypeError, ValueError):
                    continue
    return out


async def get_campaign_detail(client: ZeptoClient, campaign_id: int) -> dict:
    """One campaign's full configuration — the input to every write.

    NOT wrapped in `data`, unlike most Zepto responses.
    """
    return _unwrap(await client.get_json(ep.CAMPAIGN_PLA.format(id=campaign_id)))


async def get_targeting_options(client: ZeptoClient, *, campaign_type: str = "PLA",
                                campaign_sub_type: str = "AUCTION_UP_SELL") -> dict:
    """The brand's targeting vocabulary — `cities[{id, name}]` and categories.

    Needed by `translate.to_put` (an all-cities campaign's PUT carries the full city list)
    and by the catalogue, to turn a campaign's city ids into names.

    ⚠️ The params are the dashboard's own, and ALL of them matter (ZC-A12). With only
    `brand_id` the endpoint answers 200 with `{"cities": [], "categories": []}` —
    verified live 2026-09-21: 0 cities that way, 9 this way. That empty answer went
    unnoticed because the translator's golden test was captured WITH the params.
    """
    return await client.get_json(ep.TARGETING_OPTIONS, params={
        "brand_id": client.brand_id,
        "include": "category,geo",
        "campaign_type": campaign_type or "PLA",
        "campaign_sub_type": campaign_sub_type or "AUCTION_UP_SELL",
    })


async def get_metadata(client: ZeptoClient) -> dict:
    """Zepto's own bid/budget vocabulary and bounds — budget minimum, bidding
    strategies, multiplier types. Read rather than hardcoded where practical."""
    return _unwrap(await client.get_json(
        ep.CAMPAIGN_METADATA,
        params={"types": "budget_types,bidding_strategies,audience_targeting,"
                         "bid_multiplier_types"}))


async def get_wallet(client: ZeptoClient) -> dict:
    """Prepaid balance. A concept Blinkit has no equivalent for.

    Ads spend from a wallet, so a campaign can stall with a perfectly good budget
    when it empties. We can read this; `ads-wallet-recharge` is not in our
    permissions, so it is a warning signal and never something we can fix.

    ⚠️ The params are the dashboard's own (captured 2026-08-21) and required: without them
    Zepto answers 400 "invalid filters" — found 2026-09-23 on the FIRST real call, because
    nothing had ever called this. Same trap as `get_targeting_options` (ZC-A12). The date
    window covers the transaction summary that rides along; the balance is current either way.
    """
    today = now_ist().date()
    return _unwrap(await client.get_json(ep.WALLET, params={
        "start_date": (today - timedelta(days=30)).isoformat(),
        "end_date": today.isoformat(),
        "all_brands": "false",
        "brand_ids": client.brand_id,
    }))


async def update_campaign(client: ZeptoClient, campaign_id: int,
                          payload: dict) -> dict:
    """PUT the WHOLE campaign. **Never call this directly.**

    Both budget and bid changes come through here, which is what makes it dangerous:
    everything the campaign is travels in `payload`, so a wrong body rewrites live
    targeting rather than failing. `adapter.py` builds the payload from a fresh read
    and refuses unless exactly the intended field differs.

    A 401 is recovered inside the transport — a fresher stored session, else a new
    login — and resent once; that is safe because a 401 is rejected before Zepto
    processes anything. A TIMEOUT is never resent: the write may have applied and we
    simply never heard. That becomes `WriteUnverified` and is resolved by reading back.

    Failures are classified, not raised raw — see `_write`.
    """
    return await _write(client, "PUT", ep.CAMPAIGN_PLA.format(id=campaign_id),
                        payload, what=f"update campaign {campaign_id}")


async def set_status(client: ZeptoClient, campaign_id: int, *, pause: bool) -> dict:
    """Pause or activate. Dedicated endpoints — no whole-campaign body, so none of
    `update_campaign`'s blast radius.

    Cleaner than Blinkit, where `DELETE` means stop and a restart re-submits the
    whole campaign and needs a budget. Zepto's activate is an idempotent flip that
    keeps the prior budget and bids.
    """
    path = (ep.CAMPAIGN_PAUSE if pause else ep.CAMPAIGN_ACTIVATE).format(id=campaign_id)
    return await _write(client, "POST", path, {"brand_id": client.brand_id},
                        what=f"{'pause' if pause else 'activate'} campaign {campaign_id}")


def _reason(r: httpx.Response) -> str:
    """Zepto's own words for a failed call, or the start of the body when it gave none.

    Its errors are JSON (`{"message": "keyword bid validation failed: …"}`) — that sentence
    is what a person needs in History, so it is passed through rather than the status code.
    """
    try:
        body = r.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        for key in ("message", "error", "detail", "errors"):
            val = body.get(key)
            if isinstance(val, (list, tuple)):
                val = "; ".join(str(v) for v in val if v)
            if val:
                return str(val)[:200]
    return (r.text or "").strip()[:200] or f"HTTP {r.status_code}, empty body"


async def _write(client: ZeptoClient, method: str, path: str, body: dict, *,
                 what: str) -> dict:
    """Send one write and translate the outcome into what the choke point understands.

    `writes.py` treats three failures differently, and a bare `RuntimeError` is none of
    them — it escaped the choke point and aborted the whole engine run, skipping every
    campaign after the one that failed. So each outcome is sorted by the only question
    that matters afterwards: *could this have changed the campaign?*

    * **Nothing was sent / Zepto said no** → `WriteRefused`. A 4xx is a decision
      (`bid 8.00 is below minimum bid 10.00`), a connect failure never reached Zepto,
      and a WAF challenge (202/429) is answered by CloudFront before the origin sees it.
      One failed write with a reason; the run carries on.
    * **It may have landed** → `WriteUnverified`. A read timeout, a dropped connection,
      a 5xx (Zepto's gateway answers 500 when its upstream is slow, and the upstream may
      still finish), or a 200 we cannot parse. The choke point reads the value back to
      decide instead of guessing.
    * **401** → `SessionExpired`. Only reached once the transport has ALREADY tried to
      recover (adopt a fresher session, else log in, then resend) and still got a 401 —
      so the session genuinely cannot be restored, and every later write would fail the
      same way. That is when a run should stop.
    """
    try:
        r = await client.request(method, path, json=body)
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise WriteRefused(f"could not reach Zepto to {what} ({type(e).__name__}) — "
                           "nothing was sent") from e
    except httpx.TransportError as e:
        raise WriteUnverified(f"Zepto did not answer the request to {what} "
                              f"({type(e).__name__}) — it may still have applied") from e

    status = r.status_code
    if status == 200:
        try:
            return r.json()
        except ValueError as e:
            raise WriteUnverified(f"Zepto answered 200 to {what} but the reply was not "
                                  f"JSON ({(r.text or '')[:80]!r})") from e
    if status == 401:
        raise SessionExpired(f"Zepto rejected the session (401) while trying to {what}, "
                             "even after logging in again — nothing was changed")
    if status in (202, 429):
        raise WriteRefused(f"Zepto's firewall challenged the request to {what} "
                           f"(HTTP {status}) — nothing was sent")
    if status >= 500:
        raise WriteUnverified(f"Zepto answered {status} to {what} ({_reason(r)}) — its "
                              "gateway does this when the upstream is slow, so it may have "
                              "applied")
    raise WriteRefused(f"Zepto refused to {what}: {_reason(r)}")


def campaign_row(raw: dict) -> dict[str, Any]:
    """Flatten a list row's nested `{value,label}` wrappers into plain fields.

    Zepto wraps several list metrics as `{"value": "16", "label": "Low ad rank"}`
    so its UI can render an annotation. The label is advice for a human, not data.
    """
    def val(key: str):
        v = raw.get(key)
        return v.get("value") if isinstance(v, dict) else v

    return {
        "campaign_id": raw.get("campaign_id"),
        "campaign_name": raw.get("campaign_name"),
        "status": raw.get("status"),
        "daily_budget": raw.get("daily_budget"),
        "campaign_type": raw.get("campaign_type"),
        "campaign_sub_type": raw.get("campaign_sub_type"),
        "bid_targeting_type": raw.get("bid_targeting_type"),
        "cpc": val("smart_cpc"),
        "ad_position": val("ad_position"),
        "sov": val("sov"),
        "spend": raw.get("spend"),
        "impressions": raw.get("impressions"),
        "clicks": raw.get("clicks"),
        "roi": raw.get("roi"),
    }
