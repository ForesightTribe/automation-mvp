"""Multi-store coverage: which stores a bid decision counts, and the one position it acts on.

A keyword automation measures at up to three stores per city (`cm_city_stores` ranks: 1 is
the anchor, 2-3 validate it). The goal is the target AD SLOT at EVERY store where the
campaign can actually be sold, so the decision acts on the WORST slot among those stores.
("position" below means that slot — campaign_manager/ad_slots.py.)
"All eligible stores at target" and "the worst eligible store at target" are the same
statement — which is why `bid.compute_bid` needed no change: it is simply handed the binding
store's position.

**Stock.** A store counts only if the campaign could win there. Stock comes from one
brand-catalogue read per store (`campaign_manager/stock.py`), matched to the campaign's own
product ids:

    eligible      ≥1 campaign product listed AND in stock      → read it, it counts
    out of stock  listed, none in stock, whole brand seen       → skip it
    not listed    none listed, whole brand seen                 → skip it
    unknown       no read, a failed or partial read, no ids     → read it, it counts

⚠️ Only CONFIRMED absence of stock skips a store. "Not on this keyword's results page" is a
ranking fact — exactly the case where we must bid up — and an unknown must never be treated as
sold out, or a campaign climbing from its floor would be told to stop.

**Doubt.** A store whose reading can't be trusted this tick gets no vote this tick. That keeps
a bad reading from moving the bid in either direction:

    error      the search failed outright
    untrusted  it answered, but proves nothing: no products at all, cut short after page 1
               with our ad unseen, the campaign's products unreadable — or stock unknown
               with our ad not showing, WHILE another store gives a clear reading
    gave_up    not showing even at the ceiling for several checks — the ceiling can't buy a
               slot there, so it stops holding the bid at max for the rest of the window

"Stock unknown + not showing" is only doubtful when there is something better to go on. When
it is ALL we know (a new campaign, stock not readable yet) it still counts, so a climb from the
floor is never stopped.

Pure: no I/O, no marketplace, no DB. Unit-tested in tests/test_coverage.py.
"""
from dataclasses import dataclass, replace
from datetime import datetime

# Whether a store can serve this campaign at all.
ELIGIBLE = "eligible"
OUT_OF_STOCK = "out_of_stock"
NOT_LISTED = "not_listed"
UNKNOWN = "unknown"

# What happened at a store this tick.
SPONSORED = "sponsored"     # our ad holds a slot
ABSENT = "absent"           # a counted store where we hold no sponsored slot
SKIPPED = "skipped"         # excluded by confirmed stock — never read
ERROR = "error"             # the read failed
UNTRUSTED = "untrusted"     # the read answered but can't be trusted this tick
GAVE_UP = "gave_up"         # out of reach at the ceiling — not chased for the rest of the window

COUNTED = (SPONSORED, ABSENT)
UNUSABLE = (ERROR, UNTRUSTED)


@dataclass(frozen=True)
class StoreStock:
    """One store's catalogue read, as the stock cache holds it.

    `complete` = the read reached the end of our brand's products. Only a complete read may
    conclude that a product is NOT sold at the store; a capped or truncated one can only say
    what it saw."""
    complete: bool
    in_stock: dict[str, bool]           # product id → available now
    checked_at: datetime | None = None


def eligibility(campaign_pids, stock: StoreStock | None) -> str:
    """Can this campaign be sold at this store? See the module docstring for the four
    answers. `campaign_pids` are the campaign's product ids; stock for products belonging to
    OTHER campaigns never makes a store eligible."""
    pids = {str(p) for p in (campaign_pids or ()) if p}
    if not pids or stock is None:
        return UNKNOWN
    listed = pids & set(stock.in_stock)
    if any(stock.in_stock[p] for p in listed):
        return ELIGIBLE
    if not stock.complete:
        return UNKNOWN
    return OUT_OF_STOCK if listed else NOT_LISTED


def counts(elig: str) -> bool:
    """Is a store with this eligibility worth reading at all?"""
    return elig in (ELIGIBLE, UNKNOWN)


def absent_position(results: int) -> float:
    """Where a counted store without our ad sits, for the decision: just below the last
    result. A genuine lower bound, and it keeps escalation honest — still absent next tick
    reads as "not improved", exactly like a real slot that didn't move. Never shown to a
    client and never stored as a position.

    Still counted in RESULTS, not ads, now that the decision is in ad slots: a page can show
    fewer ads than the target (none at all, even), and "ads + 1" would then read as holding.
    There can never be more ad slots than results, so this stays worse than any real slot."""
    return float(results + 1)


@dataclass(frozen=True)
class Reading:
    """One store, one tick. `store` is anything carrying `label`, `rank` and `merchant_id`
    (repo.MeasurementStore in the engine).

    `position` is what the decision acts on: our AD SLOT (campaign_manager/ad_slots.py — 1 =
    the first ad on the page), or `absent_position` when ABSENT. Where that slot sits on the
    page is `page_position`; `ad_positions` / `organic_positions` describe the page for the
    log, History and the organic-overlap warning, and never decide anything."""
    store: object
    eligibility: str
    verdict: str
    position: float | None = None       # our ad slot, or `absent_position` when ABSENT
    results: int = 0                    # products on the results page
    detail: str = ""                    # what the matcher said, or why it was not counted
    page_position: int | None = None    # where our ad slot sits on the page
    ad_positions: tuple = ()            # page position of every ad on the page
    organic_positions: tuple = ()       # page positions of our unpaid listings


@dataclass(frozen=True)
class Outcome:
    """What the stores add up to.

    `decide`     — act on `binding.position` (the worst counted store)
    `no_stock`   — every store was skipped for confirmed stock: a shelf problem, not a bid one
    `unwinnable` — nothing counted; the stores left were given up at the ceiling
    `error`      — nothing counted and at least one store gave no usable reading;
                   `binding` is the first such reading

    `readings` is the tick's readings AFTER aggregation — a doubtful reading may have been
    set aside here — and is what gets logged and stored.
    """
    kind: str
    binding: Reading | None = None
    counted: int = 0
    excluded: int = 0
    readings: tuple = ()


def _clear(r: Reading) -> bool:
    """A reading good enough to overrule a doubtful one: our ad seen, or not seen at a store
    where stock is confirmed."""
    return r.verdict == SPONSORED or (r.verdict == ABSENT and r.eligibility == ELIGIBLE)


def _rank(r: Reading) -> int:
    return int(getattr(r.store, "rank", 1) or 1)


def aggregate(readings) -> Outcome:
    """Combine one tick's store readings into the single thing the bid acts on.

    The WORST counted position binds, because the goal is target at every store we can sell
    in. Ties go to the lower rank (the anchor first) so the store a decision is attributed to
    does not flap between two equal readings."""
    readings = list(readings)
    if not readings:
        return Outcome("error")
    if any(_clear(r) for r in readings):
        readings = [replace(r, verdict=UNTRUSTED,
                            detail="stock couldn't be confirmed and our ad isn't showing — left "
                                   "out while other stores give a clear reading")
                    if r.verdict == ABSENT and r.eligibility == UNKNOWN else r
                    for r in readings]
    counted = [r for r in readings if r.verdict in COUNTED]
    excluded = len(readings) - len(counted)
    frozen = tuple(readings)
    if counted:
        binding = max(counted, key=lambda r: (r.position, -_rank(r)))
        return Outcome("decide", binding, len(counted), excluded, frozen)
    unusable = next((r for r in readings if r.verdict in UNUSABLE), None)
    if unusable is not None:
        return Outcome("error", unusable, 0, excluded, frozen)
    gave_up_reading = next((r for r in readings if r.verdict == GAVE_UP), None)
    if gave_up_reading is not None:
        return Outcome("unwinnable", gave_up_reading, 0, excluded, frozen)
    return Outcome("no_stock", None, 0, excluded, frozen)


def gave_up(history, *, window_start: datetime, ceiling: int, ticks: int) -> bool:
    """Should this store stop being chased for the rest of the current window?

    `history` = this rule's recent readings at ONE store, newest first (`cm_bid_store_reads`
    rows: `verdict`, `bid`, `observed_at`). True when either:
      - the store was already given up in this window at a bid at or above today's ceiling
        (sticky — raising `max_bid` lifts it, because the old give-up bid is then below it); or
      - its last `ticks` readings in this window were all "not showing" at a bid already at
        the ceiling.

    Only this window counts: tomorrow's window starts from its floor and gets a fresh try.
    """
    if ticks <= 0:
        return False
    rows = [h for h in history if h.observed_at is not None and h.observed_at >= window_start]
    if any(h.verdict == GAVE_UP and h.bid is not None and h.bid >= ceiling for h in rows):
        return True
    recent = rows[:ticks]
    return len(recent) == ticks and all(
        h.verdict == ABSENT and h.bid is not None and h.bid >= ceiling for h in recent)


def unusable_streak(history, current_verdict: str) -> int:
    """How many checks in a row a store has given no usable reading, INCLUDING this one;
    0 when this one was usable. `history` = its earlier readings, newest first."""
    if current_verdict not in UNUSABLE:
        return 0
    streak = 1
    for h in history:
        if h.verdict not in UNUSABLE:
            break
        streak += 1
    return streak
