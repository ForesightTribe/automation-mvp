"""
Parallel Zepto keyword scan — N workers, one browser context each.

SEPARATE from zepto_keyword_scan.py, which stays single-threaded and untouched.
This imports its proven pieces (load_stores / open_session / search / row
building / checkpoint I/O) and replaces only the run loop. Nothing here changes
the data format, so the existing exporter builds the workbook:

    python -m scripts.zepto_keyword_scan_parallel --tag test1 --workers 5
    python -m scripts.zepto_keyword_scan --tag test1 --export

Measured 05-Aug on a rested residential IP:
    1 worker  @12 s  ->  5.0 searches/min
    5 workers @12 s  -> 21.7 searches/min, blocked at 156

So concurrency buys rate but appears to cost total volume before the block.
Whether that is a net win depends on the recovery cost, which is why every run
prints its own block points and effective rate at the end — read those rather
than trusting the numbers above.

WHY THE CHECKPOINT IS STILL SAFE
Workers run on one asyncio event loop, so only one coroutine executes at a time.
The append is additionally guarded by a lock and happens in a single call with
no await inside it, so a store's rows can never interleave with another's.

Stores are dealt round-robin, so each worker gets a spread across the city
rather than one contiguous block of pincodes.
"""
import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright

from scripts import zepto_keyword_scan as base
from scripts.zepto_keyword_scan import (
    KEYWORDS, CLIENT_BRAND, CITY, NO_RESULTS, BACKEND,
    SEARCH_GAP_S, STORE_GAP_S, PAUSE_S, MAX_STORE_ATTEMPTS, RECOVERY_WAITS_S,
    PROBE_EVERY_S,
    load_stores, open_session, search, probe_open,
)

_LOCK = asyncio.Lock()


async def bank(rows):
    """Serialised append. base.append_ckpt reads the module-level CKPT, which
    main() has already pointed at the tagged file."""
    async with _LOCK:
        base.append_ckpt(rows)


async def do_store(wid, state, st, kws, at, shared):
    """Scrape one store's outstanding keywords. Returns the ones NOT collected."""
    sid = st["store_id"]
    all_ids = ",".join([sid] + (st.get("secondary") or []))
    rows, done_kws = [], []

    for kw in kws:
        res, blocked = await search(state, sid, all_ids, kw)
        shared["n"] += 1
        if blocked:
            shared["blocks"].append(shared["n"])
            print(f"  w{wid} {st['store_name'][:26]:<27} {kw:<20} BLOCKED "
                  f"({shared['n']} searches in)")
            break
        if not res:
            # Sentinel so a legitimately empty search counts as done and is not
            # retried forever. The exporter filters these out.
            rows.append({"store_id": sid, "store_name": st["store_name"],
                         "pincode": st["pincode"], "area": st["area"],
                         "lat": st["lat"], "lng": st["lng"], "keyword": kw,
                         "brand": NO_RESULTS, "is_client": "", "position": "",
                         "product_name": "", "scraped_at": at})
        else:
            # search() returns product fields only — it has no idea which store
            # or keyword produced them. Stamp the context on before banking, or
            # every row lands with a blank store_id and the checkpoint is junk.
            rows.extend({**r, "keyword": kw,
                         "store_id": sid, "store_name": st["store_name"],
                         "pincode": st["pincode"], "area": st["area"],
                         "lat": st["lat"], "lng": st["lng"]} for r in res)
        done_kws.append(kw)
        cl = [r for r in res if r.get("is_client") == "YES"]
        best = min((r["position"] for r in cl), default=None)
        tag = (f"{CLIENT_BRAND} #{best} ({len(cl)} SKU)" if cl
               else f"no {CLIENT_BRAND}")
        print(f"  w{wid} {st['store_name'][:26]:<27} {kw:<20} "
              f"{len(res):>2} products | {tag}")
        await asyncio.sleep(SEARCH_GAP_S)

    if rows:
        await bank(rows)
    return [k for k in kws if k not in done_kws]


async def worker(wid, browser, jobs, at, shared, attempts):
    state = {"gp": {}, "se": {}, "body": {}, "ctx": None, "page": None,
             "at": at, "searches": 0, "block_points": [],
             # probe_open() binds its test search to a real store; without this
             # the probe runs unbound and its answer means nothing.
             "probe_store": jobs[0][0]["store_id"] if jobs else ""}
    await open_session(browser, state)
    if not state.get("se"):
        print(f"  w{wid}: no session headers — worker exiting")
        return

    queue, pending = list(jobs), []
    while queue or pending:
        if not queue:
            queue, pending = pending, []
        st, kws = queue.pop(0)

        # Skip anything another worker's retry already covered.
        _, done = base.load_ckpt()
        kws = [k for k in kws if (st["store_id"], k) not in done]
        if not kws:
            continue

        # Header per store. With workers interleaved the per-keyword lines alone
        # give no sense of progress, so carry the running store count here.
        shared["started"] += 1
        print(f"[{shared['started']:>3}/{shared['total_stores']}] w{wid} "
              f"{st['store_name'][:28]:<29} {st['pincode']:<7} "
              f"{st['store_id'][:8]}  ({len(kws)} kw)")

        left = await do_store(wid, state, st, kws, at, shared)
        if left:
            n = attempts.get(st["store_id"], 0) + 1
            attempts[st["store_id"]] = n
            if n < MAX_STORE_ATTEMPTS:
                pending.append((st, left))
            else:
                print(f"  w{wid} {st['store_name'][:26]} gave up after {n} tries")
            # Blocked: wait it out, but PROBE rather than sleep blind — a window
            # that reopens after 4 min should cost 4 min, not 15. The sequential
            # scanner has always worked this way; an unconditional sleep here was
            # strictly worse than the script this is meant to improve on.
            wait = RECOVERY_WAITS_S[min(n - 1, len(RECOVERY_WAITS_S) - 1)]
            print(f"  w{wid} blocked — probing every {PROBE_EVERY_S//60} min, "
                  f"up to {wait//60} min")
            # Stagger by worker id so five probes do not land together and look
            # like a fresh burst to the very limiter we are waiting out.
            await asyncio.sleep(wid * 20)
            waited = 0
            while waited < wait:
                await asyncio.sleep(PROBE_EVERY_S)
                waited += PROBE_EVERY_S
                await open_session(browser, state)
                if await probe_open(state):
                    print(f"  w{wid} window reopened after {waited//60} min")
                    break
                print(f"  w{wid} still shut at {waited//60} min")
        await asyncio.sleep(STORE_GAP_S)
    try:
        await state["ctx"].close()
    except Exception:
        pass


async def run(n_workers):
    stores, src = load_stores()
    _, done = base.load_ckpt()
    at = datetime.now().strftime("%d-%b-%Y %H:%M")
    todo = [(s, [k for k in KEYWORDS if (s["store_id"], k) not in done])
            for s in stores]
    todo = [(s, k) for s, k in todo if k]
    total = len(stores) * len(KEYWORDS)

    print(f"Store source : {src}")
    print(f"Client       : {CLIENT_BRAND}   city: {CITY}")
    print(f"Workers      : {n_workers}   pacing {SEARCH_GAP_S}s each "
          f"(~{n_workers*60/SEARCH_GAP_S:.0f}/min aggregate)")
    print(f"Already done : {len(done)}/{total} searches")
    print(f"This run     : {len(todo)} stores remaining")
    print(f"Checkpoint   : {base.CKPT.name}")
    print("=" * 96)
    if not todo:
        print("Nothing to do.")
        return

    per = [todo[i::n_workers] for i in range(n_workers)]
    shared = {"n": 0, "blocks": [], "started": 0, "total_stores": len(todo)}
    attempts, t0 = {}, time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        await asyncio.gather(*[
            worker(w + 1, browser, per[w], at, shared, attempts)
            for w in range(n_workers)])
        await browser.close()

    el = (time.time() - t0) / 60
    _, done2 = base.load_ckpt()
    print("=" * 96)
    print(f"Searches this run : {shared['n']}   in {el:.1f} min "
          f"({shared['n']/el if el else 0:.1f}/min)")
    print(f"Total complete    : {len(done2)}/{total}")
    if shared["blocks"]:
        print(f"Block points      : {shared['blocks']}")
        print(f"  earliest {min(shared['blocks'])} searches into the run")
    else:
        print("No blocks.")
    print()
    print(f"Build the workbook:")
    print(f"   python -m scripts.zepto_keyword_scan"
          + (f" --tag {base.TAG}" if base.TAG else "") + " --export")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--tag", default="",
                    help="separate checkpoint + workbook, e.g. --tag test1")
    a = ap.parse_args()
    if a.tag:
        base.TAG = a.tag.strip().replace(" ", "_")
        base.CKPT = BACKEND / f"keyword_scan_checkpoint_{base.TAG}.csv"
        print(f"[tag {base.TAG}]  checkpoint: {base.CKPT.name}")
    asyncio.run(run(max(1, a.workers)))


if __name__ == "__main__":
    main()
