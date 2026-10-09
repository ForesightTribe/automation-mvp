"""Zepto position sourcing for the bid optimizer (D17 — MP-specific).

Finds where THIS rule's ad sits in consumer search. The scrape engine is the public
scraper (`scraper.platforms.zepto.public_data`), shared with the keyword scrape so a
Zepto change gets fixed once — the same arrangement Blinkit uses with
`live_position.py`.

## Attribution is by campaign id, not by guessing at product names

Every sponsored row carries a `uclId` naming the advertiser, the **campaign**, the
store, and the **campaign keyword** that won the slot. So unlike Blinkit — where
`positions.py` has to match product names on non-stopword tokens — we can ask
directly whether *this campaign* won *this keyword's* slot.

That matters more here than it would on Blinkit, because BrikOven **conquests
competitor brand names** (`bakers dozen bread`). A rule's keyword routinely does not
appear anywhere in our own product names, so a name-similarity fallback would be
actively wrong.

## The keyword in a uclId is the CAMPAIGN's, not the query

Zepto matches campaign keywords to shopper queries by phrase and semantically:
searching `sourdough bread` returned our ad won by `bakers dozen bread`. So a
campaign with several keywords can hold several slots on one page, each won by a
different keyword. Crediting all of them to whichever rule is being evaluated would
have several rules chasing one shared number — hence the match is on
**(campaign, keyword, match_type)**, never on campaign alone.

## What counts: our AD SLOT, never an organic listing

The target is an ad slot — the Nth sponsored listing on the page (campaign_manager/ad_slots.py).
Our slot is the best (lowest) sponsored row that is ours: won by this campaign, by any of its
keywords, or our product in a paid slot whose tracking id did not decode. The *kind* is reported
in the reason and the logs; it does not change the decision.

⚠️ CHANGED 2026-10-05. From 2026-09-02 an ORGANIC row of ours counted as our position too, so
organic at 2 against a target of 3 read as holding and the bid trimmed itself away. The engine
now pushes the ad to where the client asked, whatever organic does; organic listings are only
RECORDED (`organic_positions`), for a UI warning that the spend may buy visibility we already
have. The same rule holds on Blinkit — one meaning of "target" across marketplaces.

Three outcomes:

1. **found** — `slot` is our best ad slot.
2. **absent** — no sponsored row of ours. `bid.py` treats this as worse than every slot it could
   see and bids up (see `RAISE_WHEN_ABSENT`), even when we are listed organically.
3. **unreadable** — we could not look. That is `fetch_positions`' job to raise, not this
   function's to guess.
"""
from scraper.platforms.zepto.public_data import ads

from app.utils.logger import logger
from campaign_manager import ad_slots


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def locate(results: list[dict], keyword: str, lat: float, lon: float, *,
           campaign_id, match_type: str, variant_ids: set[str] | list[str],
           brand_name: str | None = None) -> ad_slots.Placement:
    """Find this rule's AD SLOT in ALREADY-FETCHED results (pure, no I/O).

    Returns an `ad_slots.Placement`. `slot` None = we hold no ad slot — see the outcomes in
    the module docstring; the reason says which one. Our organic listings ride along in
    `organic_positions` and never decide anything.

    Split from the fetch so several rules on the same (keyword, store) share one
    scrape: the results are identical, only the attribution differs.
    """
    log = logger.bind(tag=f"cm.pos.zepto[{keyword}]")
    want_campaign = str(campaign_id)
    want_kw, want_match = _norm(keyword), _norm(match_type)
    variants = {str(v) for v in (variant_ids or []) if v}

    mine: list[tuple[float, str]] = []      # (page position, what kind of ad row it was)
    organic: list[int] = []

    for r in results:
        pos = r.get("position")
        if pos is None:
            continue
        by_variant = bool(str(r.get("variant_id") or "") in variants and variants)

        if not r.get("is_ad"):
            # Organic: recorded for the overlap warning, never a slot. Only a product-id match
            # can prove an organic row is ours — there is no tracking id on one.
            if by_variant:
                organic.append(int(pos))
            continue

        # Sponsored. `uclId` names the campaign AND the campaign keyword that won it,
        # so we can say precisely why this row is ours.
        ucl = ads.parse_ucl_id(r.get("ucl_id"))
        if ucl.get("campaign_id") == want_campaign:
            same_kw = (_norm(ucl.get("keyword")) == want_kw
                       and _norm(ucl.get("match_type")) == want_match)
            mine.append((float(pos), "sponsored" if same_kw else
                         f"sponsored, won by {ucl.get('keyword') or '?'}"
                         f"/{ucl.get('match_type') or '?'}"))
        elif by_variant:
            # Our product in a paid slot we cannot attribute — another campaign of
            # ours, or a tracking id that did not decode. It is still our product in
            # front of the shopper, which is what the position measures.
            mine.append((float(pos), "sponsored, not attributable to this campaign"))

    if not mine:
        reason = ("organic only, no ad slot" if organic
                  else "our product is not in these results")
        log.debug(f"@ ({lat},{lon}): {reason} ({len(results)} results)")
        return ad_slots.place(results, None, organic, reason)

    # Lowest wins — the first ad of ours a shopper sees.
    pos, kind = min(mine, key=lambda x: x[0])
    placed = ad_slots.place(results, pos, organic, f"live({len(results)} results, {kind})")
    log.debug(f"@ ({lat},{lon}): {ad_slots.label(placed.slot, placed.page_position)} [{kind}] "
              f"of {len(mine)} own ad row(s), {len(results)} results")
    return placed
