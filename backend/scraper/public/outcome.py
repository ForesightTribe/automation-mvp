"""How a public scrape ended — success, partial or failed — decided from what it
actually covered, not from whether the code reached its last line.

Both orchestrators used to stamp a run `success` as soon as their worker pool
returned. A pool returns when every worker has exited, and a worker exits when the
queue is empty OR when it cannot open / re-open its session. So a run whose workers
all died stamped itself `success` with most of its stores never attempted, auto-loaded
and exited 0:

    Zepto own-SKU   2026-09-26   169 stores, 0 done            -> success
    Blinkit keyword 2026-09-25   1,439 of 2,456 locations      -> success, loaded

The unit is a PAIR: (keyword, store) for the keyword scrape, (brand, store) for the
own-SKU scrape. A pair is finished when the marketplace gave a real answer for it —
including "nothing here", which is an answer. Everything else is a gap.

    success   every store was attempted and coverage is at or above the floor
    partial   stores were left unattempted, or coverage is under the floor
              -> kept on disk, NOT auto-loaded, continued with --resume
    failed    nothing at all was scraped (or the run raised)

Kept free of scraper / browser imports on purpose: `jobs/runner.py` reads
PARTIAL_EXIT_CODE from here, and the runner must not pull Playwright in to do it.
"""
from app.core.config import settings

SUCCESS = "success"
PARTIAL = "partial"
FAILED = "failed"
# The tenant had nothing to scrape on this marketplace (no keywords / no locations /
# nothing to resume). Not a failure: in an `--all` sweep it is the normal case for a
# tenant that is not on that marketplace.
SKIPPED = "skipped"

# Exit code of `cli scrape public-run|public-skus` when a run ended PARTIAL. The runner
# supervises subprocesses, so an exit code is the only thing that crosses back to it —
# a distinct one is what lets the jobs table say "partial" instead of an anonymous
# `exit_1`. (3 is taken: platform_auth.errors.AUTH_EXPIRED_EXIT_CODE.)
PARTIAL_EXIT_CODE = 4


def coverage_pct(done: int, expected: int) -> float:
    """Finished pairs as a percentage of the pairs the run set out to do."""
    return round(done / expected * 100, 1) if expected else 100.0


def decide(*, expected: int, done: int, done_this_run: int,
           unattempted_stores: int, min_coverage_pct: float | None = None) -> str:
    """The run's status.

    `expected` and `done` cover the WHOLE staging file, so a resumed run is judged on
    what the file now holds, not on the slice this process added. `done_this_run` is
    only used to tell "nothing worked" apart from "nothing was left to do".
    """
    floor = settings.PUBLIC_MIN_COVERAGE_PCT if min_coverage_pct is None else min_coverage_pct
    if expected and done_this_run == 0 and done < expected:
        return FAILED
    if unattempted_stores or coverage_pct(done, expected) < floor:
        return PARTIAL
    return SUCCESS


def describe(*, expected: int, done: int, unattempted_stores: int,
             stores_total: int, unrecovered: int, unit: str) -> str:
    """One line saying what the run covered and what is missing. Printed for every
    run; stored on the staging file (and later `scrape_jobs.error`) when the run is
    not a clean success."""
    bits = [f"{done:,}/{expected:,} {unit} pairs ({coverage_pct(done, expected)}%)"]
    if unattempted_stores:
        bits.append(f"{unattempted_stores:,} of {stores_total:,} stores never attempted "
                    f"(the workers stopped)")
    if unrecovered:
        bits.append(f"{unrecovered:,} pairs got no answer at stores that were reached")
    return "; ".join(bits)


def exit_code(statuses: list[str]) -> int:
    """The CLI's exit code for a set of run statuses: the worst one wins."""
    if FAILED in statuses:
        return 1
    if PARTIAL in statuses:
        return PARTIAL_EXIT_CODE
    return 0
