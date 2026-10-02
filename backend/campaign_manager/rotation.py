"""Store rotation: where a ROTATING marketplace measures a keyword this tick (C6, Zepto).

Blinkit reads every frozen store of a city each tick and bids for the worst one that can sell
(`coverage.py`). Zepto can't afford that — its anonymous search allows a few requests a
minute — and it also can't tell a stock-out from being outbid by the keyword search alone,
because Zepto's search HIDES sold-out products (0 sold-out rows in 6,073 keyword results and
in 1,495 brand-search rows, Sept 2026). So Zepto measures at ONE store per tick and walks the
city's ranked set only when that store can't sell the campaign (design agreed 2026-09-24):

  1. Each window starts at store 1.
  2. Our ad shows → a normal tick; showing proves the product is in stock.
  3. Our ad is missing → one own-brand search at that store (the engine does it, through
     `stock.py`). In stock → genuinely outbid → the normal raise. Not in stock → HOLD the bid,
     and the NEXT tick measures at the next store (1 → 2 → 3 → 1 …). At most one hop per
     tick, so the worst tick is two searches.
  4. A full cycle with no store able to sell → OUT-OF-STOCK REST: the bid stays where it is
     (never lowered — a Zepto bid covers every targeted city, and an ad nobody sees costs
     nothing on CPC), and one store is checked every `rest_minutes`, still in rotation, until
     one can sell again.
  5. Staying on store 2 after store 1 restocks is fine — any store that sells the product is
     a valid place to measure; the cycle comes back round to store 1 by itself.
  6. Moving to a different store is a different auction, so the rule's learned state (raise
     step, drift, relaxed target) starts fresh there.

Stateless. Everything is derived from the rule's recent per-store readings
(`cm_bid_store_reads`, one row per store actually read), so there is no rotation column to
keep in step and a failed tick simply leaves the next one where it was.

Pure: no I/O, no marketplace, no DB. Unit-tested in tests/test_rotation.py.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from campaign_manager import coverage

# Readings that prove this store can't sell the campaign right now.
CANT_SELL = (coverage.OUT_OF_STOCK, coverage.NOT_LISTED)


@dataclass(frozen=True)
class Plan:
    """Where this tick measures, and why.

    `store`        — the store to read this tick, or None: resting, and no check is due yet.
    `rank`         — its 1-based place in the set (for "store 2 of 3").
    `switched`     — a different store from the one the rule's learned state came from, so
                     that state must start fresh.
    `resting`      — the last full cycle found no store that can sell.
    `rest_since`   — when the current run of stock-outs began (resting only).
    `next_check_at` — when a resting rule is next checked (resting and not due only).
    `upcoming`     — the store that next check will read (resting and not due only).
    """
    store: object | None
    rank: int = 1
    switched: bool = False
    resting: bool = False
    rest_since: datetime | None = None
    next_check_at: datetime | None = None
    upcoming: object | None = None


def cant_sell(reading) -> bool:
    """Did this reading prove the store can't sell the campaign?"""
    return getattr(reading, "eligibility", None) in CANT_SELL


def _in_window(history, window_start: datetime) -> list:
    return [h for h in history
            if getattr(h, "observed_at", None) is not None and h.observed_at >= window_start]


def _failing_run(rows, ids=None) -> list:
    """The newest-first run of readings that each proved a stock-out. With `ids` (the current
    set), the run also stops at a store that has LEFT the set: a stock-out there says nothing
    about the stores measured now — and counting it once dated a rest from a store the client
    had already replaced ("nothing sellable since 12:01", 2026-10-02, when the new set's first
    stock-out was 12:16)."""
    run = []
    for h in rows:
        if not cant_sell(h) or (ids is not None and h.merchant_id not in ids):
            break
        run.append(h)
    return run


def is_resting(stores, rows) -> bool:
    """Has a whole cycle — every store in the set — come back unable to sell, with nothing
    in between that could? `rows` = this window's readings, newest first."""
    ids = {s.merchant_id for s in stores}
    run = _failing_run(rows, ids)
    return bool(ids) and ids <= {h.merchant_id for h in run}


def plan(stores, history, *, window_start: datetime, now: datetime,
         rest_minutes: float) -> Plan:
    """Where to measure this tick. `stores` = the city's ranked set (anchor first);
    `history` = this rule's readings, NEWEST FIRST, across every store."""
    stores = list(stores)
    if not stores:
        return Plan(None)
    rows = _in_window(history, window_start)
    ids = [s.merchant_id for s in stores]
    # Where the rule's learned state (last position, raise step, drift) was earned: the
    # newest reading that fed a decision. A tick that failed or held says nothing about it.
    learned_at = next((h.merchant_id for h in rows if h.verdict in coverage.COUNTED), None)

    def _at(i: int, **kw) -> Plan:
        store = stores[i]
        return Plan(store, rank=i + 1,
                    switched=learned_at is not None and learned_at != store.merchant_id, **kw)

    if not rows:
        return _at(0)                                   # a new window: store 1
    last = rows[0]
    if last.merchant_id not in ids:
        return _at(0)                                   # the set changed under us: start over
    i = ids.index(last.merchant_id)
    if not cant_sell(last):
        return _at(i)                                   # stay where we are
    nxt = (i + 1) % len(stores)
    if not is_resting(stores, rows):
        return _at(nxt)                                 # hop — one store per tick
    since = _failing_run(rows, set(ids))[-1].observed_at
    due = last.observed_at + timedelta(minutes=rest_minutes)
    if now < due:
        return Plan(None, rank=nxt + 1, resting=True, rest_since=since, next_check_at=due,
                    upcoming=stores[nxt])
    return _at(nxt, resting=True, rest_since=since)
