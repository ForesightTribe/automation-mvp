"""
Zepto rate-limit experiments — measurement only, never a scrape.

Deliberately SEPARATE from zepto_keyword_scan.py. That script completed a
1,521-search run and is not to be edited on a hunch; this one imports its proven
pieces (load_stores / open_session / extract) and implements only its own
measurement loop. Nothing here writes to keyword_scan_checkpoint.csv, so no
experiment can corrupt collected data.

Every mode reports the same three numbers so results are comparable across runs
and against the 04-Aug baseline:

    searches before the first block   |   elapsed   |   effective rate

Reference points, all single-IP, 12 s pacing, 1 worker:
    01-Aug (rested IP)    576+ searches, no block observed
    04-Aug (4th day)      blocks at 65-88

Run from backend/:
    python -m scripts.zepto_rate_experiments --pacing 12     # BASELINE — run first
    python -m scripts.zepto_rate_experiments --pacing 12 --pagegap 4
    python -m scripts.zepto_rate_experiments --workers 5 --pacing 12
    python -m scripts.zepto_rate_experiments --ceiling       # one probe, is it open?

Order matters. --pacing 12 is the control: without it, a good --workers result
cannot be told apart from simply having a rested IP.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright

from scripts.zepto_keyword_scan import (
    load_stores, open_session, extract, KEYWORDS,
    _BFF, _SEARCH, RESULT_CAP, MAX_PAGES,
)

# A block costs the shared IP budget, so every mode stops at the FIRST one
# rather than confirming it repeatedly.
BLOCK_STATUSES = {299, 401, 403, 429}
MAX_SEARCHES = 600          # safety ceiling; 01-Aug reached 576 without blocking


async def one_search(state, store, kw, page_gap):
    """(n_products, blocked). page_gap spaces the page requests INSIDE a search.

    The scraper spaces searches but fires a search's 2-3 page requests back to
    back, so the real traffic shape is a burst then silence. page_gap>0 spreads
    them evenly at the same requests/minute — the point of the --pagegap test.
    """
    sid = store["store_id"]
    ids = ",".join([sid] + (store.get("secondary") or []))
    got = 0
    for page_no in range(MAX_PAGES):
        if got >= RESULT_CAP:
            break
        if page_no and page_gap:
            await asyncio.sleep(page_gap)
        h = dict(state["se"])
        h["store_id"] = h["storeid"] = sid
        h["store_ids"] = ids
        h["store_etas"] = json.dumps({s: -1 for s in ids.split(",")})
        body = dict(state["body"])
        body.update(query=kw, pageNumber=page_no, mode="SHOW_ALL_RESULTS")
        try:
            r = await state["ctx"].request.post(f"{_BFF}{_SEARCH}", headers=h,
                                                data=json.dumps(body), timeout=20000)
        except Exception as e:
            print(f"    transport error: {str(e)[:60]}")
            return got, True
        if r.status in BLOCK_STATUSES:
            return got, True
        if r.status != 200:
            print(f"    HTTP {r.status}")
            return got, True
        rows = extract(await r.json(), "exp")
        if not rows:
            break
        got += len(rows)
    return got, False


async def worker(wid, browser, jobs, pacing, page_gap, shared):
    """One browser context walking `jobs` until it blocks or the pool stops."""
    state = {"searches": 0, "block_points": [], "at": "exp"}
    await open_session(browser, state)
    if not state.get("se"):
        print(f"  worker {wid}: could not capture session headers")
        return
    for store, kw in jobs:
        if shared["blocked"]:
            return
        n, blocked = await one_search(state, store, kw, page_gap)
        shared["n"] += 1
        i = shared["n"]
        if blocked:
            shared["blocked"] = True
            shared["at"] = i
            el = time.time() - shared["t0"]
            print(f"  [{i:>4}] w{wid} {store['store_name'][:24]:<25} {kw:<20} "
                  f"BLOCKED after {el/60:.1f} min")
            return
        if i % 10 == 0 or i < 5:
            el = time.time() - shared["t0"]
            print(f"  [{i:>4}] w{wid} {store['store_name'][:24]:<25} {kw:<20} "
                  f"{n:>2} products   {i/(el/60):.1f}/min")
        await asyncio.sleep(pacing)
    try:
        await state["ctx"].close()
    except Exception:
        pass


def build_jobs(stores, n):
    """(store, keyword) pairs, cycling keywords so no single term dominates."""
    out = []
    while len(out) < n:
        for s in stores:
            for kw in KEYWORDS:
                out.append((s, kw))
                if len(out) >= n:
                    return out
    return out


async def run(pacing, workers, page_gap, limit):
    stores, _ = load_stores()
    jobs = build_jobs(stores, limit)
    per = [jobs[i::workers] for i in range(workers)]     # deal round-robin
    shared = {"n": 0, "blocked": False, "at": None, "t0": time.time()}

    agg = workers * (60.0 / pacing) if pacing else float("inf")
    print(f"pacing {pacing}s | workers {workers} | page gap {page_gap}s"
          f" | aggregate ~{agg:.1f} searches/min")
    print(f"stopping at the first block, or {limit} searches")
    print("-" * 78)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        await asyncio.gather(*[
            worker(w + 1, browser, per[w], pacing, page_gap, shared)
            for w in range(workers)])
        await browser.close()

    el = time.time() - shared["t0"]
    print("-" * 78)
    print(f"searches completed : {shared['n']}")
    print(f"blocked at         : {shared['at'] or 'NO BLOCK'}")
    print(f"elapsed            : {el/60:.1f} min")
    print(f"effective rate     : {shared['n']/(el/60):.1f} searches/min")
    print()
    print("compare: 01-Aug rested IP 576+ no block | 04-Aug depleted 65-88")


async def ceiling():
    """One search. Is the window open right now, and how healthy?"""
    stores, _ = load_stores()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        state = {"searches": 0, "block_points": [], "at": "exp"}
        await open_session(browser, state)
        if not state.get("se"):
            print("could not capture session headers")
            await browser.close()
            return
        n, blocked = await one_search(state, stores[0], "sourdough", 0)
        ts = time.strftime("%H:%M:%S")
        if blocked:
            print(f"{ts}  BLOCKED — window still shut")
        else:
            print(f"{ts}  OPEN — {n} products"
                  + ("   (healthy)" if n >= 25 else "   (degraded, <25)"))
        await browser.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pacing", type=float, default=12.0,
                    help="seconds between searches, per worker (default 12)")
    ap.add_argument("--workers", type=int, default=1,
                    help="concurrent browser contexts (default 1)")
    ap.add_argument("--pagegap", type=float, default=0.0,
                    help="seconds between page requests inside one search")
    ap.add_argument("--limit", type=int, default=MAX_SEARCHES,
                    help=f"stop after this many searches (default {MAX_SEARCHES})")
    ap.add_argument("--ceiling", action="store_true",
                    help="fire ONE search and report whether the window is open")
    a = ap.parse_args()
    if a.ceiling:
        asyncio.run(ceiling())
    else:
        asyncio.run(run(a.pacing, max(1, a.workers), a.pagegap, a.limit))


if __name__ == "__main__":
    main()
