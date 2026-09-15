"""The Blinkit PUT body, derived from the campaign instead of typed out by hand.

Blinkit replaces the WHOLE campaign on every write, so the body has to restate ~26 fields
that we did not mean to change. The builders used to spell all of them out as literals:

    payload = {
        "name": detail.get("name", ""),
        "campaign_targeting": {"city_ids": "-1", ...},     # ← six weeks of pan-India
        ...
    }

Every field was an author's decision, a field nobody thought of simply was not there, and
"not there" means Blinkit resets it. That is how nine city-targeted campaigns were
broadened (docs §8.2b).

Here the payload is generated from `FIELDS` — one row per field, each saying where it goes
and how to derive it from the campaign. Three properties follow from the shape rather than
from anyone's diligence:

  - **A field cannot be forgotten**, because nobody types fields any more.
  - **A field cannot be quietly hardcoded.** A constant has to be an explicit `const(...)`
    row, which is visible in review, rather than a literal buried in 30 lines of dict.

⚠️ What this does NOT give you: verification. Building from a table and CHECKING against the
campaign are different jobs, and a wrong row here is still a wrong row — the table is our
code, so re-deriving a field from it and comparing would only prove the table agrees with
itself, which is exactly the blind spot that let `city_ids: "-1"` through. Independent
checking needs an inverse per field, and those live in `payload.py`. Coverage is tracked by
`test_payload_invariant.py::test_every_derived_field_is_checked`.

## Shapes

The three write types are genuinely different bodies, not one body with flags — a bid
UPDATE carries `repeat_order_suggestion` and a `campaign_data` with `ro_details`, a budget
UPDATE carries a slimmer `campaign_data` (and a different one again for BANNER_LISTING),
and a RESTART sends `advertiser_id: 0` with an empty `brand_name`. Each row declares the
shapes it belongs to, so those differences are data rather than branching.

## This is a refactor, not a rewrite

`tests/test_build_equivalence.py` asserts, for nine campaign shapes, that this produces
**exactly** what the hand-written builders produced — same fields, same values, same types.
The frozen fixtures there came from running the old builders. If a row here drifts, that
test fails before the marketplace ever sees it.
"""
from datetime import datetime, timedelta, timezone

from campaign_manager.marketplaces.blinkit import payload as pl

_IST = timezone(timedelta(hours=5, minutes=30))

# Shapes (re-exported from payload.py so callers need one import, not two).
BID = pl.BID
BUDGET = pl.BUDGET
RESTART = pl.RESTART

_UPDATES = frozenset({BID, BUDGET})
_ALL = frozenset({BID, BUDGET, RESTART})


# ── deriving values from the campaign ───────────────────────────────────────

def _ist(d: datetime) -> datetime:
    """A timestamp as it reads on an Indian calendar.

    Naive values are taken to be IST already — `today` comes from `datetime.now(_IST)` and
    the restart's dates are ours, not Blinkit's.

    The `except` is not defensive padding: Blinkit's no-end-date sentinel is
    `9999-12-31 18:29:59+00:00`, which converts to `23:59:59` IST on the same day with one
    second of headroom below `datetime.max`. A sentinel one second later would overflow,
    and a payload builder is the wrong place to raise — keep the date as stored.
    """
    if d.tzinfo is None:
        return d
    try:
        return d.astimezone(_IST)
    except (OverflowError, OSError, ValueError):
        return d


def fmt_date(ts) -> str:
    """Blinkit wants `M/D/YYYY`, unpadded, **in IST**. Year 9999 is its no-end-date sentinel.

    ⚠️ The timezone conversion is the point of this function, not a detail of it. Blinkit
    stores campaign dates in UTC and every Indian campaign starts at midnight IST, so
    `start_ts` reads `…T18:30:00+00:00` on the day BEFORE the campaign actually starts.
    This used to strip the offset (`.replace("+00:00", "")`) and take the date off the
    naive remainder, which put a start date one day early into every UPDATE payload —
    260 of 260 campaigns. Blinkit ignored it for months and then, overnight on 2026-09-15,
    began rejecting the whole request with `['Start Date of Campaign is not allowed to be
    changed']`: no bid write, no budget write, on any campaign (docs §8.2b).

    The single formatter. `payload._date_back` is its inverse and `payload._date_expected`
    reads the campaign's own date the same way — deliberately written out there rather than
    calling this, because a check that borrows the code it checks proves nothing (§8.2c).
    """
    if not ts:
        return ""
    if isinstance(ts, datetime):
        d = ts
    else:
        try:
            # "Z" → "+00:00" rather than being deleted: the offset has to SURVIVE the parse
            # for there to be anything to convert.
            d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return str(ts)
    d = _ist(d)
    return f"{d.month}/{d.day}/{d.year}"


def pids(detail: dict) -> str:
    """The campaign's products as Blinkit's comma-separated string.

    `pids` is a string on some campaigns, a list on others, and absent on a few — hence the
    fallback through `products`.
    """
    raw = detail.get("pids")
    if isinstance(raw, str) and raw:
        return raw
    if isinstance(raw, (list, tuple)) and raw:
        return ",".join(str(p) for p in raw if p)
    return ",".join(
        str(p.get("pid") or p.get("id") or p.get("sku_id"))
        for p in detail.get("products", []) or []
        if p.get("pid") or p.get("id") or p.get("sku_id")
    )


def _raw_keywords(detail: dict, *, nested_first: bool) -> list[dict]:
    """The campaign's keywords, as the old builders each found them.

    ⚠️ **The three builders disagreed about where keywords live, and this preserves that.**
    Blinkit returns them nested under `campaign_targeting.keyword_targeting` on some
    campaigns and at the top level on others. The bid and restart builders read nested-first
    with a top-level fallback; the budget builder read the **top level only** — so for the
    common case (nested) it found none and omitted `keyword_targeting` from the PUT
    entirely.

    That omission is evidently safe — budget writes run constantly and keywords survive
    them — so Blinkit reads a missing block as "leave them alone". It is reproduced rather
    than fixed because making budget writes start sending the keyword list would ENLARGE
    their blast radius: a write that currently cannot touch keywords would begin restating
    them all. That is a behaviour change, and it needs its own decision and its own test,
    not a silent ride-along in a refactor.
    """
    if nested_first:
        return (
            (detail.get("campaign_targeting") or {}).get("keyword_targeting", {}).get("keywords", [])
        ) or detail.get("keywords", []) or []
    return detail.get("keywords", []) or []


def keywords(detail: dict, *, nested_first: bool = True, force_max_boost_null: bool = False
             ) -> list[dict]:
    """Keyword targeting normalised to the shape the PUT expects.

    `force_max_boost_null` is the budget builder's quirk: it discards the campaign's own
    `max_boost` and sends null, where bid and restart writes preserve it.
    """
    out = []
    for kw in _raw_keywords(detail, nested_first=nested_first):
        name = kw.get("keyword", "")
        if not name:
            continue
        bids = []
        for b in kw.get("bids", []) or []:
            match = b.get("match_type", "EXACT")
            bids.append({
                "match_type": "EXACT" if match == "EXACT_MATCH" else match,
                "cpm": int(b.get("cpm", 0)),
                "max_boost": None if force_max_boost_null else b.get("max_boost"),
            })
        out.append({"keyword": name, "bids": bids})
    return out


def _str_ids(value) -> str:
    """Blinkit returns these id bags as a string on some campaigns and a list on others."""
    if isinstance(value, list):
        return ",".join(str(v) for v in value if v)
    return str(value) if value else ""


def _repeat_order(ctx: dict) -> dict:
    """A bid PUT must carry a repeat-order bid; Blinkit rejects the body without one.

    ⚠️ `min_cpm_config` is a BUDGET input despite the name, and this is the one place it is
    legitimately used as a bid — it is what the dashboard sends for the repeat-order slot,
    NOT a floor for keyword bids.
    """
    existing = ctx["detail"].get("repeat_order_suggestion") or {}
    if existing.get("bidding_strategy"):
        return existing
    campaign_type = ctx["detail"].get("campaign_type", "")
    return {"bidding_strategy": {"cpm": ctx["min_cpm"].get(campaign_type, 500)}}


def _campaign_data(ctx: dict) -> dict:
    """`campaign_data` is a different object in each shape — data, not branching.

    BANNER_LISTING budget writes are the sharp edge: ANY image field here trips Blinkit's
    "Cannot change listing spotlight image" validator, even when the value is unchanged, so
    that variant sends exactly three keys and `highlighted_pids` must be `""` (a string).
    """
    detail, shape = ctx["detail"], ctx["shape"]
    if shape == BID:
        existing = detail.get("campaign_data") or {}
        return {
            "pids": ctx["pids"],
            "brand_ids": existing.get("brand_ids", ""),
            "category_ids": existing.get("category_ids"),
            "ro_details": existing.get("ro_details") or {
                "ro_issue_date": None, "proof_url": None},
        }
    if shape == RESTART:
        existing = detail.get("campaign_data") or {}
        return {
            "brand_ids": existing.get("brand_ids") or _str_ids(detail.get("brand_ids")),
            "category_ids": existing.get("category_ids") or _str_ids(detail.get("category_ids")),
            "pids": ctx["pids"],
            "products": [],
            "ro_details": existing.get("ro_details") or {
                "ro_number": None, "ro_amount": None,
                "ro_issue_date": None, "proof_url": None},
        }
    if detail.get("campaign_type", "") == "BANNER_LISTING":
        return {
            "creative_type": "",
            "collection_id": detail.get("collection_id", ""),
            "highlighted_pids": "",
        }
    return {
        "creative_type": detail.get("creative_type", ""),
        "collection_id": detail.get("collection_id", ""),
        "pids": ctx["pids"],
    }


def _targeting(ctx: dict) -> dict:
    """`campaign_targeting`. `city_ids` comes from `payload.city_ids` — never a literal."""
    detail, shape = ctx["detail"], ctx["shape"]
    block = {"city_ids": pl.city_ids(detail), "is_extendable": False}
    if shape in _UPDATES:
        block["negative_keywords"] = detail.get("negative_keywords") or []
    if shape == BID:
        block["repeat_order_suggestion"] = _repeat_order(ctx)
        block["keyword_targeting"] = {"keywords": ctx["keywords"]}
    elif shape == RESTART:
        block["keyword_targeting"] = {"keywords": ctx["keywords"]}
    elif ctx["keywords"]:
        # A budget write omits the block entirely when the campaign has no keywords —
        # sending an empty one reads as "delete them all".
        block["keyword_targeting"] = {"keywords": ctx["keywords"]}
    return block


def const(value):
    """An explicit constant. Deliberately noisy: a hardcoded value has to say so here,
    where a reviewer sees it, instead of hiding as a literal inside a payload dict."""
    return lambda ctx: value


def _from(key: str, default=""):
    return lambda ctx: ctx["detail"].get(key, default)


# ── The field table ─────────────────────────────────────────────────────────
#
# (payload key, how to derive it, which shapes carry it)
FIELDS = (
    ("source_platform",       const("diy_dashboard_web"),                     _ALL),
    ("requested_by",          lambda c: c["requested_by"],                    _ALL),
    # A RESTART sends advertiser 0 — the server derives the account from the token for that
    # request type. An UPDATE must send the real id or it writes to the wrong account (B3).
    ("advertiser_id",         lambda c: 0 if c["shape"] == RESTART else c["advertiser_id"], _ALL),
    ("campaign_request_type", lambda c: "RESTART" if c["shape"] == RESTART else "UPDATE", _ALL),
    ("campaign_id",           lambda c: c["campaign_id"],                     _ALL),
    ("asset_type",            _from("campaign_type"),                         _ALL),
    ("name",                  _from("name"),                                  _ALL),
    ("objective_type",        _from("objective_type", "PERFORMANCE"),         _ALL),
    ("infinite_campaign",     _from("infinite_campaign", False),              _UPDATES),
    ("campaign_start",        lambda c: fmt_date(c["detail"].get("start_ts", "")), _UPDATES),
    ("campaign_end",          lambda c: fmt_date(c["detail"].get("end_ts", "")),   _UPDATES),
    ("cpm",                   _from("cpm", 0),                                _ALL),
    ("header_title",          _from("header_title"),                          _ALL),
    ("is_extendable",         const(None),                                    _UPDATES),
    ("brand_ids",             _from("brand_ids"),                             _UPDATES),
    ("brand_name",            _from("brand_name"),                            _UPDATES),
    ("pids",                  lambda c: c["pids"],                            _UPDATES),
    ("bidding_strategy",      lambda c: {"total_budget": c["budget"],
                                         "pacing_type": c["detail"].get("pacing_type", "DAILY")}, _ALL),
    ("campaign_data",         _campaign_data,                                 _ALL),
    ("campaign_targeting",    _targeting,                                     _ALL),
    # Bid-only extras — the dashboard's bid PUT carries these and the budget one does not.
    ("brand_page_id",         lambda c: c["detail"].get("brand_page_id") or "", frozenset({BID})),
    ("collection_id",         _from("collection_id"),                         frozenset({BID})),
    ("creative_type",         _from("creative_type"),                         frozenset({BID})),
    ("highlighted_pids",      lambda c: c["pids"],                            frozenset({BID})),
    ("image_url",             _from("mobile_image_url"),                      frozenset({BID})),
    ("store_name",            _from("store_name"),                            frozenset({BID})),
    # RESTART-only. `brand_name` is empty and the dates are ours, not the campaign's (AD4/AD5).
    ("image_url",             const(""),                                      frozenset({RESTART})),
    ("brand_name",            const(""),                                      frozenset({RESTART})),
    ("creative_type",         _from("creative_type"),                         frozenset({RESTART})),
    ("highlighted_pids",      lambda c: c["pids"],                            frozenset({RESTART})),
    ("collection_id",         _from("collection_id"),                         frozenset({RESTART})),
    ("store_name",            _from("store_name"),                            frozenset({RESTART})),
    ("campaign_start",        lambda c: fmt_date(c["today"]),                 frozenset({RESTART})),
    ("campaign_end",          const("12/31/9999"),                            frozenset({RESTART})),
    ("preview_image_url",     const(""),                                      frozenset({RESTART})),
)


def build(detail: dict, *, shape: str, campaign_id: int, requested_by: str,
          advertiser_id: int | None = None, budget=None, keyword_updates=None,
          min_cpm: dict | None = None, today: datetime | None = None) -> dict:
    """The PUT body for one write. Pure — no I/O, no marketplace.

    `budget` defaults to the campaign's own (an UPDATE restates it); a budget write and a
    restart pass the new one.
    """
    # Each shape's own notion of "the campaign's keywords" — see `_raw_keywords`.
    if shape == BID:
        # The bid merge preserves each keyword dict whole (`{**kw}`), so it starts from the
        # RAW list rather than the normalised one.
        kws = _apply_bid_updates(
            _raw_keywords(detail, nested_first=True), keyword_updates or [])
    elif shape == RESTART:
        kws = keywords(detail, nested_first=True)
    else:
        kws = keywords(detail, nested_first=False, force_max_boost_null=True)

    ctx = {
        "detail": detail,
        "shape": shape,
        "campaign_id": campaign_id,
        "requested_by": requested_by,
        "advertiser_id": advertiser_id,
        "pids": pids(detail),
        "keywords": kws,
        "min_cpm": min_cpm or {},
        "today": today or datetime.now(_IST),
        "budget": detail.get("campaign_budget", 0) if budget is None else budget,
    }
    out: dict = {}
    for key, derive, shapes in FIELDS:
        if shape in shapes:
            out[key] = derive(ctx)
    return out


def _apply_bid_updates(existing: list[dict], updates: list[dict]) -> list[dict]:
    """Swap in the new CPMs, KEEPING every other keyword.

    ⚠️ Sending only the changed keywords REPLACES the campaign's keyword list — the rest
    are deleted. This merge is the only thing standing between a bid change and that.
    """
    by_keyword = {u["keyword"]: u for u in updates}
    merged, seen = [], set()
    for kw in existing:
        name = kw.get("keyword", "")
        upd = by_keyword.get(name)
        if upd is None:
            merged.append(kw)
            continue
        bids = kw.get("bids") or [{"match_type": "EXACT", "cpm": 0, "max_boost": None}]
        merged.append({**kw, "bids": [{**b, "cpm": int(upd["cpm"])} for b in bids]})
        seen.add(name)
    for name, upd in by_keyword.items():
        if name not in seen:
            merged.append({"keyword": name, "bids": [{
                "match_type": upd.get("match_type", "EXACT"),
                "cpm": int(upd["cpm"]), "max_boost": None}]})
    return merged
