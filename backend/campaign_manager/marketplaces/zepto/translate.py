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
from typing import Any

_UNSET_LIFETIME_BUDGET = -1     # how the GET spells "no lifetime budget"


def _date_only(value: Any) -> Any:
    """`2026-08-21T12:20:30.808196+05:30` -> `2026-08-21`. None stays None."""
    if not isinstance(value, str):
        return value
    return value.split("T")[0]


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
    """
    cfg = detail.get("campaign_configs") or {}

    # bid_multipliers == campaign_configs.multiplier_config, plus a `time` key the
    # GET never returns. The dashboard always sends it, nested once.
    multipliers: dict[str, Any] = dict(cfg.get("multiplier_config") or {})
    multipliers.setdefault("time", {"time": {}})

    # `campaign_configs.city_targeting` carries the MODE; the GET's own top-level
    # `city_targeting` list is populated only for explicit targeting. Under "ALL"
    # the dashboard still sends the brand's full city list, so mirror that rather
    # than sending an empty include and risking a change in meaning.
    mode = cfg.get("city_targeting") or "ALL"
    cities = (city_ids(targeting_options) if mode == "ALL"
              else list(detail.get("city_targeting") or []))

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
        "geo_targeting": {"city": {"include": cities, "exclude": []}, "type": mode},
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
        "keyword_targeting": [
            {"text": k["keyword"], "match_type": k["match_type"],
             "bid_value": k["bid_value"]}
            for k in (detail.get("keyword_config") or [])
            if not k.get("is_negative")
        ],
        # A STRING here, though the campaign list returns an int — and the GET's own
        # `campaign_id` field is 0, so the id must come from the caller/URL.
        "campaignId": str(campaign_id),
    }


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
