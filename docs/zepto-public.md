# Zepto — Public Data

How the Zepto public scrape works, what it costs, and the traps that produce
plausible wrong data.

**Supersedes** the old build plan (`zepto.md`, deleted 01-Sep-2026) and the
capacity/rate-limit sections of [zepto_handover.md](zepto_handover.md) — §3 in
particular. Those were built on a per-IP volume cap that **does not exist**;
everything below was re-measured from scratch on 30-31 Aug 2026 and validated on
real runs.

The handover's *measurements* reproduce well (its 47-searches-at-6 s came back as
42) and its §1 (the 1,229-store catalogue), §9 (platform behaviours), §10
(verifying a rank) and §11 (catalogue naming) remain the reference. What was
wrong was the label on the numbers, because nothing was reading the response body
that said `LOGIN_REQUIRED`.

**Read first:** [ARCHITECTURE.md](ARCHITECTURE.md) ·
[public-glossary.md](public-glossary.md) · [staging.md](staging.md) ·
[per-unit-price.md](per-unit-price.md)

---

## TL;DR

* **There is no volume quota.** 14,279 requests were spent in one afternoon and
  the arms that ran *after* all of them were the cleanest of the day.
* **There is a rate limit, and 2 s pacing clears it entirely.** A validated run:
  169 stores × 9 keywords = **1,521 requests in 56.6 minutes, 100% success, zero
  blocks, 29,125 rows**.
* **One worker.** Four workers returned 1.02× the throughput of one while wasting
  76% of their requests. The limiter is per connection — scale with IPs, not
  workers.
* **Three failure modes, three remedies.** Collapsing them into one "blocked"
  state is what made this platform look impossible.
* **Run between 14:00 and 22:00.** Mornings deliver ~36-51% success; from ~14:00
  it is 100% and holds through at least 21:30.

Previous projection for a national run: **62 hours**. Measured: **~7 hours**.

---

## How it works

Nothing above the engine is Zepto-specific — it is the same path Blinkit uses.

```
config.xlsx ──cli sync──> marketplace_locations   (1,229 Zepto dark stores)
tenant watchlist (brands · keywords · aliases · caps)
      │
      ├── orchestrator.py   keyword scrape  → search_snapshots + search_listings
      └── targeted.py       brand scrape    → sku_snapshots
                    │
              providers.py   open_session / search / close_session / parse
                    │
              platforms/zepto/public_data/
                    │
              staging.py → local SQLite  →  cli scrape load → Postgres
```

**Store binding is the one thing to understand.** A Zepto search binds to a store
by HTTP header, never by coordinate. Send a lat/lon and it is silently ignored —
you get a valid 200 carrying a generic catalogue. The four headers are
`store_id`, `storeid`, `store_ids`, `store_etas`.

Consequence: Blinkit can be scraped from a list of coordinates; Zepto cannot. The
store **ids** are required, which is why the dark-store catalogue is a hard
prerequisite rather than a reporting nicety.

Re-verify whenever session or header logic changes: two stores that should
differ, one keyword, compare the products. Identical results across stores that
should differ means the binding has silently broken and every row is worthless.

---

## The three failure modes

These look identical in a log — a non-200. They are unrelated systems with
different scopes, different clocks and **opposite remedies**.

| | `429` | `299` | `202` |
|---|---|---|---|
| meaning | too fast, right now | anonymous allowance spent | session's AWS WAF pass is stale |
| body | — | `{"error_code":"LOGIN_REQUIRED", "message":"Oops! Please login to continue searching"}` | empty; header `x-amzn-waf-action: challenge` |
| scope | connection | connection — **shared across sessions** | **that one session only** |
| clears | ~60-80 s | ~60 s | **never** |
| remedy | slow down | pause ~60 s, retry | **re-mint the pass** |

`202` is the expensive one. A challenged session is dead permanently, so waiting
on it can never succeed — the previous build slept up to an hour and then retried
with the same dead session, which on its own is enough to make the platform look
like it has a 12-hour cooldown.

The pass is the **`aws-waf-token` cookie**, it lives **4-6 minutes**, and nothing
on the page refreshes it (`window.AwsWafIntegration` is absent). The engine
re-mints on a 4-minute timer rather than discovering expiry as a wall of 202s.

> **A block is never an empty shelf.** `search()` returns `ok=False` on any
> non-200 and never an empty product list. Recording a gate as zero products
> invents a plausible, well-formed, wrong answer — a store that stocks the brand
> reported as not stocking it.

### A fourth block: the browser itself (2026-09-24)

From 24 Sept every session failed before its first search: the warm-up's
**homepage and search page answered HTTP 429** (a blank page), so no search headers
were captured ("no session headers captured"). Not the ~60 s `429` above — it
persisted for 30+ minutes, and a human's browser on the same connection was fine.

Diagnosed 26 Sept, same machine, same IP, seconds apart: since Playwright 1.49,
`chromium.launch(headless=True)` runs a stripped-down **`chromium-headless-shell`**,
and Zepto's firewall refuses it — it solves the 202 challenge, gets the pass cookie,
then 429s every page. A visible browser went straight through, and so did the
**full Chromium in headless mode** (`channel="chromium"`): 50 Bengaluru stores,
50/50 OK, 0 blocks, ~740 MB RAM, ~4% of a core.

So every Zepto shopper session — this scrape, the own-SKU scrape, the Explorer and
the bid engine's rank checks — launches through ONE function,
`platforms/zepto/public_data/scraper.launch_browser`, with
`endpoints.BROWSER_CHANNEL = "chromium"` (the worker pools reach it via
`providers.Provider.launch_browser`; Blinkit keeps the default). It needs
Playwright ≥ 1.49 and `playwright install chromium` on the machine. Pinned by
`public_data/tests/test_browser_launch.py`.

Nothing noticed this for days: the last Zepto scrape had run on 1 Sept and there is
no schedule, so a daily "can a session open?" check is on the list.

### A fifth: the VM's address, and replaying through a proxy (2026-09-28/30)

The GCP VM's own address is refused outright: the warm-up gets a 202 challenge and then a
CloudFront 403. That is why public scrapes run on a residential laptop, not the VM.

The bid engine's rank checks have to run on the VM, so they can go through a consumer-line
proxy. Through a proxy, the **replayed** search this scraper is built on is refused (429, and
the proxy's address stayed flagged afterwards), while the page's own requests are answered.
So a session opened with `typed=True` searches by typing into Zepto's search box instead
(`public_data/typed_search.py`), and `search()` hands such a session over transparently.

Only the bid engine opens one; the scrapes never do. The switch, the rules and the cost are
in [campaign-manager.md](campaign-manager.md), "Zepto's shopper search through a proxy".

---

## Tunables, and the measurements behind them

All in `platforms/zepto/public_data/endpoints.py`.

Throughput vs pacing, 4-minute arms, riding through blocks:

```
 pace   sent    ok   blocked   success
  0.0  13648    83         0        1%   429 storm
  0.5    406   111       100       27%
  1.0    225    48         0       21%
  2.0    107   106         0       99%   <- clean
  4.0     57    57         0      100%
  8.0     29    28         0       97%
 12.0     20    20         0      100%
```

| Constant | Value | Why |
|---|---|---|
| `SEARCH_GAP_S` | 2.0 | Fastest pacing that stays completely clean |
| `STORE_GAP_S` | 0.0 | `SEARCH_GAP_S` already paces everything |
| `MAX_WORKERS` | 1 | 4 workers = 1.02× of 1, wasting 76% of requests |
| `RESULT_CAP` | 30 | One page. Only 1.9% of own-brand placements sit deeper |
| `PAUSE_EVERY` | None | No volume quota exists to rest before |
| `GATE_PAUSE_S` | 60 | Measured recovery |
| `PASS_REFRESH_S` | 240 | Pass lives 4-6 min |

`--workers` is inert on Zepto: any value runs single-worker, logged once at INFO.
Blinkit is unaffected (`max_workers=None` means no ceiling).

### Why one page

Measured across every stored row: **1.9%** of Zepto own-brand placements sit past
position 30, against **5.9%** on Blinkit. A second page doubles the run to
recover that 1.9%.

The honest cost: ~90 keyword/store pairs would be reported as *absent when
present* — a wrong answer, not just a missing one. Accepted, because halving a
national run is worth more.

**Raise it per keyword via `keyword_cap`**, not globally. Broad head terms
genuinely fill page 2 (`milk` returned 17 new products there); the current niche
keyword set returns 4-16 rows and never does.

**Dedupe is mandatory at any depth.** A single 30-item page carried 3 duplicates,
and page 1 repeated 29% of page 0. Key on `variant_id` falling back to
`product_id`, and keep the FIRST sighting — it carries the true best rank.

**But key on `(product, is_ad)`, not on the product alone.** A product can hold two
REAL slots on one page — its organic placement and a sponsored one (`sourdough bread`
showed one SKU organic at 1/2/4 and sponsored at 7/9/13). The "3 duplicates in a
30-item page" cited above were almost certainly those pairs rather than artifacts.
The targeted own-SKU scrape passes `distinct_ad_slots=False` to collapse them back,
because it measures a product's state at a store, not its placements on a page — see
`scraper/public/providers.py`.

---

## Pack size and combos

`pack.py`'s grammar is `"225 ml"` / `"12 x 250 ml"`. Zepto's `formattedPacksize`
reads `"1 pack (400 g)"`, which it parses at **2.2%** — so pack size, per-unit
price and `is_combo` were all broken.

Zepto supplies the size **structured**, at 100% fill:

```
productVariant.packsize        total content, already multiplied out
productVariant.unitOfMeasure   GRAM | MILLILITRE | PIECE | LITER | KILOGRAM | COMBO
```

`platforms/zepto/public_data/packs.py` rebuilds a canonical string in `pack.py`'s
own grammar, so the existing pipeline works untouched. Coverage: **2.2% → ~100%**.

```
"1 pack (400 g)"          ->  "400 g"
"1 pack (50 x 20 g)"      ->  "50 x 20 g"
"200 ml X 2"              ->  "2 x 200 ml"
"1 pack (400 g or 430 g)" ->  "400 g"      (first value)
```

Three things worth knowing:

* **The multiplier still comes from the string.** `productVariant.quantity` is
  NOT the pack count — it is stock, identical to `availableQuantity`; the same
  pack string shows 1, 3 and 7 on different rows.
* **Zepto zeroes `packsize` on anything it labels `COMBO`** — including
  homogeneous multipacks like `"200 ml X 2"` that have a perfectly good
  denominator. The string fallback recovers those.
* **Normalisation lives in the ENGINE, not the parser.** `targeted.py` calls
  `provider.search()` and never calls `parse()`, so a parser-side fix would leave
  `sku_snapshots` silently broken while the keyword scrape looked fine.

`pack_raw` keeps Zepto's original string, so a normaliser fix is a backfill,
never a re-scrape.

---

## What is NOT available

Zepto ships its ads and ranking internals in the response **schema** and **zeroes
the values** for anonymous clients. Measured across 557 items:

```
meta.is_fly_wheel_ad                     False × 557
meta.ads_deboosting_old_position         0 × 557
cachedReRankingParams.IsOrganicBucket    False × 557
rankingParams.l30RPI / l30ORD            0 × 557
searchFeedOrder · zeptoPassPrice         0 × 557
```

The keyword set deliberately included the terms most likely to carry sponsored
placements (`milk`, `chocolate`, `chips`, `shampoo`). All zero.

🔴 **Superseded 2026-09-01 — this section once concluded that public data cannot
split SoV by paid vs organic on Zepto, and that an `is_ad` column was "proposed and
withdrawn". That was wrong.** Every field listed above is genuinely zeroed, but the
sponsored marker is not among them: it lives in `productResponse.meta.tagsV2`, keyed
by badge SLOT (`P0`, `P3`, …) rather than by meaning, which is why a scan of the
obvious field names missed it. On a live `bread` search, 9 of 24 results were
sponsored. The column exists, is populated, and carries the `uclId` with it — see
`platforms/zepto/public_data/ads.py`.

⚠️ `is_fly_wheel_ad` is the trap, not the marker. It sits on the same `meta` block
and reads `False` even on confirmed sponsored rows (verified on 10 of our own ads).
It marks Zepto's organic "flywheel" re-ranking. Reading it as the ad flag is what
made ads look invisible for two days — and is most of why the paragraph above was
written.

**Sold-out products are not shown at all.** Unlike Blinkit, Zepto's search leaves a
sold-out product out of the results rather than flagging it: 0 `outOfStock` rows in
6,073 keyword results, 1,495 own-SKU rows (165 stores, 1-9 Brik Oven products each)
and 1,479 results of a 50-store test. So on Zepto:

* **Distribution % (in-stock ÷ listed) is not measurable** from public data — every
  listed row is in stock by construction. What varies is how MANY products a store
  lists, which is the stock signal.
* **A product missing from a search is either out of stock or not sold there** — the
  two cannot be told apart, and neither can "outbid" from "sold out" when an ad is
  missing. This is why the bid engine confirms stock with a brand search before
  raising, and moves to another store when the product is not there
  (docs/campaign-manager.md, "Zepto rotates through its stores").

---

## What a run costs

**Unit: 1 request = 1 keyword × 1 store × 1 page ≈ 30 products.** 30 is a hard
ceiling; twelve page-size parameter conventions were tested and every one is
silently ignored.

```
minutes = (stores × keywords × pages) ÷ requests-per-minute
```

| Window | Rate | Per 100 requests |
|---|---:|---:|
| Peak (14:00-21:30) | 27/min | **3.7 min** |
| Mid (~13:00) | 17/min | 5.9 min |
| Morning (10:00-12:00) | 10-14/min | 7-10 min |

One keyword, single page, every store:

| Scope | Stores | Peak | Blended |
|---|---:|---:|---:|
| Per 100 stores | 100 | **3.7 min** | 5.9 min |
| Bengaluru | 169 | 6.3 min | 9.9 min |
| Mumbai | 140 | 5.2 min | 8.2 min |
| Delhi NCR | 266 | 9.9 min | 15.6 min |
| **All India** | **1,229** | **46 min** | 72 min |

Rule of thumb: **a keyword costs ~6 minutes per 160 stores**; one IP delivers
~1,600 store-keyword-pages per hour.

### By workload

| Workload | Requests | Peak | Cadence |
|---|---:|---:|---|
| Keyword scrape — 9 kw × all-India × 1 page | 11,061 | ~6.9 h | occasional |
| Brand/inventory — 1 kw × all-India × 2 pages | 2,458 | ~1.5 h | weekly |
| Bidding — per 15-min cycle | ≤150 | — | continuous |

**Bidding must be sized for the WORST hour**, not the best — it runs continuously
and hits the ~10/min morning every day. Safe budget is ~100 requests per cycle
across all automations, which is ~100 automations at 1 store each, or ~16-20 at
5-6 stores. The bid engine therefore reads ONE store per automation per tick
(rotating through a city's frozen stores only when one cannot sell the product) —
1 search a tick, 2 when our ad is missing and stock has to be checked; a brand
search is cached ~1 h per store and serves every automation there.

### Throughput across the day

```
10:19   51%   417 prod/min        14:56  100%   784 prod/min
11:52   36%   305 prod/min        15:59  100%   776 prod/min
13:53   61%   495 prod/min        21:30  100%   735 prod/min
```

An **eight-hour full-rate window**, wide enough for a national run to start and
finish inside it. The IP took ~1,600 requests across that day and was still at
100% at 21:30 — cumulative usage accrues no penalty; the morning dip is the hour,
not the spend.

**Unmeasured:** 22:00-10:00. One overnight run showed ~30% slower responses after
midnight (no blocks), so a 7 h run started at 14:00 crosses into a slower band
near its end.

---

## Running it

```bash
# keyword scrape (SoV / rank / competitors)
python -m cli scrape public-run  -m zepto -t <tenant> --city bengaluru
python -m cli scrape public-run  -m zepto -t <tenant> --no-load    # stage only

# own-SKU scrape (price / stock / inventory)
python -m cli scrape public-skus -m zepto -t <tenant> --city bengaluru

# staged files, then load
python -m cli scrape staged
python -m cli scrape load <file> --dry-run
```

`--workers` is accepted and ignored. `--resume` skips already-staged stores.
Nothing touches Postgres during a scrape — the run stages to SQLite and the
loader pushes later in one all-or-nothing transaction.

---

## Traps

Each of these produces plausible, well-formed, **incorrect** data with no error.

**`data.get("layout", [])` is wrong.** Zepto sends `"layout": null` past the end
of results. The key is *present*, so the default never applies and iterating
`None` raises. Always `data.get("layout") or []`.

**Not every `PRODUCT_GRID` is a search result.** A `HEADER_WIDGET` titled
"Similar Products" starts a recommendation carousel. Counting past it turns
recommendations into ranks — it produced positions of 41, 48 and 66 for a query
whose real result set was 11 items.

**Prices are in PAISE.** `mrp: 11000` is ₹110.00.

**`position` is 0-based** in the payload; the shared contract is 1-based.

**`availableQuantity` lives on `productResponse`**, not on `productVariant`.
Reading it off the variant returns None for every row, which then makes
`in_stock` default to True everywhere.

**A session must re-target on every store.** One session walks many stores, so
`merchant_id` must be passed per search. Without it every store returns the SEED
store's catalogue, with correct-looking rows attached to the wrong merchant.

**Pacing must be unconditional.** The gap fires after *every* search including
ones that return nothing. Thin keywords are common, and skipping the gap on those
trips the rate limit within a minute.

---

## Open

* **No schedule.** The last keyword scrape ran 2026-09-01 and the last own-SKU
  scrape 2026-09-02, so every Zepto public view shows early-September data. Public
  scraping is to move to separate infra — never the bidding VM, whose IP and search
  allowance the bid engine needs (agreed 2026-09-26; the guard that enforces this on
  the VM is not built yet).
* **No daily "can a session open?" check** — the 24 Sept browser block went
  unnoticed because nothing was running (see "A fourth block" above).
* **Overnight rate (22:00-10:00)** unmeasured — needed before any overnight Zepto
  bid window.
* **`is_ad` unproven on stored rows** — all 6,073 were loaded before the marker; the
  first scheduled run is the check.

Closed since this page was written:

* ~~`public-skus` has never run end to end~~ — it ran 2026-09-02: 1,495
  `sku_snapshots` rows across 165 Bengaluru stores.
* ~~`search_listings.extra` is not written for Zepto~~ — it is, but only the
  engine's small generic keys (`unit`, `category`, `group_id`, `match_reason`…).
  Zepto's detail (`brand_id`, manufacturer, scores…) still goes only on
  `sku_snapshots.extra`, for the size reason: ~212k rows per national run.
* ~~Bidding storage~~ — the bid engine stores per-store READINGS
  (`cm_bid_store_reads`: position, stock verdict, bid; 30-day trim), never listings.
