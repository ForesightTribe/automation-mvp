# Zepto Phase 0 — Handover

**For:** whoever picks up the Zepto build next
**Covers:** Phase 0 (recon) as specified in [zepto.md](zepto.md), plus the dark
store catalog and the keyword-level scraper built alongside it
**Status:** Q1–Q11 answered, Q12 open. Date: 04-Aug-2026

Read [zepto.md](zepto.md) first for the decisions (D1–D11) and the phase plan.
This document is the *how* — what each Phase 0 task turned out to mean for Zepto
and what was actually done about it.

---

## TL;DR for someone starting cold

Five things to know before touching any of this:

1. **A Zepto search is bound to a store by HTTP headers, not by coordinates.**
   Send a lat/lng and it is silently ignored — you get a valid 200 with a
   generic catalog. This is the single most important fact in the document.
2. **Because binding is by store id, you cannot scrape a store you have not
   already discovered.** That is why the catalog had to exist first.
3. **The catalog did not exist and could not be bought. It was built** — 1,229
   stores across 58 cities, by grid-scanning coordinates.
4. **Zepto rate limits on a volume cap per IP, not just a rate.** Blinkit's
   remedy (retry + session refresh) does not port. Slowing down helps; changing
   browser identity does not.
5. **This makes Zepto slow, and the numbers do not fit the schedule.** One city
   is ~8.6 h; the full catalog projects to ~62 h against a 12 h job timeout.
   That is a coverage/cadence decision (D10), not a tuning problem — see
   [Task 5](#task-5--rate-limits-q10).
6. **Prices are in paise.** `mrp: 11000` is ₹110.00.

---

## Phase 0 checklist — status

From [zepto.md](zepto.md):

| Task | Status |
|---|---|
| Capture a live Zepto search: URL, method, headers, body, response | partial — response outstanding |
| Commit the response as `zepto/public_data/api.txt` | done (42 KB) |
| Answer Q1–Q12, replace the open-questions table | Q1–Q11 done, Q12 open |
| Confirm store binding actually changes the catalog (Q2) | **done — see Task 2** |
| Probe ~20 scattered coordinates, record distinct store ids (Q11) | superseded — 1,229 stores found |
| Decide from Q3 whether the engine is browser- or httpx-based | done — browser |
| Delete the throwaway probe script | outstanding |

**Gate:** "no Zepto engine code until Q1–Q8 are answered" — **cleared.**

Note there is a *second* gate on Phase 2 that is **not** cleared: D9 requires a
live Blinkit `public-run` to pass clean on the VM before any Zepto code merges.
That needs VM access, same as Q12.

---

## Task 1 — Capture the API

### What was asked
Capture a live search: request URL, method, headers, body, response. Commit it.

### What Zepto turned out to be

Four endpoints, all on `https://bff-gateway.zepto.com`:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/maps/place/autocomplete/?place_name=` | text → area suggestions + `place_id` |
| `GET /api/v1/maps/place/details/?place_id=` | place → lat/lng/city/state |
| `GET /lms/api/v2/get_page?latitude=&longitude=` | coordinate → `storeId` + store name |
| `POST /user-search-service/api/v3/search` | keyword + store headers → products |

The first two exist only to turn a pincode or area name into a coordinate. The
third is how a coordinate is resolved to a store — it is the **discovery**
endpoint. The fourth is the actual scrape.

### How it was captured

Not from devtools by hand. The session headers Zepto requires are numerous (31
for `get_page`, 33 for `search`) and include generated device/session values, so
they are captured programmatically from the page's own traffic:

```python
async def capture(page, part, nav, settle=8000):
    cap = {"h": None, "body": None}

    async def on_req(req):
        if part in req.url and cap["h"] is None:
            cap["h"] = dict(req.headers)
            cap["body"] = req.post_data

    page.on("request", on_req)
    await nav()
    w = 0
    while cap["h"] is None and w < settle:      # keep listening after nav returns
        await page.wait_for_timeout(250)
        w += 250
    page.remove_listener("request", on_req)
```

**Gotcha that cost time:** the request fires *after* `domcontentloaded`, so
`page.goto()` returns before the header-bearing request has gone out. Removing
the listener at that point captures nothing. The polling window above is the
fix — do not "simplify" it away.

### Output
`backend/scraper/platforms/zepto/public_data/api.txt`

**Outstanding:** the search *response* is annotated `NOT CAPTURED` — the capture
attempt hit HTTP 429 at the time. The request is fully documented. Capturing the
response is a small, still-open task.

---

## Task 2 — Confirm store binding actually changes the catalog (Q2)

This is the task worth reading twice.

### What was asked
> Confirm the store-binding mechanism actually changes the catalog — a request
> that accepts a coordinate and ignores it is the silent failure.

### Why it matters

A scraper asks "what does Zepto show **at this store**?" You send a coordinate,
get HTTP 200 and 30 real products. It looks correct.

But if the API ignores the coordinate and serves a default catalog, you scrape
1,229 stores and collect 1,229 copies of the same data, each labelled with a
different store name. Nothing errors. Nothing looks wrong. A 403 tells you
something broke; this tells you nothing.

### How it was tested

Four stores that should genuinely differ, same keyword, compare the **results**
— not the status codes.

| Approach | Result |
|---|---|
| lat/lng injected into the request body | all four returned the **identical** catalog |
| `store_id` / `storeid` / `store_ids` / `store_etas` headers overridden | **4 of 4 correct**, all different |

Zepto ignores coordinates on the search endpoint entirely. Binding is by header:

```python
h["store_id"] = h["storeid"] = sid
h["store_ids"] = all_ids                      # primary + secondary, comma-joined
h["store_etas"] = json.dumps({s: -1 for s in all_ids.split(",")})
```

`all_ids` is `store_id` plus that store's `secondary` ids. **Do not drop the
secondaries** — they are part of the binding, and any export that omits them
cannot drive a scrape.

### Contrast with Blinkit

Blinkit binds by coordinate, also in headers
([blinkit/public_data/scraper.py:260](../backend/scraper/platforms/blinkit/public_data/scraper.py#L260)):

```python
headers = {**headers, "lat": str(lat), "lon": str(lon)}
```

Same architecture — one shared session, headers swapped per store, ~0.4 s per
fetch. Different key. This was never a problem on Blinkit because Blinkit's API
cooperates; Zepto's does not.

**Downstream consequence:** Blinkit can be scraped from a list of coordinates.
Zepto cannot — you need the store **ids**. That is what turned Q9 from a
reporting nicety into a hard prerequisite.

### How to re-verify

Cheap and worth repeating any time session or header logic changes: two stores
that should differ, one keyword, compare output. Live example from 04-Aug:

```
BLR-Nagdevanahalli     #1 The Baker's Dozen  #2 Baker's Loaf  #3 Theobroma
                       (no Brik Oven present)
BLR-Shivaji nagar New  #1 Brik Oven (3 SKUs)
```

Different catalogs → binding works. **Identical results across stores that
should differ → binding has silently broken and every row being collected is
worthless.**

---

## Task 3 — Build the store catalog (Q9)

### What was asked

> Where does the Zepto store catalog come from? A store-list endpoint, a
> published dataset, or an export like Blinkit's?

The plan flagged this as *"the one open question that may need a
non-engineering answer"* and as **blocking for Phase 3**. Blinkit's catalog
(2,059 stores) came from an external export.

### What happened

No equivalent Zepto export was available. The catalog was **built**.

### The method — two phases per city

**Phase A — pincode sweep.** For each known pincode: `autocomplete` → `details`
→ `get_page`. Returns a store id, name, and whether it is serviceable. Cheap and
gives a full address, but only finds stores near a pincode centroid.

**Phase B — grid scan.** Lay a lattice over the city's bounding box and call
`get_page` at every point.

```python
STEP      = 0.006    # ~666 m
MIN_HALF  = 0.13
MARGIN    = 0.12
OUTLIER_KM = 45
```

**Grid resolution was measured, not guessed.** At 1 km spacing `BLR-Bellandur 6`
was missed. At 666 m, *"known stores not hit by grid = 0"* in all 58 cities.
Do not widen `STEP` without re-running that check.

### Three problems found and fixed

**1. Outliers stretched the bounding box.** Jaipur's box came to 158,608 grid
points — 109 minutes for one city — because two stores 199 km away
(`KTU-Dadabari` in Kota, `MTH-Govind Dham` in Mathura) were included in the
sizing. Excluding stores >45 km from the city median cut it to 4,891 points.

**2. Phantom stores.** Some coordinates return `serviceable: false` with no
`storeDetailsResponse`. Reading only `storeId` counted these as new stores with
a null name — Dehradun reported 2 that did not exist. Fixed by capturing
`serviceable` and `has_details` and flagging rather than deleting. 5 nationally.

**3. Misfiled stores.** Store names carry a city prefix (`BLR-`, `KUR-`, `GGN-`).
64 prefix→city mappings were derived at ≥80% agreement, plus explicit overrides
(`SAS`→Mohali, `PNK`→Panchkula). Nine stores were re-attributed — each predicted
from its prefix first, then confirmed by that city's scan.

### Deduplication — three layers

Redundancy is inevitable when scanning adjacent cities, so it is handled at
three points:

1. **within a scan** — on `store_id`
2. **across cities** — a global `is_new` check against every previously known id
3. **at merge** — keyed on `store_id`

This is what stops a store already found in Bengaluru being re-counted when a
neighbouring city is scanned.

### Result

**1,229 unique dark stores across 58 cities** (1,442 rows → 1,234 unique → 1,229
after excluding phantoms), up from 1,129 previously held — **+100 (+8.9%)**.

| City | Before | After |
|---|---|---|
| Delhi NCR | 214 | 266 |
| Mumbai | 115 | 140 |
| Lucknow | 25 | 32 |
| Mohali | 5 | 14 |
| Ambala | 7 | 2 (six were misfiled from elsewhere) |

128 grid-found stores had no pincode; 127 were resolved by reverse geocoding
(Nominatim, 1 req/s). One unresolved (`MUM-Ulwe`).

### Verification

Coordinates were round-tripped back through `get_page` and the returned store id
compared against the stored one. Kolkata: **51 of 53 (96.2%)**.

A mismatch does not necessarily mean bad data — several coordinates sit where
two catchments overlap, and `get_page` returns whichever store is primary at
that exact point. The stored id was found there, so it is real.

### Scripts

| File | Purpose |
|---|---|
| `scripts/zepto_discover_city_full.py` | two-phase per-city discovery — the core |
| `scripts/zepto_merge_final.py` | layer-3 merge and dedupe |
| `scripts/zepto_fill_missing_pincodes.py` | reverse-geocode grid-found stores |
| `scripts/zepto_verify_city_file.py` | round-trip coordinate verification |
| `scripts/zepto_export_darkstores.py` | Blinkit-schema export |
| `scripts/zepto_discovery_progress.py` | per-city progress |

Full write-up: `backend/docs/zepto_darkstore_discovery.txt`

### On the export

`zepto_darkstores_export.xlsx` mirrors `blinkit_darkstores_export.xlsx` for the
shared fields. Blinkit columns with no Zepto equivalent (`type`, `longtail_ids`,
`super_longtail_ids`, `unicorn_ids`) were **dropped rather than filled with
invented values** — Zepto has no store tiering, only a primary store plus
`secondaryStoreIds`.

⚠️ **The export does not carry `secondary`.** The keyword scraper reads
`zepto_FINAL_master_filled_*.xlsx`, not the export, because it needs those ids
for the `store_ids` header. Do not consolidate down to the export alone without
adding that column first.

---

## Task 4 — Transport (Q3)

### What was asked
Does direct `httpx` work, or is there a Cloudflare-class block?

### Answer: browser session required, but not per request

Raw `httpx` gets HTTP 429 even with valid cookies. But once headers are captured
from a real browser session, they can be **replayed** through Playwright's
request context:

```python
r = await ctx.request.post(f"{_BFF}{_SEARCH}", headers=h, data=json.dumps(body))
```

**~0.33 s per call**, versus ~3 s for a full `page.reload()`. This is the fast
probe technique the whole build depends on — a browser is needed to *establish*
the session, not to make each request.

Blinkit solves the equivalent problem differently, with an in-page fetch
(`page.evaluate(fetch(..., credentials:'include'))`) to get past Cloudflare.
That addresses bot detection, which is a different problem from Zepto's.

---

## Task 5 — Rate limits (Q10)

**This is the biggest operational difference from Blinkit and it is not solved.**

### Measured on a residential IP

| Pacing | Blocked after |
|---|---|
| 0.4 s (150/min) | **1 search** |
| 5 s (12/min) | 21 |
| 6 s (10/min) | 47 |
| 12 s (5/min) | 137 |

| Identity change | Loss |
|---|---|
| rotate session headers | 22.0% |
| brand-new browser context (fresh device_id + cookies) | 22.5% |
| 3.0 s pacing on a cold IP | 0% |

### Conclusions

- the limit tracks the **IP** — not the session, cookie, or device id
- it has **both a rate and a volume component**: pacing helps, but there is
  still a ceiling on total requests per window
- `get_page` and `search` have **separate budgets** — one can be healthy while
  the other is blocked
- **HTTP 299** is Zepto's non-standard throttle signal
- changing browser identity does **not** help

### Why Blinkit's solution does not port

Blinkit's orchestrator handles rate limiting with:

```python
_STORE_SKIP_AFTER = 2    # failed fetches at a store -> skip its keywords
_REFRESH_AFTER    = 8    # consecutive failures -> reopen session
_PACING           = 0.05
workers           = 5
_RETRY_DELAYS     = (0.5, 1.5, 3.0)
```

Retry, refresh, move on. Blinkit sustains 5 workers at 0.05 s spacing for 2,059
stores in ~1.5 h because per zepto.md Q10 its blocks are *"transient 403/429
[that] self-resolve on backoff"*.

Blinkit has blips. Zepto has a ceiling. Retry-and-refresh cures a blip and does
nothing against a ceiling — and the session-refresh remedy was measured above at
22% loss.

### The like-for-like comparison — confirmed with the Blinkit owner, 04-Aug

Same 9 keywords, same worker model, same VM, **both from a single IP**:

| | Blinkit | Zepto |
|---|---|---|
| stores × keywords | 2,059 × 9 = 18,531 searches | 1,229 × 9 = 11,061 searches |
| workers | **5, on one IP** | 1 (a 2nd just hits the same cap sooner) |
| sustained rate | **~68 searches/min** | ~5/min, then blocked |
| volume ceiling | **none observed** | ~137 searches at 12 s pacing |
| runtime | **4–5 h** | ~62 h projected |

Normalised for store count, Zepto is **~23× slower**. It decomposes as:

| factor | multiplier |
|---|---|
| concurrency (5 workers vs 1) | 5× |
| per-worker pacing (4.4 s vs 12 s) | 2.7× |
| rest overhead (40% of Zepto's runtime) | 1.7× |
| | **≈23×** |

**Blinkit running 5 concurrent workers off one IP is the proof:** Blinkit has no
per-IP volume cap and Zepto does. Same infrastructure, same code path — the only
variable is platform policy.

**There is no code change that fixes this.** Concurrency is the largest term and
it maps directly onto IP count:

```
5 IPs  ->  5 x 3 searches/min  ->  ~12 h   (at the job timeout)
10 IPs ->                          ~6 h    (comfortably inside it)
```

So the decision is **more IPs, or less often** — a commercial call, not an
engineering one. Note also that `zepto.md` currently states "~1.5 h for 2059
stores at 5 workers"; the like-for-like figure at 9 keywords is **4–5 h**, and
the capacity planning in that doc is built on the smaller number.

### Sampling is NOT available as a lever — measured 04-Aug

The obvious saving is "scrape fewer stores". Measured against 92 Bengaluru
stores, it does not hold:

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

Two related levers are equally unavailable if ranking fidelity matters:
`RESULT_CAP 30 → 15` halves requests but drops placements seen at #27–#36, and
`MAX_PAGES 3 → 2` truncates ranks 27–30.

Coverage cannot be traded for speed. **Cadence can** — every store, every
keyword, full ranking, run fortnightly instead of weekly, at zero cost to the
data. That is the D10-preferred lever and the one to take to the client.

### What was done instead

Pacing plus scheduled rests, in `scripts/zepto_keyword_scan.py`:

```python
SEARCH_GAP_S = 12.0
STORE_GAP_S  = 3.0
PAUSE_EVERY  = 110      # searches before a scheduled rest
PAUSE_S      = 900      # 15 min, then reopen the session
MAX_STORE_ATTEMPTS = 4
RECOVERY_WAITS_S   = [900, 1800, 2700, 3600]
```

Resting *before* the window closes is cheaper than sprinting into a block and
waiting out a 15–60 min recovery.

### Faster pacing is SLOWER end to end — tested 04-Aug

The 5 s and 12 s figures were measured before the `layout: null` bug was found,
so it was worth re-testing whether that bug had inflated them. **It had not.**
6 s blocked after 47 searches, and the block was genuine — one store blocked on
`sourdough`, which returns 30 and never pages past the end, so it cannot be the
parse bug.

Throughput with the block penalty included is what settles it:

| Pacing | Searches before stopping | Then | Effective |
|---|---|---|---|
| 6 s | 47 in 282 s | ~15 min **hard block** | **2.4/min** |
| 12 s | 110 (scheduled rest fires first) | 15 min **clean rest** | **3.0/min** |

Halving the gap made the run ~20% slower. A hard block costs more than a
scheduled pause: recovery after a block yields ~3 searches per 5-minute probe
cycle, while a clean pause resets the window properly.

**Do not re-litigate the pacing without new evidence.** It has now been tested
in both directions and 12 s is the floor on a residential IP.

### Wall-clock reality — the number to plan against

One city, Bengaluru, 169 stores × 9 keywords = 1,521 searches:

```
scraping   1,521 × 12 s          = 5.1 h
rests      1,521 ÷ 110 × 15 min  = 3.5 h
                                   ─────
                                   ~8.6 h  before any hard block
```

Roughly **40% of runtime is deliberate waiting**, and the observed run took
~11 h across two days including blocks.

Projected to the full catalog — 1,229 stores × 9 keywords = 11,061 searches:

```
scraping  37 h  +  rests 25 h  =  ~62 h
```

**The `batch` job timeout is 12 h**, and per [zepto.md](zepto.md) Blinkit and
Zepto share that lane, so the weekly window is the *sum* of both. All-India
weekly Zepto does not fit — not marginally, by a factor of five.

This is not a tuning failure, it is a capacity finding, and D10 already
anticipates it. Its levers in order of preference: **narrower coverage** (top N
cities), **lower cadence** (fortnightly), a retention policy, a paid tier.

Whoever picks this up should treat "which cities, how often" as a scoping
decision to settle with the client *before* building a schedule.

### Known inefficiency — ~25% of requests are wasted

`SEARCH_GAP_S` spaces *searches*, but the rate limiter counts *requests*, and
one search is up to 3 requests. Zepto's page size is ~12–27, not 30, so:

```
page 0: 14 rows
page 1: 12 rows   -> 26 total, still under RESULT_CAP
page 2:  0 rows   <- wasted request
```

A result reported as "30 products" typically cost 2 requests; anything under 30
costs 3, with the third usually empty. Effective request rate is therefore
~2.2× the search rate.

`MAX_PAGES = 3 → 2` would cut roughly a quarter of all requests, buying ~25%
more searches per window and therefore fewer rests. It was **not** applied to
the current run, deliberately: changing it midway would mean some stores were
scanned at 3 pages and others at 2, so a product-count difference between two
stores would no longer be attributable to the stores themselves. That silently
corrupts any store-vs-store comparison.

Apply it in the Phase 2 engine, where every store gets the same treatment from
the start — but validate first that page 2 is genuinely empty rather than
carrying ranks 27–30.

### ⚠️ Q12 is the open question that matters here

> Does the response differ between a datacenter IP (the Mumbai VM) and a
> residential one?

Blinkit's answer was "no difference, validated 2026-07-13". **Zepto is untested.**
Every measurement above is from a home connection. Per zepto.md, Zepto is meant
to run from the GCP Mumbai box — *"Never run a runner locally… a local runner
will scrape from a home IP."*

This decides whether the volume cap is a production constraint or a local
artefact, and it reshapes Phase 5 and the D10 disk gate. **Test it before
tuning anything else.**

---

## Task 6 — Remaining API facts (Q4–Q8, Q11)

| Q | Answer | Consequence |
|---|---|---|
| **Q4** store grain | per-product store id present → **store-grain** | D8 satisfied; Reach/Distribution denominators are meaningful |
| **Q5** brand field | explicit `brand` per product | own-vs-competitor is exact; no name-guessing or alias tuning |
| **Q6** pagination | `pageNumber`, `mode: SHOW_ALL_RESULTS`; **no** basic→similarity switch | no `follow_similarity` equivalent needed |
| **Q7** fields | typed numerics, **prices in paise** (`mrp: 11000` = ₹110.00) | parser divides by 100 |
| **Q8** pack strings | parse with the existing `pack.py` | no `_UOM`/`_TERM` extension needed (D7 respected) |
| **Q11** scale | 1,229 stores, 58 cities | feeds the D10 disk gate |

---

## The keyword-level scraper

Built as a client deliverable (Brik Oven, Bengaluru), but it is where every
Phase 0 finding was proven end to end. `scripts/zepto_keyword_scan.py`.

**It is not product code.** It lives in `backend/scripts/` and writes Excel, not
the database. Phase 2 rebuilds this properly under
`scraper/platforms/zepto/public_data/`. Read it as a working reference for the
mechanics.

### Shape

169 Bengaluru stores × 9 keywords = 1,521 searches. Resumable via a CSV
checkpoint — survives Ctrl-C, reboot, and rate limiting. Every completed
store×keyword pair is banked immediately, so nothing is ever re-fetched.

### Design decisions worth carrying into Phase 2

**No `get_page` per store.** An earlier version called `get_page` before each
store to re-confirm the binding. That doubled the request count and spent a
second, independently rate-limited budget for nothing — and when *that* budget
ran out, stores were skipped while `search` was perfectly healthy. The catalog
already holds every store id and its secondaries.

**Scrape everything, narrow at export.** The client named five competitors. All
30 SERP products are still captured; filtering happens at export. This keeps
`position` a true rank out of 30 rather than a rank among six, and adding a
competitor later costs a re-export instead of another full run.

**Re-queue partial stores.** A store blocked partway through keeps its completed
keywords and pushes only the uncollected ones back onto a pending queue, up to
`MAX_STORE_ATTEMPTS`. Before this, a mid-store block silently lost the rest of
that store's keywords.

**Sentinel rows for genuine zeroes.** `sourdough bread loaf` legitimately
returns 0 products at some stores. Writing no rows meant the pair never entered
the checkpoint and was retried forever. It is now recorded with a
`(no results)` sentinel brand, filtered at export.

### Bugs found — read these before writing the engine

**1. `layout: null` misreported as a rate-limit block.** The worst one.

```python
for w in data.get("layout", []):     # WRONG
```

On a page past the end of the result set Zepto sends `"layout": null`. The key
**is present**, so the `.get` default never applies — it returns `None`, and
iterating `None` raises. A bare `except Exception: pass` in `search()` swallowed
the crash, `page_rows` stayed `None`, and the code reported `BLOCKED`.

Symptoms, all of which looked like rate limiting and none of which were:
- blocked "after 1 search" on a completely fresh window
- the same stores failing every single run (it is deterministic, not rate-based)
- `check_rate_limit` reporting healthy (it only ever fires page 0)
- always on keywords where that store returns fewer than 30 products

Cost: a store that had genuinely fetched 26 products had all 26 discarded, was
marked blocked, and cycled the retry queue while the run sat waiting out a block
that did not exist.

```python
for w in (data.get("layout") or []):     # RIGHT
```

And in `search()`, only a throttle **status** now means blocked; a parse failure
with rows already in hand keeps the rows.

**2. Search headers never refreshed on a stale session.** Only `get_page`
headers were re-captured, so one expired search session poisoned every remaining
store. Fixed with a `refresh_session()` that re-captures both.

**3. HTTP 299 read as an empty result** and retried 3× *into* an active block,
prolonging it. 299 is now treated as throttling.

### Captured fields

`store_id, store_name, pincode, area, lat, lng, keyword, position, brand,
is_client, product_name, pack_size, mrp_rs, selling_price_rs, discount_pct,
discount_rs, in_stock, available_qty, rating, rating_count, category,
match_bucket, weight_g, product_id, variant_id, scraped_at`

---

## Outstanding

| Item | Blocker |
|---|---|
| **Q12** — datacenter vs residential IP | needs VM access |
| **D9 gate** — a live Blinkit `public-run` passing clean on the VM before Phase 2 merges | needs VM access |
| Capture the search **response** into `api.txt` | none — just needs an open rate-limit window |
| Delete the throwaway probe scripts | none |
| Commit everything to `feature/zepto-public-scrape` | none — all Zepto work is currently untracked |

---

## What Phase 0 unblocks

**Phase 2 (engine)** — the Q1–Q8 recon gate is cleared and every mechanism is
proven in working code. Still gated on D9 (VM).

**Phase 3 (catalog)** — was "Blocked on Q9". No longer blocked. Now largely a
`cli sync` of a catalog that already exists and has been verified.

**Be clear-eyed about what is not done:** none of this is in the product. It is
scripts writing Excel. It proved the mechanisms, produced a client deliverable,
and de-risked the hard parts — but the engine still has to be built.
