"""The write invariant — what a Blinkit PUT is allowed to change.

Every Blinkit write is a whole-campaign re-submission (docs §8.2): we read the campaign,
rebuild its entire body, and PUT it back with one thing different. So the payload restates
the campaign's budget, dates, products, keywords, bids and city targeting whether we meant
to touch them or not, and **any field the builder gets wrong is silently written to a live
account**. That is not hypothetical — a hardcoded `"city_ids": "-1"` in the bid builder
broadened nine city-targeted campaigns to pan-India over six weeks (§8.2b).

This module answers one question before the request goes out:

    Does this payload say the same thing as the campaign we just read,
    except for the change we intended?

## Why it compares against the DETAIL, not against another payload

The obvious version of this check — build the payload twice, once with the change and once
without, and diff them — is worthless here. Both copies come from the same builder, so a
builder that hardcodes `-1` produces `-1` in both, the diff is empty, and the check passes
while the campaign is destroyed. It is a self-consistency check, and self-consistency is
exactly what a hardcoded constant has.

So every rule below carries an **inverse**: it reads the payload's own value back into the
detail's vocabulary (`"2010,2013"` → `[2010, 2013]`) and compares it to what Blinkit
actually reported for that campaign. A constant cannot survive that, because the constant
has to equal the campaign's real value to pass.

## Both directions live here

Each field appears once, with the transform that WRITES it and the inverse that reads it
back. `city_ids` used to have its writer in a separate `targeting.py` and its reader here —
one field's two halves in two files, free to drift apart with nothing forcing them to agree.
That is the shape of the original bug in miniature, so they are together now: change how a
field is written and its inverse is on the next line.

This is also the shape the builders will eventually be generated from — a field with a
`write`/`back` pair is one row of the field map, so folding the two together is the first
row of that work rather than a detour.

## What it deliberately does NOT check

Fields with no meaningful inverse (`source_platform`, `requested_by`, `advertiser_id`) and
fields a given request type is *supposed* to rewrite. Those are declared per shape in
`INTENDED`, so "the restart resets the dates" is written down as a decision rather than
discovered as a diff. Anything not in a rule is unchecked — this narrows the blast radius,
it does not eliminate it. The structural fix (build the payload by echoing the read instead
of hand-listing fields) is a separate, larger change; this is the guardrail that holds
until then, and stays useful afterwards.
"""
from datetime import datetime, timedelta, timezone

from campaign_manager.writes import WriteRefused

_IST = timezone(timedelta(hours=5, minutes=30))

# Request shapes. Each corresponds to one builder.
BID = "bid"            # client.update_keyword_bids   — one keyword's cpm changes
BUDGET = "budget"      # client.update_campaign       — total_budget changes
RESTART = "restart"    # restart.build                — budget + dates change

# What each shape is ALLOWED to rewrite. A rule named here is skipped for that shape,
# because changing it is the point of the call.
INTENDED: dict[str, frozenset[str]] = {
    # ⚠️ NOT `{"keywords"}`. A bid write changes a keyword's CPM, and the keyword rule
    # checks the keyword SET, not its bids — so exempting it here bought nothing and blinded
    # the check for the exact write type that caused the incident. A bid write may add a
    # keyword (the builder supports it) but may never drop one; that is the rule's NO_LOSS
    # mode, not an exemption.
    BID: frozenset(),
    BUDGET: frozenset({"budget"}),
    # A restart re-submits the campaign: it sets the budget, stamps today's start date and
    # forces the no-end-date sentinel (AD4/AD5). All three are deliberate.
    RESTART: frozenset({"budget", "campaign_start", "campaign_end",
                        # AD4 — the dashboard sends an empty brand_name on a restart.
                        "brand_name", "image_url"}),
    # ⚠️ There was a fourth shape here, BUDGET_NO_PIDS — `adapter.apply_budget` retried a
    # rejected budget write with `pids: ""` to work around a delisted catalog, and that
    # retry needed permission to rewrite the product list. Tested live 2026-09-04 (574687,
    # PRODUCT_LISTING): it does NOT clear the products (Blinkit ignores an empty list, so
    # it was never a second city bug) but it cannot succeed either — the validator fires on
    # the payload HAVING no pids ("Please select atleast one PID"). Removed 2026-09-05 with
    # the shape, because it also destroyed the diagnosis: its rejection replaced the real
    # one. If a pid-clearing write is ever needed again, declare the shape again — do not
    # widen an existing one.
}


ABSENT = object()
"""Distinct from `None`. A field the builder never sent is the builder's business; a field
sent AS null is a value, and a value gets checked. Collapsing the two let `city_ids: None`
through unexamined."""


def _get(obj: dict, *path: str):
    """Read a nested payload path. Returns `ABSENT` when any hop is missing — never None,
    because None is a legitimate value that must still be checked."""
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            return ABSENT
        obj = obj[key]
    return obj


# ── cities ──────────────────────────────────────────────────────────────────
#
# THE field. `"-1"` means all of India, and Blinkit accepts it silently on a campaign that
# was targeted at one city — which is how nine of them were broadened for six weeks.

def city_ids(detail: dict) -> str:
    """WRITE: the campaign's `region_ids` → `campaign_targeting.city_ids`.

    Returns Blinkit's comma-separated id string, or `"-1"` for a genuinely untargeted
    (pan-India) campaign. Every builder calls this; none may write the field itself.

    Raises `WriteRefused` when the campaign says it is city-targeted but its ids could not
    be read. That should be impossible; if it happens the detail read was partial or Blinkit
    renamed the field, and the only two options are to refuse or to broaden a live campaign
    to the whole country. We refuse — a failed write is visible and recoverable, a silently
    broadened campaign is neither.
    """
    ids = _city_id_list(detail.get("region_ids"))
    if ids:
        return ",".join(ids)
    if (detail.get("region_type") or "").strip().upper() == "CITY":
        raise WriteRefused(
            f"campaign reports region_type=CITY but no readable region_ids "
            f"({detail.get('region_ids')!r}) — refusing to write, because sending -1 "
            f"would broaden it to all of India"
        )
    return "-1"


def _city_id_list(raw) -> list[str]:
    """`region_ids` → a list of id strings. Blinkit returns it as a list of ints on some
    campaigns and an already-comma-separated string on others; both mean the same thing."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        parts = raw
    else:
        parts = [raw]
    return [s for s in (str(p).strip() for p in parts if p is not None) if s]


def _cities_back(value) -> set[str] | None:
    """`"2010,2013"` → `{"2010","2013"}`. `"-1"` (all India) → empty set."""
    if value is None:
        return None
    parts = [p.strip() for p in str(value).split(",")]
    ids = {p for p in parts if p and p != "-1"}
    return ids


def _cities_expected(detail: dict) -> set[str]:
    """READ-BACK: what the campaign's own targeting is, in the same vocabulary."""
    return {i for i in _city_id_list(detail.get("region_ids")) if i != "-1"}


# ── products ────────────────────────────────────────────────────────────────

def _pids_back(value) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return {str(p).strip() for p in value if str(p).strip()}
    return {p.strip() for p in str(value).split(",") if p.strip()}


def _pids_expected(detail: dict) -> set[str]:
    raw = detail.get("pids")
    if isinstance(raw, str) and raw:
        return {p.strip() for p in raw.split(",") if p.strip()}
    if isinstance(raw, (list, tuple)) and raw:
        return {str(p).strip() for p in raw if str(p).strip()}
    return {
        str(p.get("pid") or p.get("id") or p.get("sku_id")).strip()
        for p in detail.get("products", []) or []
        if p.get("pid") or p.get("id") or p.get("sku_id")
    }


# ── keywords ────────────────────────────────────────────────────────────────

def _keywords_back(value) -> set[str] | None:
    """The payload's keyword SET (not their bids — a bid write changes one of those)."""
    if not isinstance(value, list):
        return None
    return {k.get("keyword", "") for k in value if k.get("keyword")}


def _keywords_expected(detail: dict) -> set[str]:
    existing = (
        (detail.get("campaign_targeting") or {}).get("keyword_targeting", {}).get("keywords", [])
    ) or detail.get("keywords", []) or []
    return {k.get("keyword", "") for k in existing if k.get("keyword")}


# ── scalars and dates ───────────────────────────────────────────────────────

def _num(value):
    """Compare 200 and 200.0 as equal — Blinkit is inconsistent about which it returns."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _date_back(value):
    """`"8/6/2026"` → `(2026, 8, 6)`. The inverse of the builders' `_fmt_date`, written as
    a parse rather than a second copy of the formatter — duplicating the formatter is the
    mistake that produced the city bug in the first place."""
    if not value or not isinstance(value, str):
        return None
    parts = value.split("/")
    if len(parts) != 3:
        return None
    try:
        month, day, year = (int(p) for p in parts)
    except ValueError:
        return None
    return (year, month, day)


def _date_expected(detail: dict, key: str):
    """The campaign's own date as `(y, m, d)`, read on an Indian calendar.

    Blinkit returns ISO with assorted suffixes, in UTC. A campaign that starts at midnight
    IST is stored as `…T18:30:00+00:00` the previous day, so the offset has to be CONVERTED,
    not discarded — this used to strip it and compare the UTC date, which is the same
    mistake `build.fmt_date` made on the way out (§8.2b).

    ⚠️ The conversion is written out here rather than borrowed from `build.fmt_date`, and
    that duplication is deliberate. This is the rule's inverse: its whole job is to be an
    independent statement of what the campaign's date IS. A check that calls the formatter
    it is checking agrees with itself by construction and would pass a formatter that is
    wrong in both directions — the blind spot §8.2c exists for. Both halves still have to
    move together, and `tests/test_campaign_dates.py` fails if only one of them does.
    """
    raw = detail.get(key)
    if not raw or not isinstance(raw, str):
        return None
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is not None:
        try:
            d = d.astimezone(_IST)
        except (OverflowError, OSError, ValueError):
            # The no-end-date sentinel's neighbourhood — see `build._ist`. Compare the
            # date as stored rather than refusing the write over an unrepresentable one.
            pass
    return (d.year, d.month, d.day)


# ── The rules ───────────────────────────────────────────────────────────────
#
# `mode` is how the sent value must relate to the campaign's:
#   EXACT   — identical. For anything where BOTH gaining and losing is damage. City
#             targeting is the canonical case: `-1` *adds* the whole country.
#   NO_LOSS — the campaign's value must survive; additions are allowed. For collections
#             where dropping is the damage and adding is a legitimate operation (a bid
#             write may introduce a keyword; nothing may silently delete one).
EXACT, NO_LOSS = "exact", "no-loss"

# (name, payload path, inverse, expected-from-detail, mode, description)
_RULES = (
    ("cities", ("campaign_targeting", "city_ids"), _cities_back, _cities_expected, EXACT,
     "city targeting — '-1' means ALL OF INDIA and Blinkit accepts it silently"),
    ("keywords", ("campaign_targeting", "keyword_targeting", "keywords"),
     _keywords_back, _keywords_expected, NO_LOSS,
     "the campaign's keyword set — a partial list DELETES the rest"),
    ("pids", ("pids",), _pids_back, _pids_expected, NO_LOSS,
     "the advertised products"),
    ("budget", ("bidding_strategy", "total_budget"),
     _num, lambda d: _num(d.get("campaign_budget")), EXACT,
     "the daily budget"),
    ("pacing", ("bidding_strategy", "pacing_type"),
     lambda v: v, lambda d: d.get("pacing_type", "DAILY"), EXACT,
     "pacing type"),
    ("name", ("name",), lambda v: v, lambda d: d.get("name", ""), EXACT,
     "the campaign's name"),
    ("asset_type", ("asset_type",), lambda v: v, lambda d: d.get("campaign_type", ""), EXACT,
     "the campaign type"),
    ("objective_type", ("objective_type",), lambda v: v,
     lambda d: d.get("objective_type", "PERFORMANCE"), EXACT,
     "the objective"),
    # ── passthrough fields ──────────────────────────────────────────────────
    # Each is copied straight off the campaign, so the "inverse" is identity and the rule
    # is a second, independent statement of where the value comes from. Weak on its own —
    # but it is precisely strong enough to catch the bug class that started all this: a
    # literal typed into the builder instead of the campaign's own value.
    ("infinite_campaign", ("infinite_campaign",), lambda v: v,
     lambda d: d.get("infinite_campaign", False), EXACT, "the no-end-date flag"),
    ("cpm", ("cpm",), _num, lambda d: _num(d.get("cpm", 0)), EXACT, "the campaign CPM"),
    ("header_title", ("header_title",), lambda v: v,
     lambda d: d.get("header_title", ""), EXACT, "the creative's header"),
    ("brand_ids", ("brand_ids",), lambda v: v,
     lambda d: d.get("brand_ids", ""), EXACT, "the advertised brands"),
    ("collection_id", ("collection_id",), lambda v: v,
     lambda d: d.get("collection_id", ""), EXACT, "the collection"),
    ("creative_type", ("creative_type",), lambda v: v,
     lambda d: d.get("creative_type", ""), EXACT, "the creative type"),
    ("store_name", ("store_name",), lambda v: v,
     lambda d: d.get("store_name", ""), EXACT, "the store"),
    ("image_url", ("image_url",), lambda v: v,
     lambda d: d.get("mobile_image_url", ""), EXACT, "the creative image"),
    ("brand_page_id", ("brand_page_id",), lambda v: v,
     lambda d: d.get("brand_page_id") or "", EXACT, "the brand page"),
    # Checked on updates; a RESTART deliberately blanks it (AD4) and declares that in INTENDED.
    ("brand_name", ("brand_name",), lambda v: v,
     lambda d: d.get("brand_name", ""), EXACT, "the advertised brand"),
    # `highlighted_pids` and `campaign_data.pids` restate the product list, so they carry
    # the same loss risk as `pids` itself and get the same NO_LOSS treatment.
    ("highlighted_pids", ("highlighted_pids",), _pids_back, _pids_expected, NO_LOSS,
     "the highlighted products"),
    ("campaign_data.pids", ("campaign_data", "pids"), _pids_back, _pids_expected, NO_LOSS,
     "the products inside campaign_data"),
    # Dates are checked because `_fmt_date` reformats them on every write, so a mangled
    # conversion silently re-dates a live campaign. A RESTART is allowed to change both.
    ("campaign_start", ("campaign_start",), _date_back,
     lambda d: _date_expected(d, "start_ts"), EXACT, "the campaign's start date"),
    ("campaign_end", ("campaign_end",), _date_back,
     lambda d: _date_expected(d, "end_ts"), EXACT, "the campaign's end date"),
)


# ── structural rules ────────────────────────────────────────────────────────
#
# A handful of fields have no counterpart on the campaign, so the detail comparison has
# nothing to say about them. Most are harmless constants — get one wrong and Blinkit rejects
# the request, which is loud. `advertiser_id` is the exception: it is the ACCOUNT the write
# lands in, a wrong one spends someone else's money, and Blinkit publishes it nowhere in its
# read APIs, so there is nothing to compare against. It gets asserted instead: an UPDATE
# must carry a real positive id, a RESTART must carry 0 (AD4).
#
# There is deliberately no check for the old hardcoded `234` here. That value came from a
# fallback in `get_advertiser_id()` which now raises instead, no stored account holds it,
# and a guard against a value that can no longer occur is just a magic number keeping the
# memory of a deleted bug alive.

STRUCTURAL_FIELDS = frozenset({"advertiser_id"})
"""Fields guarded by `_structural` rather than by a detail comparison. Named so the coverage
ratchet counts them as covered — otherwise closing a gap this way looks like leaving one."""

def _structural(payload: dict, shape: str) -> list[str]:
    """Problems visible in the payload alone. Pure."""
    problems = []
    adv = _get(payload, "advertiser_id")
    if adv is not ABSENT:
        if shape == RESTART:
            if adv != 0:
                problems.append(
                    f"advertiser_id: a RESTART must send 0 (the server derives the account "
                    f"from the token for that request type), got {adv!r}")
        elif not isinstance(adv, int) or adv <= 0:
            problems.append(
                f"advertiser_id: an UPDATE must carry the tenant's real ad-account id, "
                f"got {adv!r}")
    return problems


def check(detail: dict, payload: dict, *, shape: str) -> list[str]:
    """Every way `payload` disagrees with `detail`, ignoring what `shape` may change.

    Pure. Returns a list of human-readable mismatches, empty when the payload is faithful.
    Separated from `verify` so it is testable without exceptions and so a caller that wants
    to warn rather than refuse can.
    """
    intended = INTENDED.get(shape, frozenset())
    problems: list[str] = []
    for name, path, back, expected_of, mode, description in _RULES:
        if name in intended:
            continue
        sent = _get(payload, *path)
        if sent is ABSENT:
            # Absent is not the same as wrong: a campaign with no keyword targeting sends
            # no `keyword_targeting` block at all. This checks what IS sent; whether a
            # field belongs in this shape is the builder's business.
            continue
        got, expected = back(sent), expected_of(detail)
        if expected is None:
            # We could not read the campaign's own value, so there is nothing to compare
            # against. Not a pass — an unverifiable field, which `_verifiable` guards
            # against wholesale so this can never become "everything is fine".
            continue
        if mode == NO_LOSS:
            lost = (expected - got) if isinstance(got, set) else expected
            if lost:
                problems.append(
                    f"{name}: payload drops {sorted(lost)!r} that the campaign has "
                    f"({description})")
        elif got != expected:
            problems.append(
                f"{name}: payload says {got!r} but the campaign is {expected!r} "
                f"({description})")
    return problems + _structural(payload, shape)


def _verifiable(detail: dict) -> bool:
    """Is this detail a real campaign read, or the wreckage of a failed one?

    Every rule compares the payload against `detail`, so an empty or thin detail makes the
    whole check vacuous — it would pass anything, exactly when the payload built from that
    same thin read is at its most dangerous. `_fetch` turns a Blinkit error page into `{}`,
    so this is a reachable state, not a hypothetical.
    """
    return bool(detail) and bool(detail.get("campaign_type") or detail.get("name"))


def verify(detail: dict, payload: dict, *, shape: str, campaign_id: int | None = None) -> None:
    """Raise `WriteRefused` unless `payload` restates `detail` faithfully.

    Called by every builder immediately before the PUT. A refusal is caught at the write
    choke-point and logged as a rejected write, so one bad campaign costs one write rather
    than the whole run.
    """
    where = f"campaign {campaign_id} " if campaign_id is not None else ""
    if not _verifiable(detail):
        raise WriteRefused(
            f"refusing to write {where}— the campaign detail is empty or unreadable, so "
            f"nothing about this payload can be verified. A payload built from a failed "
            f"read is the case this check exists for."
        )

    problems = check(detail, payload, shape=shape)
    if not problems:
        return
    raise WriteRefused(
        f"refusing to write {where}— this {shape} PUT would change fields it was not "
        f"asked to: " + "; ".join(problems)
    )
