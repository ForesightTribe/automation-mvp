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

## What counts as "our position": the BEST row that is ours, paid or not

Deepansh's call, 2026-09-02, and it is the better objective. The goal is *our product
visible at the target position, as cheaply as possible* — not *our ad specifically
winning a slot*.

An earlier version returned a position only for a SPONSORED row of ours, and reported
an organic-only appearance as "no decision". The reasoning was "a bid cannot move an
organic rank" — true of the organic ROW, but the wrong conclusion: a bid adds a
SPONSORED row higher up, which improves the best position our product occupies. So
best-position does respond to bidding.

Taking the best of both is also what makes the engine stop paying when it does not
need to. Organic at 2 against a target of 3 reads as holding, so drift-down trims the
bid, we lose the paid slot, and the product still sits at 2 — for free. The
sponsored-only model cannot even see that situation, and would keep bidding for a
placement already in hand.

Three outcomes:

1. **found** — the lowest position of any row that is ours, by product id or by
   `uclId` campaign. The *kind* (paid / organic / won by another of our keywords) is
   reported in the reason and the logs, because it still matters for knowing whether
   the ad spend is doing anything — it just does not change the decision.
2. **absent** — no row of ours anywhere. `bid.py` treats this as worse than every slot
   it could see and bids up (see `RAISE_WHEN_ABSENT`).
3. **unreadable** — we could not look. That is `fetch_positions`' job to raise, not
   this function's to guess.
"""
from scraper.platforms.zepto.public_data import ads

from app.utils.logger import logger


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def locate(results: list[dict], keyword: str, lat: float, lon: float, *,
           campaign_id, match_type: str, variant_ids: set[str] | list[str],
           brand_name: str | None = None) -> tuple[float | None, str]:
    """Find this rule's sponsored slot in ALREADY-FETCHED results (pure, no I/O).

    Returns (position | None, source). `None` means "no bid decision" — see the four
    outcomes in the module docstring; the source string says which one.

    Split from the fetch so several rules on the same (keyword, store) share one
    scrape: the results are identical, only the attribution differs.
    """
    log = logger.bind(tag=f"cm.pos.zepto[{keyword}]")
    want_campaign = str(campaign_id)
    want_kw, want_match = _norm(keyword), _norm(match_type)
    variants = {str(v) for v in (variant_ids or []) if v}

    mine: list[tuple[float, str]] = []      # (position, what kind of row it was)

    for r in results:
        pos = r.get("position")
        if pos is None:
            continue
        by_variant = bool(str(r.get("variant_id") or "") in variants and variants)

        if not r.get("is_ad"):
            # Organic. Only a product-id match can prove an organic row is ours —
            # there is no tracking id on one.
            if by_variant:
                mine.append((float(pos), "organic"))
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
        reason = "our product is not in these results"
        log.debug(f"@ ({lat},{lon}): {reason} ({len(results)} results)")
        return None, reason

    # Lowest wins — where a shopper actually sees us first. Our product can hold BOTH
    # an organic and a paid slot on one page (verified: `ricotta` at 8 organic and 9
    # sponsored), and the better of the two is the one that counts.
    pos, kind = min(mine, key=lambda x: x[0])
    log.debug(f"@ ({lat},{lon}): pos {pos:g} [{kind}] of {len(mine)} own row(s), "
              f"{len(results)} results")
    return pos, f"live({len(results)} results, {kind})"
