# Zepto — Status Update

**Date:** 04-Aug-2026
**Author:** Zepto public-data work
**Read alongside:** [zepto.md](zepto.md) (the plan) and
[zepto_phase0_handover.md](zepto_phase0_handover.md) (how each Phase 0 task was solved)

---

## TL;DR

1. **Phase 0 recon is ~90% done — not closed.** Q1–Q11 answered from live
   traffic, so the "no engine code until Q1–Q8" gate is cleared. Three items
   remain: **Q12** (datacenter IP, needs VM access), the **search response** is
   still missing from `api.txt`, and the **throwaway probe scripts** have not
   been deleted.
2. **The store catalog was built, not sourced** — 1,229 dark stores across 58
   cities. This was Phase 3's blocker (Q9) and it is now resolved.
3. **A keyword scraper is running** for the client Brik Oven — 169 Bengaluru
   stores × 9 keywords, currently 96% complete.
4. **Zepto is ~23× slower per store than Blinkit**, and this is a platform
   limit, not a code problem. Details below — this is the part that needs a
   decision.
5. **Nothing is in the database yet.** All of the above writes Excel. The engine
   (Phase 2) has not been built.

---

## Phase 0 — every task, and how it was done

The checklist is from [zepto.md](zepto.md). Full detail on each in
[zepto_phase0_handover.md](zepto_phase0_handover.md).

| # | Task | Status | How it was done |
|---|---|---|---|
| 1 | Capture a live Zepto search — URL, method, headers, body, response | **partial** | Headers are session-generated and go stale, so they could not be copied by hand. Captured programmatically: a real browser loads zepto.com, a request listener steals the headers its own page generated (31 for `get_page`, 33 for `search`). Request side complete; **response still missing** |
| 2 | Commit as `zepto/public_data/api.txt` | **done** | 42 KB, all four endpoints documented |
| 3 | Answer Q1–Q12 | **Q1–Q11 done** | See the table below. Q12 needs the VM |
| 4 | Confirm store binding actually changes the catalog (Q2) | **done** | Four stores, same keyword, compared *results* not status codes. lat/lng in the body → all four returned the **identical** catalog (silently ignored). Overriding `store_id`/`storeid`/`store_ids`/`store_etas` headers → **4 of 4 correct**. Binding is by header, never by coordinate |
| 5 | Probe ~20 scattered coordinates, record distinct store ids (Q11) | **superseded** | Went far beyond 20 — a full grid scan found 1,229 stores across 58 cities |
| 6 | Decide browser-based or httpx-based engine (Q3) | **done** | Raw `httpx` gets 429 even with valid cookies. But headers captured from a real session can be **replayed** via Playwright's request context at ~0.33 s/call vs ~3 s for a page reload. Browser needed to *establish* the session, not per request |
| 7 | Delete the throwaway probe script | **outstanding** | Still on disk |

### The twelve questions

| Q | Answer | Why it mattered |
|---|---|---|
| Q1 | `POST bff-gateway.zepto.com/user-search-service/api/v3/search` | defines `endpoints.py` |
| **Q2** | **Headers, not coordinates** — swappable per request on one session | the cost model: header swap is cheap, a session per store would have been 10–50× |
| Q3 | browser session required; headers then replayable | no pure-httpx engine |
| Q4 | per-product store id present → **store-grain** | Reach/Distribution denominators are meaningful (D8) |
| Q5 | explicit `brand` field | own-vs-competitor is exact, no name-guessing |
| Q6 | `pageNumber`; no basic→similarity switch | no `follow_similarity` equivalent needed |
| Q7 | typed numerics, **prices in paise** (`mrp: 11000` = ₹110.00) | parser divides by 100 |
| Q8 | pack strings parse with existing `pack.py` | no `_UOM`/`_TERM` changes (D7 respected) |
| **Q9** | **built, not sourced** — 1,229 stores, 58 cities | was Phase 3's blocker; flagged in the plan as possibly needing a non-engineering answer |
| Q10 | a **volume** cap per IP, not just a rate | the whole performance problem — see below |
| Q11 | 1,229 stores, 58 cities | feeds the D10 disk gate |
| **Q12** | **OPEN** — needs the VM | decides whether the volume cap is a production constraint or a home-broadband artefact |

### How the catalog was built (Q9)

No Zepto equivalent of Blinkit's 2,059-store export existed, so it was
constructed: a pincode sweep (`autocomplete` → `details` → `get_page`) plus a
**0.006° (~666 m) grid scan** over each city's bounding box.

The grid resolution was measured, not guessed — at 1 km a Bellandur store was
missed; at 666 m, *"known stores not hit by grid = 0"* in all 58 cities.

Three problems found and fixed: outlier stores stretching the bounding box
(Jaipur went from 158,608 grid points to 4,891 after excluding stores >45 km
from the city median), phantom stores (`serviceable: false` with no details —
counted as real until flagged), and misfiled stores (nine re-attributed via
name-prefix analysis, each predicted then confirmed).

Deduplication runs at three layers — within a scan, across cities against all
known ids, and again at merge — so a store found in one city is never
re-counted when a neighbour is scanned.

**Result: 1,229 unique stores, up from 1,129 previously held (+8.9%).** Delhi
NCR 214→266, Mumbai 115→140, Mohali 5→14. Verified by round-tripping
coordinates back through `get_page`: Kolkata matched 51 of 53 (96.2%).

---

## Where the current run stands

Client: **Brik Oven**, city: **Bengaluru**, competitors tracked: The Health
Factory, Suchali, Theobroma, The Baker's Dozen, Baker's Loaf.

| | |
|---|---|
| stores | 169 |
| keywords | 9 |
| total searches | 1,521 |
| banked | **1,456 (95.7%)** |
| product rows | ~14,000 |
| elapsed | **~11 hours across two days** |

Captured per product: rank, brand, product name, pack size, MRP, selling price,
discount % and value, in-stock, available quantity, rating, rating count,
category, product/variant ids, timestamp.

Output: `zepto_keyword_scan_bengaluru_<ts>.xlsx` — sheets are All Products,
Brik Oven Only, Tracked Brands, Head to Head, By Keyword, Brand Ranking, Summary.

**One finding to flag:** `Suchali` does not appear on any Zepto SERP across
~14,000 product rows and 169 stores. Either they do not list on Zepto or not in
Bengaluru. Reported explicitly in the workbook rather than silently omitted.

---

## The performance problem

### The like-for-like comparison

Same 9 keywords, same worker model, same VM, **both from a single IP**:

| | Blinkit | Zepto |
|---|---|---|
| stores × keywords | 2,059 × 9 = 18,531 searches | 1,229 × 9 = 11,061 searches |
| workers | **5, on one IP** | 1 |
| sustained rate | **~68 searches/min** | ~5/min, then blocked |
| volume ceiling | **none observed** | ~137 searches, drifting down to ~67 |
| runtime | **4–5 h** | ~62 h projected |

Normalised for store count, **Zepto is ~23× slower.** It decomposes as:

| factor | multiplier |
|---|---|
| concurrency (5 workers vs 1) | 5× |
| per-worker pacing (4.4 s vs 12 s) | 2.7× |
| rest overhead (40% of Zepto runtime) | 1.7× |

### Why concurrency is not available

Blinkit runs **5 concurrent workers off one IP** and sustains it for 18,531
searches. That is only possible if Blinkit has no per-IP volume cap — if it did,
5 workers sharing an IP would share one budget, hit the wall 5× sooner, and
finish no earlier.

Zepto does have that cap. We proved it tracks the **IP** and not the session:

| change | result |
|---|---|
| rotate session headers | 22.0% loss |
| entirely new browser context (fresh device_id + cookies) | 22.5% loss |
| slow down on a cold IP | 0% loss |

Zepto ignored *who* we claimed to be and only cared *where we came from*.

### Measured block thresholds (residential IP)

| pacing | rate | blocked after | ≈ requests |
|---|---|---|---|
| 0.4 s | 150/min | **1 search** | ~2 |
| 5 s | 12/min | 21 | ~46 |
| 6 s | 10/min | 47 | ~103 |
| 12 s | 5/min | **137** | ~300 |

Note these are not equal in request terms — a pure volume cap would cut off at
the same count regardless of speed. The budget partly refills as you go, and
speed outruns the refill. Both a rate and a volume component are present.

**There is also a longer window.** Across today the ceiling drifted
**137 → 86 → 117 → 67**. A 15-minute rest clears the short window; a longer one
drains across the day. Mornings run materially better than evenings.

### What this means for scheduling

One city (Bengaluru, 1,521 searches):

```
scraping   1,521 × 12 s          = 5.1 h
rests      1,521 ÷ 110 × 15 min  = 3.5 h
                                   ~8.6 h   before any hard block
```

All India (1,229 stores × 9 keywords = 11,061 searches):

```
scraping 37 h + rests 25 h = ~62 h
```

**The `batch` job timeout is 12 h**, and Blinkit and Zepto share that lane, so
the weekly window is the *sum*. All-India weekly Zepto does not fit — by roughly
a factor of five.

---

## What has already been tried and ruled out

| approach | result |
|---|---|
| more workers | same IP, same cap — reaches the wall proportionally sooner |
| faster pacing (6 s) | **blocked after 47**; 20% slower end-to-end than 12 s, because a hard block costs more than a scheduled rest |
| session-header rotation | 22.0% loss |
| fresh browser identity | 22.5% loss |
| retry + session refresh (the Blinkit remedy) | cures a transient blip; does nothing against a ceiling |
| scrape fewer stores | **not viable** — see below |
| smaller `RESULT_CAP` | halves requests but drops placements observed at #27–#36 |
| `MAX_PAGES 3 → 2` | truncates ranks 27–30 |

### Sampling stores is not available as a lever

The obvious saving is "scrape fewer stores". Measured across 92 Bengaluru stores:

| keyword | stores | distinct product sets | median pairwise overlap |
|---|---|---|---|
| sourdough | 92 | **92** | 46% |
| sourdough bread | 92 | **92** | 50% |
| ricotta | 92 | **92** | 43% |
| mozzarella | 92 | 88 | 62% |
| rosemary sourdough | 70 | 29 | 10% |

**No two stores carry the same assortment**, and two random stores share under
half their products. A sampled subset does not approximate the whole — a brand's
rank at an unscraped store is genuinely unknowable.

**Coverage cannot be traded for speed. Cadence can** — every store, every
keyword, full ranking, run fortnightly rather than weekly, at zero cost to data
quality. This is the D10-preferred lever.

---

## Plan to speed it up — six experiments

Ranked by what they could buy. Each needs a reasonably cold window, so they
cannot run back to back.

### 1. Concurrent workers — the largest possible win

5 workers, own browser context each, 12 s per worker (25/min aggregate). Count
searches before the block.

| result | meaning |
|---|---|
| <10 | aggregate rate limit — concurrency confirmed dead |
| 30–50 | burst-tolerant; net win from amortising the fixed recovery cost |
| near 137 | cap is per-session → **5× speedup**, 62 h becomes ~12 h |

Follow-up if it dies instantly: 5 workers at 60 s each (same 5/min aggregate as
one worker at 12 s). If that beats 137, something beyond raw rate is in play.

**Cost:** ~30 min. **Confidence it helps:** low (~20%), but it is the largest
term in the 23× gap and currently only an inference.

### 2. The VM — Q12 ▢ BLOCKED ON ACCESS

Run the same measurement from the GCP Mumbai box. Free, ~10 minutes, and it is
the D9 gate regardless.

Two parts: **burst** (1 s pacing — home IP died after 1 search at 0.4 s) and
**sustained** (12 s — home IP: 137).

| VM result | conclusion |
|---|---|
| same as home | cap is Zepto-wide. Proxies or fortnightly are the only levers |
| worse than home | datacenter ASNs policed harder — important before scheduling |
| much better / no block | the whole problem is a home-broadband artefact |

**Confidence:** low-moderate. Blinkit's Q12 answer was "no difference", but
datacenter IPs are often policed *harder*, not less.

### 3. Intra-search page spacing

Pages currently fire **back-to-back with zero gap**, then wait 12 s — a burst of
2–3 requests, then silence. Test 4 s between pages instead. Identical
requests/minute, evenly distributed.

If burst detection is part of the limiter — and 0.4 s dying after a *single
search* suggests it is — this could permit a lower overall gap.
**Confidence: moderate.** The most interesting untested idea.

### 4. Measure the long window

The ceiling drifted 137 → 86 → 117 → 67 today. Nobody knows the longer budget's
period or size. Deplete fully, then probe every 30 min overnight and record when
capacity returns.

Will not speed up a single run, but decides whether "two 4-hour runs at 06:00
and 18:00" beats one 9-hour slog. **Confidence: high that it is informative.**

### 5. `MAX_PAGES = 3 → 2`

Guaranteed ~25% fewer requests. `SEARCH_GAP_S` spaces *searches*, but the
limiter counts *requests*, and one search is up to 3:

```
page 0: 14 rows
page 1: 12 rows   -> 26 total, still under RESULT_CAP
page 2:  0 rows   <- wasted request
```

Needs validating first: does page 2 ever return products when page 0+1 < 30?
Only safe for a **fresh** run — mixing 2-page and 3-page stores makes product
counts incomparable between stores.

### 6. `get_page` as a second budget

`get_page` has a **separate, largely unused budget**, and its `PAGE_IN_PAGE`
layouts return product data (152 products observed in one layout). It cannot
give keyword rank, so it cannot replace search — but category listings or
pricing might come from there, moving part of the workload onto capacity that is
currently wasted. **Confidence: low for this use case**, but it is free.

### Honest expectation

None of these is likely to break the ceiling, because it is a deliberate
platform limit rather than an oversight. What they do is convert "we think it
cannot go faster" into "we measured it, here are six things we tried" — which is
what a proxy or cadence decision needs behind it.

---

## What we need from you

| # | Need | Why |
|---|---|---|
| 1 | **VM access** (GCP Mumbai, repo + Playwright) | Q12, and the D9 gate blocks Phase 2 regardless |
| 2 | **A decision on proxies** | 5 IPs → ~12 h, 10 IPs → ~6 h. It is circumventing a control Zepto put there deliberately, so it is a company call, not an engineering one |
| 3 | **The `keyword_cap` behind the Blinkit 4–5 h figure** | converts the comparison from approximate to exact |
| 4 | **Where Zepto's secondary store ids should live** | `marketplace_locations` has no column for them and Zepto's search binding uses them — see below |

### On the secondary store ids

Zepto binds a search to a store via headers, and `store_ids` is the primary id
**plus that store's secondaries**. `marketplace_locations` has no field for
this; Blinkit does not need one.

Before designing a column, there is a two-search test: same store, `store_ids` =
primary only vs primary + secondaries. If results are identical the column is
unnecessary and this goes away. If not, it is the first field either platform
needs that the shared schema cannot express — a real schema decision.

Also note `zepto.md` currently states "~1.5 h for 2059 stores at 5 workers"; the
like-for-like figure at 9 keywords is **4–5 h**, and the capacity planning in
that doc rests on the smaller number.

---

## What is NOT done

- **Nothing is in the database.** The scan writes `keyword_scan_checkpoint.csv`
  and Excel. No `search_snapshots`, no `search_listings`, no `sku_snapshots`.
  Consequence: no history, so no week-on-week comparison and nothing in the
  dashboard.
- **Phase 2 (the engine) has not started.** `zepto_keyword_scan.py` is a script
  in `backend/scripts/`, not product code. The proper build goes under
  `scraper/platforms/zepto/public_data/` — `endpoints.py`, `scraper.py`,
  `parser.py`, delete the four stubs, flip `wired=True`.
- **Phase 3** is unblocked but not started — the 1,229 stores need loading into
  `config.xlsx` with `mp=zepto`, then `cli sync`.
- **Nothing is committed.** All Zepto work is untracked on
  `feature/zepto-public-scrape`.
- **Phase 0 is not formally closed.** Outstanding: Q12 (needs the VM),
  the search **response** missing from `api.txt` (it was rate limited at capture
  time — capturable now), and the throwaway probe scripts still on disk, which
  the plan says should not survive Phase 0.

---

## Suggested order

1. Finish the Bengaluru scan and export the client workbook *(in progress)*
2. Commit everything to `feature/zepto-public-scrape`
3. **VM access → run Q12** — it gates both the speed question and Phase 2
4. Concurrency and page-spacing experiments on a fresh morning budget
5. Take proxies vs fortnightly cadence to a decision with the evidence above
6. Phase 2: build the engine
7. Phase 3: `config.xlsx` + `cli sync`
