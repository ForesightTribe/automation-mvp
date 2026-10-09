"""Ad slots — what a bid automation targets.

A target is an **ad slot**: the Nth sponsored listing on the search page, counted in page order
among the ads actually shown. Organic listings are not counted and never move a bid.

    page:   1  2  3  4  5  6  7  8  9  10 11
    ads:       ●        ●  ●        ●     ●      ads at page positions 2, 5, 6, 9, 11
    slot:      #1       #2 #3       #4    #5

"Ad #2" there is page position 5. On a keyword whose ads sit at 1, 3, 5, 7 the same target is
page position 3 — the client names the slot and never needs to know the layout.

Why slots and not page positions (2026-10-05): ad layouts differ by keyword, store and
marketplace. Blinkit's are mostly 1/5/9/13/17 but its first ad sits at 3, 9 or 13 on some
keywords; Zepto has no fixed layout at all (ads at 2, 4, 6, 7, 9, 11…). A page-position target
the layout cannot fill was either unreachable — the bid climbed to `max_bid` chasing it — or met
by an organic listing the bid never bought. Both Zepto rules targeted position 1, which no Zepto
ad was seen holding.

Only ads that are SHOWN are numbered. An empty slot in a marketplace's layout is not a slot here:
"Ad #2" is the second ad a shopper sees, wherever it lands.

**Organic listings.** Recorded (`organic_positions`), never decided on. They feed one thing: a
warning that we already appear organically above the slot being paid for
(`organic_overlap`). They are matched by product id only — a false warning gets ignored, and
then a true one does too.

Pure: no I/O. Each marketplace's matcher decides which rows are OURS; this module only counts.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Placement:
    """Where this rule's ad is on one search page.

    `slot`           our ad slot (1 = first ad on the page); None = we hold no ad slot
    `page_position`  the page position of that slot; None with `slot`
    `ad_positions`   page position of every ad on the page, in order — ours and everyone's
    `organic_positions`  page positions of our unpaid listings (product-id match only)
    `reason`         what the matcher saw, for the log ("live(30 results, sponsored)")
    """
    slot: int | None
    page_position: int | None
    ad_positions: tuple[int, ...]
    organic_positions: tuple[int, ...]
    reason: str


def ad_positions(results) -> tuple[int, ...]:
    """The page position of every sponsored row, in page order. A position is counted once:
    it is one place on the page whatever else rode along with it."""
    return tuple(sorted({int(r["position"]) for r in results or ()
                         if r.get("is_ad") and r.get("position") is not None}))


def slot_of(page_position, ads: tuple[int, ...]) -> int | None:
    """Which ad slot a page position is — its 1-based place among `ads` — or None if no ad sits
    there."""
    if page_position is None:
        return None
    try:
        return ads.index(int(page_position)) + 1
    except ValueError:
        return None


def place(results, our_ad_position, organic, reason: str) -> Placement:
    """Build a Placement from a matcher's findings.

    `our_ad_position` = the page position of our BEST sponsored row (lowest), or None.
    `organic` = page positions of our unpaid rows."""
    ads = ad_positions(results)
    slot = slot_of(our_ad_position, ads)
    return Placement(
        slot=slot,
        page_position=int(our_ad_position) if slot is not None else None,
        ad_positions=ads,
        organic_positions=tuple(sorted({int(p) for p in organic or () if p is not None})),
        reason=reason,
    )


def page_position_of_slot(slot: int, ads) -> int | None:
    """Where ad slot `slot` sits on a page with ads at `ads`, or None when the page shows fewer
    ads than that."""
    ads = tuple(ads or ())
    if slot is None or slot < 1 or slot > len(ads):
        return None
    return int(ads[slot - 1])


def organic_overlap(target_slot: int, ads, organic) -> int | None:
    """Our best organic page position when it is ABOVE the target slot on this page, else None.

    "Above" = a smaller page position than the one the target slot occupies here. A page with
    fewer ads than the target has no such slot to compare with, so no overlap is claimed."""
    where = page_position_of_slot(target_slot, ads)
    best = min((int(p) for p in organic or ()), default=None)
    if where is None or best is None:
        return None
    return best if best < where else None


@dataclass(frozen=True)
class Overlap:
    """The organic-overlap warning for one automation (shown, never acted on).

    `stores` of `of` stores (that gave a reading recently) keep showing us organically above the
    target slot. The positions are from the newest such reading: our organic listings, and the
    page position the target slot sat at there."""
    stores: int
    of: int
    store_labels: tuple[str, ...]
    organic_positions: tuple[int, ...]
    target_page_position: int
    last_seen: object


def overlap_summary(reads, target_slot: int, *, min_reads: int = 2) -> Overlap | None:
    """Should this automation warn that it may be paying for visibility it already has?

    `reads` = its recent page readings across stores, newest first — rows carrying
    `merchant_id`, `store_label`, `ad_positions`, `organic_positions`, `observed_at`
    (`repo.recent_page_reads`, already capped to the last few per store).

    A store counts as overlapping when MOST of its recent readings show our organic listing
    above the target slot, and it has at least `min_reads` of them — one reading must not
    raise a flag, and a flag must not flicker on and off with every search."""
    by_store: dict[str, list] = {}
    for r in reads or ():
        by_store.setdefault(r.merchant_id or "", []).append(r)
    flagged, newest = [], None
    for rows in by_store.values():
        hits = [r for r in rows
                if organic_overlap(target_slot, tuple(r.ad_positions or ()),
                                   tuple(r.organic_positions or ())) is not None]
        if len(rows) >= min_reads and len(hits) * 2 > len(rows):
            flagged.append(rows[0])
            if newest is None or hits[0].observed_at > newest.observed_at:
                newest = hits[0]
    if not flagged:
        return None
    ads = tuple(newest.ad_positions or ())
    return Overlap(
        stores=len(flagged), of=len(by_store),
        store_labels=tuple(r.store_label or r.merchant_id for r in flagged),
        organic_positions=tuple(sorted({int(p) for p in newest.organic_positions or ()})),
        target_page_position=page_position_of_slot(target_slot, ads),
        last_seen=newest.observed_at,
    )


def label(slot: int | None, page_position: int | None = None) -> str:
    """How a slot is shown to people: `Ad #2 · position 5`, or `Ad #2` without a page position."""
    if slot is None:
        return "no ad slot"
    return f"Ad #{slot}" + (f" · position {page_position}" if page_position is not None else "")
