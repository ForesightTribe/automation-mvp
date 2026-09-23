"""GET campaign detail -> PUT campaign body.

Zepto's read and write shapes for the same campaign **are not the same shape**. The
PUT needs seven fields the GET does not return under those names, so a write cannot
echo back what a read produced — it has to be translated.

    GET  /ads-bff/api/v1/campaigns/pla/{id}   ->  detail (38 keys, its own vocabulary)
    PUT  /ads-bff/api/v1/campaigns/pla/{id}   <-  a whole-campaign body (18 keys)

## Why this file is the dangerous one

Budget and bid are both a **whole-campaign PUT**. Everything the campaign is —
geo targeting, the product list, every other keyword's bid — travels in that body.
Get one field wrong and the write does not fail; it silently rewrites live config.
A malformed Blinkit budget PUT sets a wrong budget. A malformed Zepto one can
unset the campaign's targeting.

So this module never invents a value. Every field below is copied, renamed, or
derived from something the GET actually returned, and `campaign_manager/tests/
test_zepto_translate.py` proves it against a real dashboard PUT.

## The trap that only the golden test caught

`start_date` comes back from the GET as a full ISO timestamp
(`2026-08-21T12:20:30.808196+05:30`) and the PUT wants a bare date (`2026-08-21`).
Echoing it back is either rejected or — worse — silently shifts the campaign's start
date. No amount of reading the payload reveals that; only diffing our output against
what the dashboard really sent.
"""
import copy
from datetime import datetime, timedelta, timezone
from typing import Any

_UNSET_LIFETIME_BUDGET = -1     # how the GET spells "no lifetime budget"
_IST = timezone(timedelta(hours=5, minutes=30))


def _date_only(value: Any) -> Any:
    """`2026-08-21T12:20:30.808196+05:30` -> `2026-08-21`. None stays None.

    The date is taken on an INDIAN calendar: a timestamp carrying any other offset is
    converted to IST first, so `2026-08-20T20:00:00Z` is the 21st, not the 20th (the
    trap Blinkit's `e684aa4` fixed). A value with no offset is Zepto's own IST. Anything
    unparseable falls back to the text before `T`, which `payload.py` then checks."""
    if not isinstance(value, str):
        return value
    try:
        d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return value.split("T")[0]
    if d.tzinfo is not None:
        d = d.astimezone(_IST)
    return d.date().isoformat()


def city_ids(targeting_options: dict) -> list[str]:
    """Every city id for the brand, from `/ads-bff/api/v1/brands/targeting-options`.

    Needed because the GET reports city targeting as the MODE ("ALL") while the PUT
    wants the explicit list the dashboard sends alongside it.
    """
    data = targeting_options.get("data", targeting_options)
    return [c["id"] for c in (data.get("cities") or []) if c.get("id")]


def keyword_key(text: str, match_type: str) -> tuple[str, str]:
    """A keyword's identity is the PAIR, never the text alone.

    Zepto bids the same keyword under EXACT / BROAD / PHRASE at genuinely different
    rates, so collapsing on text silently merges separate bid targets — and a bid
    write aimed at one would land on whichever matched first.
    """
    return (text, match_type)


def bids_from_detail(detail: dict) -> dict[tuple[str, str], int]:
    """Current bids, keyed by (keyword, match_type). Excludes negative keywords —
    they carry no bid and are not targets."""
    return {
        keyword_key(k["keyword"], k["match_type"]): k["bid_value"]
        for k in (detail.get("keyword_config") or [])
        if not k.get("is_negative")
    }


def to_put(detail: dict, targeting_options: dict, campaign_id: int) -> dict:
    """Build the PUT body that represents `detail` unchanged.

    The result is the campaign as it currently IS. Callers mutate exactly one field
    of it and send it back — see `adapter.apply_budget` / `apply_bid`, which also
    enforce that only that one field differs.

    ⚠️ Returned as a DEEP copy. The multipliers and subcategory list used to be the
    detail's own nested objects, so mutating the payload silently mutated the read it was
    built from — and `payload.check`, which compares the two, then saw them agree. Found by
    `test_zepto_payload_invariant` on 2026-09-21; harmless in the write path only because
    `_put_one_field` happens to deep-copy before mutating.
    """
    return copy.deepcopy(_to_put(detail, targeting_options, campaign_id))


def _to_put(detail: dict, targeting_options: dict, campaign_id: int) -> dict:
    cfg = detail.get("campaign_configs") or {}

    # bid_multipliers == campaign_configs.multiplier_config, plus a `time` key the
    # GET never returns. The dashboard always sends it, nested once.
    multipliers: dict[str, Any] = dict(cfg.get("multiplier_config") or {})
    multipliers.setdefault("time", {"time": {}})

    budget = detail.get("budget")
    lifetime = 0 if budget in (None, _UNSET_LIFETIME_BUDGET) else budget

    return {
        "brand_id": detail.get("brand_id"),
        "campaign_type": detail.get("campaign_type"),
        "campaign_sub_type": detail.get("campaign_sub_type"),
        "campaign_name": detail.get("campaign_name"),
        "ro_id": detail.get("ro_id") or "",
        "budget_type": detail.get("budget_type"),
        "bid": detail.get("bid") or 0,          # campaign-level; unused under KEYWORD
        "daily_budget": detail.get("daily_budget"),
        "lifetime_budget": lifetime,
        "bidding_strategy_type": detail.get("bidding_strategy_type"),
        "start_date": _date_only(detail.get("start_date")),
        "end_date": _date_only(detail.get("end_date")),
        "bid_multipliers": multipliers,
        "geo_targeting": geo_targeting(detail, targeting_options),
        "product_config": {
            "product_variant_ids": [
                a["product_variant_id"] for a in (detail.get("ad_assets_pla") or [])
                if a.get("product_variant_id")
            ],
            "type": cfg.get("product_targeting") or "MANUAL",
        },
        "bid_targeting": {
            "targeting_type": cfg.get("bid_targeting"),
            "subcategory_targeting": detail.get("subcategory_targeting") or [],
        },
        "keyword_targeting": keyword_targeting(detail),
        # A STRING here, though the campaign list returns an int — and the GET's own
        # `campaign_id` field is 0, so the id must come from the caller/URL.
        "campaignId": str(campaign_id),
    }


def geo_targeting(detail: dict, targeting_options: dict) -> dict:
    """The PUT's `geo_targeting`, exactly as the dashboard sends it.

    `campaign_configs.city_targeting` is the MODE:

    * **ALL** — the dashboard still sends the brand's FULL city list in `include`, taken
      from `targeting-options`. That list used to arrive empty (ZC-A12: we called the
      endpoint without the dashboard's `include=geo` params), so every write to an
      all-cities campaign sent `include: []`. `write_refusal` now refuses that case.
    * **MANUAL** — the GET lists the chosen cities as OBJECTS
      (`{city_id, is_included, is_active}`); the PUT wants plain id STRINGS (ZC-A13,
      verified against a dashboard save of 2427461 on 2026-09-21). Passing the objects
      through — which this did — sends a shape the dashboard never sends.
    """
    mode = ((detail.get("campaign_configs") or {}).get("city_targeting")) or "ALL"
    if mode == "ALL":
        return {"city": {"include": city_ids(targeting_options), "exclude": []},
                "type": mode}
    include: list[str] = []
    exclude: list[str] = []
    for c in detail.get("city_targeting") or []:
        if isinstance(c, str):                  # tolerate a bare id, should Zepto send one
            include.append(c)
            continue
        cid = c.get("city_id")
        if not cid or c.get("is_active") is False:
            continue
        (include if c.get("is_included", True) else exclude).append(cid)
    return {"city": {"include": include, "exclude": exclude}, "type": mode}


def keyword_targeting(detail: dict) -> list[dict]:
    """The PUT's `keyword_targeting`: negative keywords FIRST, then the bidding ones.

    ⚠️ Negatives travel in this same list (`{text, match_type, is_negative: true}`, no bid)
    — verified on the dashboard save of 2026-09-21. They used to be filtered OUT here
    (ZC-A14), and since this list replaces the campaign's keywords, every budget or bid
    write would have deleted them. The order mirrors the dashboard's.

    The dashboard also sends each bidding keyword's `min_bid`. We leave it out: an earlier
    dashboard save without it was accepted, and a value we would have to look up
    separately is one more thing that can be stale.
    """
    rows = detail.get("keyword_config") or []
    negatives = [{"text": k["keyword"], "match_type": k["match_type"], "is_negative": True}
                 for k in rows if k.get("is_negative")]
    bidding = [{"text": k["keyword"], "match_type": k["match_type"],
                "bid_value": k["bid_value"]}
               for k in rows if not k.get("is_negative")]
    return negatives + bidding


def write_refusal(payload: dict) -> str | None:
    """Why this PUT must not be sent, or None. Pure.

    The one-field diff guard compares our translation with ITSELF, so it cannot see a
    translation that is wrong in both copies. This catches the case that did happen: an
    empty city list, which on an all-cities campaign means `targeting-options` failed us,
    and on a chosen-cities campaign would target nowhere.
    """
    geo = payload.get("geo_targeting") or {}
    if not ((geo.get("city") or {}).get("include")):
        return (f"the campaign's city targeting ({geo.get('type') or 'unknown'}) came out "
                "with no cities — sending it could change where the campaign runs, so "
                "nothing was sent")
    return None


def diff(a: Any, b: Any, path: str = "") -> list[str]:
    """Every field that differs between two payloads, as readable paths.

    This is the safety mechanism, not a debugging aid: `adapter` refuses any write
    whose diff is not exactly the one field it meant to change. Lists compare
    order-insensitively when their members match, because the city list's order is
    not meaningful and a reordering is not a change.
    """
    out: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            out += diff(a.get(key), b.get(key), f"{path}.{key}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) == len(b) and sorted(map(str, a)) == sorted(map(str, b)):
            return out
        if len(a) != len(b):
            out.append(f"{path}: list len {len(a)} -> {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
    elif a != b:
        out.append(f"{path}: {a!r} -> {b!r}")
    return out
