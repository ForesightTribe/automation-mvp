# Blinkit public scraper — why only 2 of 5 workers ran, and what fixed it

**Date:** 16 Sep 2026
**File changed:** `backend/scraper/public/orchestrator.py` (only this one)
**Commits:** `680bd98`, `c9322f8`, `8cdae85` — on `main` since `81ea212`
**Status:** deployed to the VM, verified on the 16 Sep 11:00 scheduled run

---

## The problem

A worker's first act is `open_session`: launch a browser, load blinkit.com at the
store's lat/lon, wait for the page to fire its own `/v1/layout/search`, and copy the
headers off that request. If that never happens, `open_session` returns nothing — and
the old code did this:

```python
session = await provider.open_session(browser, seed[0], seed[1])
if not session:
    logger.warning(f"worker {wid}: could not open session — exiting")
    return
```

One failure and the worker **exited and was never replaced**. All five started in the
same second, Cloudflare challenged four of them, and the 14 Sep run spent ten hours on
two workers.

---

## Change 1 — stagger the start-ups (`680bd98`)

```python
_WORKER_STAGGER_S = 5
...
if _WORKER_STAGGER_S and wid > 1:
    await asyncio.sleep(_WORKER_STAGGER_S * (wid - 1))
```

Worker N waits `5 × (N−1)` seconds before its first page load — so 0, 5, 10, 15, 20 s.
Setting it to `0` restores the old all-at-once behaviour.

**Result on the VM: 2 live workers → 4.**

---

## Change 2 — give a failed open more attempts (`c9322f8`, then `8cdae85`)

The first version was a single retry after 10 s. That got 4/5 but not always the fifth.
Looking at *why* the opens failed, the errors were `HTTP 429 · non-JSON body` — a
Cloudflare challenge page, not a slow load. The challenge window is short, so the fix is
more attempts with growing waits:

```python
_OPEN_SESSION_RETRY_S = (10, 30)      # waits before attempt 2, attempt 3
...
session = None
for attempt, wait in enumerate((*_OPEN_SESSION_RETRY_S, None), start=1):
    session = await provider.open_session(browser, seed[0], seed[1])
    if session or wait is None:
        break
    logger.warning(f"worker {wid}: could not open session (attempt {attempt}) — "
                   f"retrying in {wait}s")
    await asyncio.sleep(wait)
if not session:
    logger.warning(f"worker {wid}: could not open session — exiting")
    return
```

Three attempts: immediately, +10 s, +40 s. A single-entry tuple restores the old
give-up-at-once.

**Result on the VM: 5 live workers.**

---

## Evidence — the 16 Sep 11:00 run

```
11:01:16  worker 2: could not open session (attempt 1) — retrying in 10s
11:01:24  worker 4: attempt 1 failed — retrying in 10s
11:01:25  worker 3: attempt 1 failed — retrying in 10s
11:01:37  worker 5: attempt 1 failed — retrying in 10s
11:01:40  worker 2: attempt 2 failed — retrying in 30s
          ...
[1/2059] w1 · [2/2059] w3 · [3/2059] w4 · [4/2059] w1 · [5/2059] w5 · [6/2059] w2
```

All five finished a store. w3, w4 and w5 came in on attempt 2; **w2 needed all three.**
Under the old code only w1 would have survived.

---

## What it bought

|                | 14 Sep      | 16 Sep                  |
| -------------- | ----------- | ----------------------- |
| workers live   | 2 of 5      | **5 of 5**              |
| duration       | 9 h 57 m    | ~4 h 20 m               |
| errors         | —           | 4 in ~700 stores        |

The only cost is up to ~60 seconds of start-up.

---

## What these changes are *not*

They do **not** make Blinkit tolerate more sessions. Blinkit rate-limits *session
creation* per IP — measured at roughly **one new session per 20–30 s** — and the VM has
one IP. Searching itself is not limited: ~700 stores and ~6,000 searches in the same run
produced 4 errors.

The changes only stop a worker from dying because it happened to be second in the queue.

---

## Known consequence, and what's still open

The bid optimizer needs the same kind of Blinkit session every 15 minutes to measure
keyword positions, and it has **no retry**. With five workers minting sessions it now
gets caught in the same rate limit:

```
11:01:36  error  could not check the search position, so the bid was left unchanged
11:30:42  error  same
12:16:10  error  same
```

Those are position-check failures, not bid failures — the bid is left untouched
(842→842) and the next cycle 15 minutes later applies normally. Failures by cause per day
show it clearly: zero such errors in the previous 7 days, including 14 Sep when the
scrape ran 10 hours on 2 workers; 3 on 16 Sep with 5 workers.

Two follow-ups, neither done yet:

1. **Retry in `campaign_manager/marketplaces/blinkit/live_position.py`** — the same
   10 s / 30 s ladder. Fixes the optimizer at any hour, regardless of what else runs.
   This is the one that matters.
2. **Widen `_WORKER_STAGGER_S` 5 → 20 s.** Today's log shows an open 20 s after the
   first one still got refused, so 5 s is below Blinkit's tolerance and we are paying for
   retries we could avoid. Costs ~80 s on a 4-hour run.
