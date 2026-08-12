# Zepto — Complete Handover

**Date:** 06-Aug-2026 · **Branch:** `zepto-dark-stores-discover`
**Supersedes:** `zepto_status.md` and `zepto_phase0_handover.md`
**Companion:** [zepto.md](zepto.md) — the build plan with decisions D1–D11

---

## TL;DR

1. **The store catalog was built, not bought** — 1,229 dark stores across 58
   cities. This was Phase 3's blocker (Q9) and it is solved.
2. **A search binds to a store by HTTP header, not by coordinate.** Send a
   lat/lng and it is silently ignored — you get a valid 200 carrying a generic
   catalog. This is the single most important fact about the platform.
3. **The full pipeline runs end to end**, the same path Blinkit uses:
   `config.xlsx → cli sync → DB → orchestrator → engine → staging.sqlite3 →
   cli scrape load → Postgres`. Verified with real rows on 06-Aug.
4. **Zepto is ~23× slower per store than Blinkit** — it enforces a per-IP volume
   cap where Blinkit does not. This is platform policy, not a code problem, and
   no scraper change fixes it. **This is the decision that needs your input.**
5. **Not all `PRODUCT_GRID` widgets are search results.** A `HEADER_WIDGET`
   titled "Similar Products" starts a recommendation carousel, and counting past
   it turns recommendations into ranks. That plus three other platform
   behaviours are in [§9](#9-zepto-behaviours-your-code-must-handle) — read it
   before trusting a scrape, because each one produces plausible, well-formed,
   incorrect data with no error.

---

## Status by phase

| Phase | State | Blocker |
|---|---|---|
| **0 — Recon** | 6 of 7 tasks done | **Q12** — datacenter vs residential IP, needs VM |
| **1 — Provider refactor** | 7 of 8 checks done | **live Blinkit run on the VM** (the D9 gate) |
| **2 — Zepto engine** | **built and validated** | 4 stubs not yet deleted; merge waits on D9 |
| **3 — Store catalog** | **DONE** — synced 06-Aug | — |
| **4 — First real run** | **done for Bengaluru** | other cities need coverage rows |
| **5 — Scale + disk gate** | orchestrator pacing done | D10 disk gate not measured |
| **6 — Read layer** | not started | dashboard shows no Zepto data |

Phase 0 and Phase 1 have **one blocker each, and it is the same one: VM access** —
which the team has agreed to defer.

---

## 1. The dark store catalog

### Why it had to be built

Q9 in the plan asked where Zepto's catalog would come from, and flagged it as
*"the one open question that may need a non-engineering answer"* — the
expectation was to source an export the way Blinkit's 2,059-store list was
obtained. No such export exists for Zepto.

### How

Two phases per city:

1. **Pincode sweep** — `autocomplete` → `place details` → `get_page`. Cheap, and
   returns a full address, but only finds stores near a pincode centroid.
2. **Grid scan** — a 0.006° (~666 m) lattice over the city's bounding box,
   asking `get_page` "which store serves this point?" at every node.

**The grid resolution was measured, not guessed.** At 1 km a Bellandur store was
missed; at 666 m, *"known stores not hit by grid = 0"* in all 58 cities.

### Three problems found and fixed

**Outliers stretched the bounding box.** Jaipur came to 158,608 grid points — 109
minutes for one city — because two stores 199 km away were included in the sizing.
Excluding stores >45 km from the city median cut it to 4,891.

**Phantom stores.** Some coordinates return `serviceable: false` with no store
details. Reading only `storeId` counted these as new stores with a null name.
Now flagged, not counted. 5 nationally.

**Misfiled stores.** Store names carry a city prefix (`BLR-`, `KUR-`, `GGN-`). 64
prefix→city mappings were derived at ≥80% agreement, plus explicit overrides.
Nine stores were re-attributed, each predicted from its prefix then confirmed.

### Deduplication — three layers

1. within a scan, on `store_id`
2. across cities, against every previously known id
3. again at merge

This is what stops a store found in Bengaluru being re-counted when a neighbouring
city is scanned.

### Result

**1,229 unique stores across 58 cities**, up from 1,129 previously held (+8.9%).

| City | Before | After |
|---|---|---|
| Delhi NCR | 214 | 266 |
| Mumbai | 115 | 140 |
| Lucknow | 25 | 32 |
| Mohali | 5 | 14 |
| Ambala | 7 | 2 (six were misfiled from elsewhere) |

128 grid-found stores had no pincode; 127 resolved by reverse geocoding. One
unresolved (`MUM-Ulwe`).

**Verified** by round-tripping coordinates back through `get_page` and comparing
the returned store id. Kolkata: 51 of 53 (96.2%).

---

## 2. The API — Phase 0 findings

### Endpoints

All on `https://bff-gateway.zepto.com`:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/maps/place/autocomplete/` | text → area + `place_id` |
| `GET /api/v1/maps/place/details/` | place → lat/lng/city/state |
| `GET /lms/api/v2/get_page` | **coordinate → serving store** |
| `POST /user-search-service/api/v3/search` | keyword + store headers → products |

Fully documented in `zepto/public_data/api.txt` (62 KB, request **and** response).

### Store binding — the finding that matters most

The plan warned: *"a request that accepts a coordinate and ignores it is the
silent failure."* That is exactly what Zepto does.

Tested on four stores, comparing **results** rather than status codes:

| Approach | Result |
|---|---|
| lat/lng in the request body | all four returned the **identical** catalog |
| `store_id`/`storeid`/`store_ids`/`store_etas` headers | **4 of 4 correct** |

`store_ids` is the primary id **plus that store's secondaries**, comma-joined.

**Consequence:** Blinkit can be scraped from a list of coordinates. Zepto cannot —
you need the store **ids**, which is why building the catalog stopped being a
reporting nicety and became a hard prerequisite.

**How to re-verify** (worth doing any time session or header logic changes): two
stores that should differ, one keyword, compare output. Identical results across
stores that should differ means the binding has silently broken and every row
being collected is worthless.

### The other questions

| Q | Answer | Consequence |
|---|---|---|
| Q3 transport | browser session required; headers then replayable at ~0.33 s/call | no pure-httpx engine |
| Q4 store grain | per-product store id present → **store-grain** | Reach/Distribution denominators are meaningful |
| Q5 brand | explicit `brand` field | own-vs-competitor is exact, no name guessing |
| Q6 pagination | `pageNumber`; no basic→similarity switch | no `follow_similarity` equivalent needed |
| Q7 fields | typed numerics, **prices in PAISE** (`mrp: 11000` = ₹110.00) | parser divides by 100 |
| Q8 pack strings | parse with the existing `pack.py` | no `_UOM`/`_TERM` changes (D7 respected) |
| **Q12** | **OPEN — needs the VM** | decides whether the volume cap is a production constraint |

---

## 3. The performance problem — needs a decision

### Like-for-like with Blinkit

Same 9 keywords, same worker model, same VM, **both from a single IP**:

| | Blinkit | Zepto |
|---|---|---|
| stores × keywords | 2,059 × 9 = 18,531 searches | 1,229 × 9 = 11,061 |
| workers | **5, on one IP** | 1 (a 2nd hits the same cap sooner) |
| sustained rate | **~68 searches/min** | ~5/min, then blocked |
| volume ceiling | **none observed** | ~137 searches, drifting to ~65 across a day |
| runtime | **4–5 h** | ~62 h projected |

Normalised for store count, **Zepto is ~23× slower**:

| factor | multiplier |
|---|---|
| concurrency (5 workers vs 1) | 5× |
| per-worker pacing (4.4 s vs 12 s) | 2.7× |
| forced rest overhead (40% of runtime) | 1.7× |

### Why concurrency is not freely available

Blinkit runs **5 concurrent workers off one IP** and sustains it for 18,531
searches. That is only possible if Blinkit has no per-IP volume cap — if it did,
5 workers sharing an IP would share one budget and finish no sooner.

Zepto does have that cap, and it tracks the **IP**, not the session:

| change | result |
|---|---|
| rotate session headers | 22.0% loss |
| entirely new browser context (fresh device_id + cookies) | 22.5% loss |
| slow down on a cold IP | 0% loss |

Zepto ignored *who* we claimed to be and only cared *where we came from*.

### Measured block thresholds (residential IP)

| pacing | rate | blocked after |
|---|---|---|
| 0.4 s | 150/min | **1 search** |
| 5 s | 12/min | 21 |
| 6 s | 10/min | 47 |
| 12 s | 5/min | **137** |

These are not equal in request terms (~2 to ~300), so the cap is not a fixed
quota — the budget partly refills as you go and speed outruns the refill. **Both a
rate and a volume component are present.**

**There is also a longer window.** Across one day the ceiling drifted
**137 → 86 → 117 → 65 → 8**, and **~12 hours of rest restored it fully**. Mornings
run materially better than evenings.

### What this means for scheduling

```
one city  (1,521 searches)   ~8.6 h   before any block
all India (11,061 searches)  ~62 h
batch job timeout             12 h    -- and Blinkit shares the lane
```

**All-India weekly Zepto does not fit — by roughly a factor of five.**

This is a capacity finding, not a tuning failure, and D10 already anticipates it.
Its levers in order of preference: **narrower coverage** (top N cities), **lower
cadence** (fortnightly), a retention policy, a paid tier.

### What was tried and ruled out

| approach | result |
|---|---|
| more workers | same IP, same cap — reaches the wall proportionally sooner |
| faster pacing (6 s) | blocked after 47; **20% slower end-to-end** than 12 s |
| session rotation / fresh identity | 22% loss, no gain |
| retry + session refresh (Blinkit's remedy) | cures a transient blip; useless against a ceiling |
| **scrape fewer stores** | **not viable — see below** |
| smaller `RESULT_CAP` | halves requests but drops placements seen at #27–#36 |
| `MAX_PAGES` 3→2 | truncates ranks 27–30 |

### Sampling stores is NOT available as a lever

Measured across 92 Bengaluru stores:

| keyword | stores | distinct product sets | median pairwise overlap |
|---|---|---|---|
| sourdough | 92 | **92** | 46% |
| sourdough bread | 92 | **92** | 50% |
| ricotta | 92 | **92** | 43% |
| mozzarella | 92 | 88 | 62% |

**No two stores carry the same assortment**, and two random stores share under half
their products. A sampled subset does not approximate the whole — a brand's rank at
an unscraped store is genuinely unknowable.

**Coverage cannot be traded for speed. Cadence can** — every store, every keyword,
full ranking, run fortnightly rather than weekly, at zero cost to data quality.

### What concurrency DID buy

5 workers, measured 05-Aug on a rested IP:

```
1 worker   5.0 searches/min    Bengaluru in ~11 h
5 workers  9.7 searches/min    Bengaluru in  2.7 h    4.1x faster
```

Blocks arrive sooner (~150 searches instead of ~576) because the budget is shared,
but **recovery is only ~5 minutes** when you probe rather than sleep blind — so the
net is a genuine 4×. This is the configuration Phase 5 should adopt.

---

## 4. What was built

### The engine (Phase 2)

```
scraper/platforms/zepto/public_data/
    endpoints.py   NEW   every URL, header, body, tunable — nothing inline elsewhere
    parser.py      NEW   thin; identical contract to Blinkit's
    scraper.py     NEW   mirrors Blinkit's section layout exactly
    api.txt              request + response, 62 KB
```

Provider registered `wired=True`. All five signatures (`open_session`,
`open_context_session`, `close_session`, `search`, `scrape`) match Blinkit's byte
for byte; `parser.parse()` returns an identical key set.

**The non-negotiables from the spec, all present:** double-enforced fetch timeout,
a non-JSON 200 treated as a challenge rather than an empty page, dedupe keeping the
**first** sighting, running-order position fallback, and `open_context_session` not
owning the shared browser.

**One Zepto-specific design call:** the provider interface passes `lat/lon`, but
Zepto binds by store id. `_make_session` resolves the coordinate to a store **once
per session** and caches it. Resolving per search would spend `get_page`'s separate,
independently rate-limited budget on every call — which is exactly how an earlier
version ran dry while search was perfectly healthy.

### Folder structure — and the one package Blinkit does not have

The engine path is now an exact structural match:

```
scraper/platforms/blinkit/public_data/   endpoints.py  scraper.py  parser.py  api.txt
scraper/platforms/zepto/public_data/     endpoints.py  scraper.py  parser.py  api.txt
```

**`scraper/platforms/zepto/dark_store/` has no Blinkit counterpart — deliberately.**

| | Blinkit | Zepto |
|---|---|---|
| where the catalog came from | supplied export | **built here** |
| who refreshes it | the supplier | **us** |
| discovery code needed | none | `dark_store/` + the catalog scripts |

**It is not on the scrape path.** The scraper never imports it:

```
dark_store/ + zepto_discover_*.py  ->  master xlsx
                                   ->  config.xlsx (mp=zepto)
                                   ->  cli sync
                                   ->  marketplace_locations
                                   ->  scraper reads the DB
```

**Why it is kept:** dark stores open and close — Bengaluru moved 134 → 169 during
this build alone. With these tables a refresh is a day's work; without them it
means rediscovering grid resolution, outlier exclusion, phantom detection and
prefix attribution from scratch, roughly a week.

### `config.xlsx` (Phase 3, prepared not applied)

```
locations   2,059 blinkit (mp blank)  +  1,229 zepto  =  3,288
brands          6 Dobra               +      6 Brik Oven
coverage      242 Dobra               +      1 Brik Oven/zepto
```

An `mp` column was added to `locations` and `coverage`. **Blinkit's rows were not
edited** — they gain an empty cell, and `sync.py`'s `DEFAULT_MP` reads blank as
blinkit. Cities lowercased to match Blinkit's convention.

Validated by parsing through `sync.py`'s own reader: 0 duplicate
`(mp, merchant_id)` pairs, 0 blank merchant ids, and the coverage row
`zepto | Brik Oven | bengaluru` matches **169 locations** — the join that fails
silently if city case is wrong.

Backup at `config.backup-20260805.xlsx`.

### Client deliverable — Brik Oven, Bengaluru

169 stores × 9 keywords × all competitors, run twice:

| | 04-Aug | 05-Aug |
|---|---|---|
| runtime | 11 h (1 worker) | **2.7 h (5 workers)** |
| product rows | 36,770 | 36,349 |
| Brik Oven rows | 1,242 | **1,665** |
| stores stocking Brik Oven | 163/169 | **169/169** |
| head-to-head wins | 71% | **83%** |

Both runs collected equivalent SERP depth (mean 24.9 vs 24.3 products), so the
movement is real. **In 24 hours Brik Oven reached full city distribution** and its
win rate rose 12 points, while mozzarella presence fell 42%.

`Suchali` — one of the client's five named competitors — **does not appear on any
Zepto SERP** across 36,000+ rows. Reported explicitly rather than silently omitted.

---

## 5. What we need from you

| # | Need | Why |
|---|---|---|
| 1 | **VM access** (GCP Mumbai, repo + Playwright) | Q12, **and** the D9 gate which blocks Phase 2 from merging |
| 2 | **Decision: proxies, or lower cadence** | 5 IPs → ~12 h, 10 IPs → ~6 h. Circumventing a control Zepto put there deliberately is a company call, not an engineering one |
| 3 | **Tenant record for Brik Oven** | which account, and is the name exactly "Brik Oven"? `config.xlsx` looks tenants up by exact string |
| 4 | **Sign-off to run `cli sync`** | a write to the shared DB; dry run expects `added=1229, deleted=0` |
| 5 | **The `keyword_cap` behind the Blinkit 4–5 h figure** | converts the comparison from approximate to exact |

**Also worth correcting:** `zepto.md` states "~1.5 h for 2059 stores at 5 workers".
The like-for-like figure at 9 keywords is **4–5 h**, and the capacity planning in
that doc rests on the smaller number.

---

## 6. What is NOT done

- **Nothing is in the database.** `config.xlsx` is ready; `cli sync` has not run.
  Consequence: no history, no week-on-week comparison, nothing in the dashboard.
- **Phase 2 is not merged** — blocked on D9. Two items also remain: the four
  original stubs are still present (`cli/commands/scrape.py:677` imports
  `zepto...storage`, which the spec says not to recreate), and the smoke test —
  same keyword at two coordinates returning **different catalogs** — has not run.
- **The orchestrator is Blinkit-tuned.** `_PACING = 0.05` with 5 workers is
  ~150 searches/min, which on Zepto blocks immediately. It needs Zepto's 12 s
  pacing, rest cycle and probe-based recovery before `public-run -m zepto` is
  usable. That is Phase 5.
- **Q12 untested.** Every rate measurement here is from a residential connection.
- **There is no Zepto seller-dashboard access — only public data.** This splits
  the CLI cleanly in two:
  - **Public-data commands are already shared**, marketplace selected by value,
    not by a different command: `cli sync` (platform comes from the row's `mp`
    column), `cli scrape public-run --marketplace zepto`, `cli scrape public
    --platform zepto`. `zepto` is registered `wired=True` in
    `scraper/public/providers.py` — a real provider, not a stub like
    `instamart`.
  - **Seller-side commands are Blinkit-only**, because the module they'd import
    doesn't exist for Zepto: `cli/commands/auth.py` imports
    `scraper.platforms.blinkit.auth` and
    `scraper.platforms.blinkit.dashboard_data.seller.auth` with no Zepto
    equivalent. Same for ads, campaign manager, and the SKU-level stock probes.
  - **Consequence for the dashboard:** until a `scraper/platforms/zepto/
    dashboard_data/seller/` package is built (mirroring Blinkit's — auth,
    scraper, parser, storage), Zepto can only ever populate what public search
    data supports: **Competition** (pricing, rank, SoV) and **Inventory**
    (on-shelf/out-of-stock presence). Overview's KPI strip (ad spend, ad
    revenue, RoAS, total/organic revenue, units sold), Products' sales columns,
    Reports' sales pivot, Ads/Campaign Manager, and Scorecard all read seller
    data and will show blank/zero for Zepto regardless of how complete the
    public-data integration is — that's a scope boundary, not a bug to chase.

---

## 7. How to run what exists

```bash
# Is the search window open? (one request)
python -m scripts.zepto_rate_experiments --ceiling

# Keyword scrape — the fast path, 5 workers
python -m scripts.zepto_keyword_scan_parallel --tag <name> --workers 5
python -m scripts.zepto_keyword_scan --tag <name> --export

# Catalog refresh, when stores go stale
python -m scripts.zepto_discover_all_cities
python -m scripts.zepto_merge_final
python -m scripts.zepto_fill_missing_pincodes
python -m scripts.zepto_export_darkstores

# Once the tenant exists
python -m cli sync --dry-run     # expect added=1229, deleted=0 — STOP if not
python -m cli sync
python -m cli locations list -m zepto
```

**A run costs ~1,500 searches and drains the IP for ~12 hours.** Check `--ceiling`
before starting, and expect one full-city run per day on a single residential IP.

---

## 8. Known traps

**`data.get("layout", [])` is wrong.** Zepto sends `"layout": null` on a page past
the end of the results. The key is *present*, so the default never applies, `None`
comes back and iterating it raises. Use `data.get("layout") or []`.

This one cost two days: the exception was swallowed by a bare `except`, the store
was reported as `BLOCKED`, its already-fetched products were discarded, and the run
sat waiting out a rate limit that did not exist. Every symptom looked like
throttling — blocked "after 1 search" on a fresh window, the same stores failing
every run, `check_rate_limit` reporting healthy.

**Header capture must outlive the navigation.** Zepto fires its requests *after*
`domcontentloaded`, so removing the listener when `goto()` returns captures nothing.
The polling loop in `_capture` is load-bearing.

**HTTP 299** is Zepto's non-standard throttle signal. Treat it as a block, never as
an empty result — retrying into it prolongs the block.

**Prices are in paise.** `mrp: 11000` is ₹110.00.

**`secondary` store ids are part of the binding** and must not be dropped when
consolidating files. `marketplace_locations` currently has no column for them; a
two-search test (primary only vs primary + secondaries) would settle whether one is
needed before designing a migration.

---

## 9. Zepto behaviours your code must handle

Four things about this platform that are not obvious from the API, and that a
naive implementation gets wrong **without any error appearing**. Each one
produces plausible, well-formed, incorrect data — which is why they are worth
reading before trusting a scrape.

### Not every PRODUCT_GRID is a search result

A search response is **sectioned**, and only the first section is the search:

```
TITLE_WIDGET        "Showing results for sourdough"
PRODUCT_GRID x4     <- the actual results (11 items)
OOS_SEARCH_WIDGET   "Some items are temporarily out of stock"
HEADER_WIDGET       "Similar Products"          <- BOUNDARY
PRODUCT_GRID x3     <- a recommendation carousel, NOT ranks 12-20
```

Collecting every `PRODUCT_GRID` turns that carousel into search ranks. Paging
compounds it: once the results have ended, later pages continue the carousel, so
a 9-result query yields positions of 41, 48, 66.

**What it looks like when wrong:** a brand at "rank 34" on a page showing ~24
products; a competitor at #2 on the page and #9 in the data. Nothing errors.

**Handled by** `SECTION_BREAK_WIDGETS` in `endpoints.py`. `_extract_products`
returns `(products, hit_break)` and `search()` stops paging on a break.

### A session must re-target on every store

The worker pool opens one session per worker from a seed coordinate and then
walks many stores through it. Blinkit re-targets per call via its lat/lon
headers, so this is invisible there.

Zepto binds by store id header. A session that resolves its store once and keeps
it will return **that one store's catalog for every store in the run** — the Q2
silent failure, with correct-looking rows attached to the wrong merchant.

**Handled by** passing `merchant_id` into `search()`. The caller is iterating
catalog rows, so it already knows the store — no lookup needed, and no calls to
`get_page`, which carries its own separate rate-limit budget.

`Provider.search` therefore takes `merchant_id`; Blinkit accepts and ignores it.
That asymmetry is D8 in practice: for Blinkit the merchant is an **output** read
off the products, for Zepto it is an **input**.

**Guard already in place:** the orchestrator warns when the observed store id
differs from the catalog's. That warning is the only thing that surfaces this
failure — do not remove it.

### Pacing must be unconditional

`search_gap_s` has to fire after **every** search, including ones that return
nothing. Thin keywords are common — `sourdough bread loaf` returns 0-6 products
at most stores — and skipping the gap on those is enough to trip the rate limit
within a minute even at 5 workers.

### Syncing a new marketplace needs its `marketplaces` row first

`marketplace_locations.mp_slug` is an FK to `marketplaces.slug`. That row is
normally created by `ensure_refs()` on the scrape path — which means a
marketplace that has never been scraped cannot have its catalog synced, and the
locations insert fails on the foreign key.

`cli sync` now seeds every marketplace the file declares before inserting
locations. **Instamart will need this too.**

---

## 10. Verifying a rank against the live site

The only honest comparison, and it has to be all four steps:

1. set zepto.com to a location
2. read `storeId` from the `get_page` response in DevTools
3. scrape **that store id** within the same minute
4. compare

Done this way, a check matched **13 of 13 products** on name, order and price.

Anything looser compares different stores or different moments:

**A pincode is not a store.**

```
bengaluru: 169 stores across 80 pincodes   (~2.1 per pincode)
pincode 560037 alone has EIGHT stores
```

Two stores in the same pincode carry different catalogues — median pairwise
overlap across Bengaluru is 43-62%. Filtering an export by pincode tells you
nothing about which store the site gave you. **`merchant_id` is the unit.**

**Ranks move within hours.** One product was observed at 13, then 12, then 11
over an afternoon as competitors went out of stock. A scrape is a snapshot;
`scraped_at` is stamped at scrape time and carried through untouched.

**The page lazy-loads.** It renders ~24 products until you scroll; the result set
can be far longer. Count what the API counts, including repeats.

---

## 11. Catalog naming — grid-found stores

150 of the 1,229 stores were found by grid scan rather than pincode lookup. Their
stored coordinate is the **lattice node the scan happened to hit**, not the
store's address — it can be 2 km out — and `location_name` was reverse-geocoded
from that node. That produced `"Punjab"` as an area name, and a Chandigarh store
labelled Sector 7 where Zepto calls it Sector 26.

Scrape data is unaffected: binding is by `merchant_id`, and those nodes provably
resolve to the right store. But it made those rows impossible to verify by hand —
searching the reverse-geocoded name on zepto.com lands nowhere near the store.

`location_name` for those rows now carries **Zepto's own store name** instead
(136 rows updated in `config.xlsx`; no schema change).

`scripts/zepto_refine_new_store_coords.py` would tighten the coordinates too, by
probing a dense 330 m grid and taking the centroid of the served area. It costs
roughly 1,250-2,500 `get_page` calls and has not been run.

---

## 12. Field-level status

**Verified correct:** prices, MRP, discount, stock, brand classification
(`is_brand` true only on the client's own brand), store binding, section
boundaries, and rank when compared same-store / same-minute.

**Known gaps:**

* `pack_size` / `pack_uom` are NULL on every Zepto row — `pack.py` does not parse
  `"1 pack (400 g)"`. This breaks per-unit pricing (D7).
* `merchant_type` is always empty. Correct — Zepto has no store tiering — but
  worth knowing before it is read as missing data.
* the four original stubs in `zepto/public_data/` are still present.
  `cli/commands/scrape.py:677` imports `storage`, which the spec says not to
  recreate, so removing them needs that ad-hoc path repointed first.

### Checking tools

| file | purpose |
|---|---|
| `scripts/zepto_db_peek.py` | read-only summary of what is in Postgres |
| `scripts/zepto_export_from_db.py` | Excel view of loaded data, for eyeballing a run |

Neither is pipeline. Delete both once the dashboard shows this data.
