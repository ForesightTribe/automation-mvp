"""The write invariant — what a Zepto PUT is allowed to change.

Zepto has no targeted write: budget and bid are both a PUT of the WHOLE campaign
(`PUT /ads-bff/api/v1/campaigns/pla/{id}`), so every write restates the campaign's
cities, products, keywords, negative keywords, bids, dates and multipliers whether we
meant to touch them or not. Any field the translator gets wrong is written to a live
account, silently.

This module answers one question before the request goes out — the same one Blinkit's
`marketplaces/blinkit/payload.py` answers:

    Does this payload say the same thing as the campaign we just read,
    except for the change we intended?

## Why it compares against the DETAIL, not against another payload

`adapter._put_one_field` already diffs the payload before and after the mutation. That
is a SELF-consistency check — both copies come from the same translator — so a
translator that is wrong in both copies passes it. That is not hypothetical here: on
2026-09-21 three such bugs were found at once (ZC-A12..A14 — an empty city list, city
objects where the PUT wants ids, and negative keywords dropped, which would have DELETED
them), and the diff guard was green for all three.

So every rule below carries an **inverse**: it reads the payload's value back into the
GET's vocabulary and compares it to what Zepto reported for the campaign. The inverses
are written independently of `translate.py` on purpose — a check that calls the code it
is checking agrees with itself by construction.

## After the write, too

`check(..., shape=READBACK)` compares a FRESH read taken after the PUT with the payload we
sent, with nothing exempt. Blinkit does not do this; Zepto warrants it, because the body
carries everything and a server-side normalisation (a city dropped, a keyword re-matched)
would otherwise be invisible until someone looked at the dashboard.
"""
from datetime import date, datetime, timedelta, timezone

from campaign_manager.writes import WriteRefused

_IST = timezone(timedelta(hours=5, minutes=30))

# Write shapes. Each declares what it is ALLOWED to change.
BUDGET = "budget"        # adapter.apply_budget  — `daily_budget`
BID = "bid"              # adapter.apply_bid     — ONE (keyword, match_type)'s bid_value
READBACK = "readback"    # after a PUT: the campaign must now equal what we sent

INTENDED: dict[str, frozenset[str]] = {
    BUDGET: frozenset({"daily_budget"}),
    # A bid write exempts nothing wholesale: `keyword_bids` knows the ONE pair it may
    # change (passed as `keyword=`), and every other pair's bid is still checked.
    BID: frozenset(),
    READBACK: frozenset(),
}

ABSENT = object()


def _get(obj, *path):
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            return ABSENT
        obj = obj[key]
    return obj


def _cfg(detail: dict) -> dict:
    return detail.get("campaign_configs") or {}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _same(v):
    return v


# ── dates ───────────────────────────────────────────────────────────────────
# The GET returns `2026-08-21T12:20:30.808196+05:30`; the PUT sends `2026-08-21`. Echoing the
# timestamp back shifts the start (the golden test caught that once). Compared as a calendar
# date ON AN INDIAN CALENDAR, converted here independently of `translate._date_only`.

def _put_date(v):
    """A PUT date must be a BARE `YYYY-MM-DD`. Anything longer is refused as unparseable:
    echoing the GET's full timestamp is the bug that shifts a campaign's start, and slicing
    it to 10 characters here would make exactly that payload look fine."""
    if v is None:
        return None
    s = str(v)
    if len(s) != 10:
        return ("not a bare date", v)
    try:
        return date.fromisoformat(s)
    except ValueError:
        return ("unparseable", v)


def _get_date(raw):
    if raw is None:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return ("unparseable", raw)
    if d.tzinfo is not None:
        d = d.astimezone(_IST)
    return d.date()


# ── lifetime budget: the GET spells "none" as -1, the PUT as 0 ─────────────

def _lifetime_expected(d):
    b = d.get("budget")
    return 0.0 if b in (None, -1, -1.0) else _num(b)


# ── multipliers: the PUT adds a `time` key the GET never has ───────────────

def _mult_back(v):
    return {k: x for k, x in v.items() if k != "time"} if isinstance(v, dict) else v


# ── cities ──────────────────────────────────────────────────────────────────

def _mode(d) -> str:
    return (_cfg(d).get("city_targeting") or "ALL").upper()


def _include_expected(d):
    """The campaign's own chosen cities. For ALL there is nothing on the campaign to compare
    the brand-wide list against — `_structural` insists it is non-empty instead."""
    if _mode(d) == "ALL":
        return None
    return {c["city_id"] for c in d.get("city_targeting") or []
            if isinstance(c, dict) and c.get("city_id")
            and c.get("is_included", True) and c.get("is_active") is not False}


def _exclude_expected(d):
    if _mode(d) == "ALL":
        return set()
    return {c["city_id"] for c in d.get("city_targeting") or []
            if isinstance(c, dict) and c.get("city_id")
            and c.get("is_included") is False and c.get("is_active") is not False}


def _id_set(v):
    return {str(x) for x in v} if isinstance(v, list) else v


# ── keywords ────────────────────────────────────────────────────────────────
# Three rules over the same list, because they fail differently:
#   negative_keywords — dropping one is how every write would have deleted them (ZC-A14);
#   keywords          — the bidding set: no write may add or drop a (text, match) pair;
#   keyword_bids      — every pair's bid, except the one a bid write targets.

def _neg_back(v):
    if not isinstance(v, list):
        return v
    return {(k.get("text"), k.get("match_type")) for k in v if k.get("is_negative")}


def _neg_expected(d):
    return {(k.get("keyword"), k.get("match_type"))
            for k in d.get("keyword_config") or [] if k.get("is_negative")}


def _kw_back(v):
    if not isinstance(v, list):
        return v
    return {(k.get("text"), k.get("match_type")) for k in v if not k.get("is_negative")}


def _kw_expected(d):
    return {(k.get("keyword"), k.get("match_type"))
            for k in d.get("keyword_config") or [] if not k.get("is_negative")}


def _bids_back(v):
    if not isinstance(v, list):
        return v
    return {(k.get("text"), k.get("match_type")): _num(k.get("bid_value"))
            for k in v if not k.get("is_negative")}


def _bids_expected(d):
    return {(k.get("keyword"), k.get("match_type")): _num(k.get("bid_value"))
            for k in d.get("keyword_config") or [] if not k.get("is_negative")}


# ── The rules ───────────────────────────────────────────────────────────────
# (name, payload path, inverse, expected-from-detail, description). Every rule is EXACT:
# unlike Blinkit, no Zepto write we make is allowed to ADD anything either.

_RULES = (
    ("brand_id", ("brand_id",), _same, lambda d: d.get("brand_id"), "the ad account's brand"),
    ("campaign_type", ("campaign_type",), _same, lambda d: d.get("campaign_type"),
     "the campaign type"),
    ("campaign_sub_type", ("campaign_sub_type",), _same, lambda d: d.get("campaign_sub_type"),
     "the campaign sub-type"),
    ("campaign_name", ("campaign_name",), _same, lambda d: d.get("campaign_name"),
     "the campaign's name"),
    ("ro_id", ("ro_id",), lambda v: v or "", lambda d: d.get("ro_id") or "",
     "the release order"),
    ("budget_type", ("budget_type",), _same, lambda d: d.get("budget_type"),
     "the budget type"),
    ("bid", ("bid",), _num, lambda d: _num(d.get("bid") or 0), "the campaign-level bid"),
    ("daily_budget", ("daily_budget",), _num, lambda d: _num(d.get("daily_budget")),
     "the daily budget"),
    ("lifetime_budget", ("lifetime_budget",), _num, _lifetime_expected,
     "the lifetime budget (-1 on the campaign means none)"),
    ("bidding_strategy_type", ("bidding_strategy_type",), _same,
     lambda d: d.get("bidding_strategy_type"), "the bidding strategy"),
    ("start_date", ("start_date",), _put_date, lambda d: _get_date(d.get("start_date")),
     "the start date — a mangled one re-dates a live campaign"),
    ("end_date", ("end_date",), _put_date, lambda d: _get_date(d.get("end_date")),
     "the end date"),
    ("bid_multipliers", ("bid_multipliers",), _mult_back,
     lambda d: _cfg(d).get("multiplier_config") or {}, "the placement bid multipliers"),
    ("city_mode", ("geo_targeting", "type"), lambda v: (v or "").upper(), _mode,
     "whether the campaign runs in ALL cities or chosen ones"),
    ("city_include", ("geo_targeting", "city", "include"), _id_set, _include_expected,
     "the chosen cities"),
    ("city_exclude", ("geo_targeting", "city", "exclude"), _id_set, _exclude_expected,
     "the excluded cities"),
    ("products", ("product_config", "product_variant_ids"), _id_set,
     lambda d: {str(a["product_variant_id"]) for a in d.get("ad_assets_pla") or []
                if a.get("product_variant_id")}, "the advertised products"),
    ("product_mode", ("product_config", "type"), _same,
     lambda d: _cfg(d).get("product_targeting") or "MANUAL", "how products are chosen"),
    ("bid_targeting", ("bid_targeting", "targeting_type"), _same,
     lambda d: _cfg(d).get("bid_targeting"), "keyword vs auto bidding"),
    ("subcategories", ("bid_targeting", "subcategory_targeting"),
     lambda v: {str(x) for x in v} if isinstance(v, list) else v,
     lambda d: {str(x) for x in (d.get("subcategory_targeting") or [])},
     "the targeted subcategories"),
    ("negative_keywords", ("keyword_targeting",), _neg_back, _neg_expected,
     "the negative keywords — a PUT without them deletes them"),
    ("keywords", ("keyword_targeting",), _kw_back, _kw_expected,
     "the bidding keywords (text + match type) — nothing may be added or dropped"),
    ("keyword_bids", ("keyword_targeting",), _bids_back, _bids_expected,
     "every keyword's bid"),
    ("campaign_id", ("campaignId",), lambda v: str(v),
     lambda d: str(d["id"]) if d.get("id") else None, "which campaign this body is for"),
)

STRUCTURAL = frozenset({"bid_multipliers.time", "city_include(ALL)"})
"""Guarded by `_structural` rather than a detail comparison — named so the coverage test
counts them as covered."""


def _structural(detail: dict, payload: dict) -> list[str]:
    problems = []
    time_key = _get(payload, "bid_multipliers", "time")
    if time_key is not ABSENT and time_key != {"time": {}}:
        problems.append(f"bid_multipliers.time: the dashboard always sends "
                        f"{{'time': {{}}}}, got {time_key!r}")
    if _mode(detail) == "ALL":
        include = _get(payload, "geo_targeting", "city", "include")
        if include is ABSENT or not include:
            problems.append("city_include: an all-cities campaign must send the brand's full "
                            "city list, got none (targeting-options failed — ZC-A12)")
    return problems


def check(detail: dict, payload: dict, *, shape: str,
          keyword: tuple[str, str] | None = None) -> list[str]:
    """Every way `payload` disagrees with `detail`, except what `shape` may change. Pure.

    `keyword` = the one `(text, match_type)` a BID write targets. It must already exist on
    the campaign — a bid write changes a bid; it never adds a keyword.
    """
    intended = INTENDED.get(shape, frozenset())
    problems: list[str] = []
    for name, path, back, expected_of, description in _RULES:
        if name in intended:
            continue
        sent = _get(payload, *path)
        if sent is ABSENT:
            problems.append(f"{name}: missing from the payload ({description})")
            continue
        got, expected = back(sent), expected_of(detail)
        if expected is None and name != "end_date":
            continue                          # nothing on the campaign to compare against
        if name == "keyword_bids" and shape == BID and keyword is not None:
            if keyword not in expected:
                problems.append(f"keyword_bids: the campaign has no bidding keyword "
                                f"{keyword!r} — a bid write never adds one")
                continue
            got = {k: v for k, v in (got or {}).items() if k != keyword}
            expected = {k: v for k, v in expected.items() if k != keyword}
        if got != expected:
            problems.append(f"{name}: payload says {_show(got)} but the campaign is "
                            f"{_show(expected)} ({description})")
    return problems + _structural(detail, payload)


def _show(v) -> str:
    if isinstance(v, (set, frozenset)):
        return repr(sorted(v, key=str))
    if isinstance(v, dict):
        return repr(dict(sorted(v.items(), key=lambda kv: str(kv[0]))))
    return repr(v)


def _verifiable(detail: dict) -> bool:
    """A real campaign read, or the wreckage of a failed one? Every rule compares against
    `detail`, so a thin one would pass anything — exactly when a payload built from it is
    most dangerous."""
    return bool(detail) and bool(detail.get("campaign_type")) and bool(detail.get("campaign_name"))


def verify(detail: dict, payload: dict, *, shape: str, campaign_id,
           keyword: tuple[str, str] | None = None) -> None:
    """Raise `WriteRefused` unless `payload` restates `detail` faithfully. Called before
    every Zepto PUT; a refusal costs one write, never the run (the choke point catches it)."""
    if not _verifiable(detail):
        raise WriteRefused(
            f"refusing to write campaign {campaign_id} — the campaign detail is empty or "
            f"unreadable, so nothing about the payload can be verified. Nothing was sent.")
    problems = check(detail, payload, shape=shape, keyword=keyword)
    if problems:
        raise WriteRefused(
            f"refusing to write campaign {campaign_id} — this {shape} PUT would change "
            f"things it was not asked to: " + "; ".join(problems) + ". Nothing was sent.")
