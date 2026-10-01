"""Per-worker search pacing for the public scrapes.

Two modes, chosen by the marketplace (`providers.Provider`):

  fixed     `search_gap_s` slept AFTER every search. What every marketplace did until
            2026-10-01, and what Blinkit (0 s) and Instamart (1 s) still do.

  adaptive  the gap is measured START to START and moves: wider after every block, back
            towards the floor after a clean stretch. Zepto's allowance changes through
            the day (mornings measured 10-14 requests a minute against 27 in the
            afternoon), so a fixed pace that is clean at 15:00 overshoots at 11:00 and
            the run lives in block -> recover -> block. The 2026-09-29 Brik Oven run had
            48 such streaks, a median of 7 searches each.

Unconditional either way: a blocked or empty search is still a request against the
limiter, so it still waits its turn.

The state is a plain dict (house style: functions, not classes), one per worker — each
worker is its own session and, on a marketplace with a per-connection limit, still shares
the connection, which is why Zepto runs one worker.
"""
import asyncio
import time


def new(provider) -> dict:
    """A worker's pacer for `provider`."""
    adaptive = bool(provider.gap_max_s)
    base = provider.gap_floor_s if adaptive else (provider.search_gap_s or 0.0)
    return {
        "adaptive": adaptive, "base": base, "gap": base, "max": provider.gap_max_s,
        "backoff": provider.gap_backoff, "ease_after": provider.gap_ease_after,
        "ease": provider.gap_ease, "clean": 0, "last": None,
    }


async def before(p: dict, session: dict | None) -> None:
    """Call immediately before a search. Adaptive: hold until `gap` after the previous
    request LEFT, and hand the gap to the session so a second page keeps the same pace.

    The previous request is whichever is later of the last search this pacer started and
    the session's own `last_request_at` (set by an engine that records it, Zepto's): a
    search that paged sent its last request well after it started."""
    if not p["adaptive"]:
        return
    if session is not None:
        session["gap_s"] = p["gap"]
    marks = [t for t in (p["last"], (session or {}).get("last_request_at")) if t is not None]
    if marks:
        wait = max(marks) + p["gap"] - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
    p["last"] = time.monotonic()


async def after(p: dict) -> None:
    """Call immediately after a search, whatever it returned. Fixed mode's gap."""
    if not p["adaptive"] and p["base"]:
        await asyncio.sleep(p["base"])


def on_block(p: dict) -> None:
    """A block: widen the gap (up to the ceiling) and start the clean count over."""
    if p["adaptive"]:
        p["gap"] = min(p["max"], p["gap"] * p["backoff"])
        p["clean"] = 0


def on_clean(p: dict) -> None:
    """A search that came back without a block. Enough of them in a row narrow the gap
    one step, never below the floor."""
    if not p["adaptive"]:
        return
    p["clean"] += 1
    if p["clean"] >= p["ease_after"] and p["gap"] > p["base"]:
        p["gap"] = max(p["base"], p["gap"] / p["ease"])
        p["clean"] = 0
