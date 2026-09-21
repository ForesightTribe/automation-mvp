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
    """Every sponsored-products campaign on the account, in ONE call.

    ⚠️ The list is DATE-SCOPED. A narrow window silently omits campaigns rather than
    erroring, so anything reading this to decide "what exists" must pass a generous
    window — the same hazard `cm sync-campaigns` guards with MIN_DAYS on Blinkit.
    """
    today = now_ist().date()
    params = {
        "selectedBrand": client.brand_id,
        "brand_id": client.brand_id,
        "categoryType": "sponsored_products",
        "campaign_category": "sponsored_products",
        "from_date": str(today - timedelta(days=days)),
        "to_date": str(today),
        "limit": "200",
        "page": "1",
        "sort_field": "nudges",
        "sort_order": "ASC",
        "date_field": "",
        "campaign_sub_types": "",
    }
    body = await client.get_json(ep.CAMPAIGNS, params=params)
    data = _unwrap(body)
    campaigns = data.get("campaigns") or []
    total = data.get("total_count")
    if total is not None and len(campaigns) < total:
        # Paging exists (`page`/`limit`); say so loudly rather than silently
        # under-reporting the account.
        logger.warning(
            f"Zepto returned {len(campaigns)} of {total} campaigns — raise `limit` "
            "or add paging before trusting this as the full account."
        )
    return campaigns


async def get_campaign_detail(client: ZeptoClient, campaign_id: int) -> dict:
    """One campaign's full configuration — the input to every write.

    NOT wrapped in `data`, unlike most Zepto responses.
    """
    return _unwrap(await client.get_json(ep.CAMPAIGN_PLA.format(id=campaign_id)))


async def get_targeting_options(client: ZeptoClient) -> dict:
    """Brand-level targeting vocabulary. Needed by `translate.to_put` for the city
    list when a campaign targets ALL cities."""
    return await client.get_json(ep.TARGETING_OPTIONS,
                                 params={"brand_id": client.brand_id})


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
    """
    return _unwrap(await client.get_json(ep.WALLET))


async def update_campaign(client: ZeptoClient, campaign_id: int,
                          payload: dict) -> dict:
    """PUT the WHOLE campaign. **Never call this directly.**

    Both budget and bid changes come through here, which is what makes it dangerous:
    everything the campaign is travels in `payload`, so a wrong body rewrites live
    targeting rather than failing. `adapter.py` builds the payload from a fresh read
    and refuses unless exactly the intended field differs.

    `retry_writes=False`: a 401 is safe to retry (rejected before processing), but a
    TIMEOUT is not — the write may have applied and we simply never heard the answer.
    Retrying that blindly turns a retry into a second unintended write.

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
    * **401** → `SessionExpired`. Not a verdict on this change: every later write in the
      run would fail the same way, which is exactly when a run should stop.
    """
    try:
        r = await client.request(method, path, json=body, retry_writes=False)
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
        raise SessionExpired(f"Zepto rejected the session (401) while trying to {what} — "
                             "nothing was changed; the session was taken over or expired")
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
