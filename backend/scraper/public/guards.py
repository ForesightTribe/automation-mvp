"""Wall-clock guards for a public scrape run.

A job timeout answers "has this run gone on too long?", which cannot tell a slow
run from a dead one: a national sweep legitimately takes five hours, so its
ceiling has to be set high enough that a wedged run sits there for most of a day
before anything notices. Measured 2026-09-17: a `public-skus` run stalled on its
last store and retried for 75 minutes with zero rows written, while its 12-hour
`batch` ceiling still had ten hours to run.

These guards watch PROGRESS instead, which is the signal that actually
distinguishes the two.
"""
import asyncio
import time

from app.utils.logger import logger

# No new rows for this long -> the run is wedged, not slow. Ten minutes is well
# clear of a legitimate pause: the slowest store observed on a throttled national
# sweep took ~40s, and the backoff ladder tops out at ~65s per call.
STALL_AFTER_S = 10 * 60

# Hard ceiling on the backlog pass. Every pair in it has already failed twice, so
# this is a courtesy retry, not a phase worth waiting on — it must never outlast
# the main pass that produced it.
RETRY_DEADLINE_S = 20 * 60

_SAMPLE_S = 30


async def watch_for_stall(stats: dict, stop: asyncio.Event, *,
                          stall_after_s: int = STALL_AFTER_S,
                          label: str = "") -> None:
    """Set `stop` once `stats["rows"]` has not moved for `stall_after_s`.

    Runs as a background task for the life of a scrape. Workers check `stop` at the
    top of each store and exit cleanly, so the run finalises its staging file with
    whatever it has rather than being killed from outside and leaving the file
    half-open (`status='running'`, no `completed_at`, rows stranded).
    """
    tag = f"{label}: " if label else ""
    last_rows = -1
    last_change = time.monotonic()
    while not stop.is_set():
        await asyncio.sleep(_SAMPLE_S)
        rows = stats.get("rows", 0)
        if rows != last_rows:
            last_rows = rows
            last_change = time.monotonic()
            continue
        idle = time.monotonic() - last_change
        if idle >= stall_after_s:
            logger.error(
                f"{tag}STALLED — no rows staged for {int(idle // 60)} min "
                f"({rows:,} rows so far). Stopping workers and finalising the run."
            )
            stop.set()
            return


async def run_with_deadline(coro, deadline_s: int, label: str) -> bool:
    """Await `coro` with a ceiling. Returns True if it finished, False if it timed out.

    A timeout here is not a run failure: the backlog pass is best-effort, so the
    caller carries on and finalises normally.
    """
    try:
        await asyncio.wait_for(coro, timeout=deadline_s)
        return True
    except asyncio.TimeoutError:
        logger.warning(
            f"{label}: hit its {deadline_s // 60} min deadline and was stopped. "
            f"Unrecovered pairs are left out of this run; --resume will retry them."
        )
        return False
