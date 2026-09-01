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

**So public data cannot split share of voice by paid vs organic on Zepto.** If
the dashboard needs that, it has to come from the seller/ads side. An `is_ad`
column was proposed and **withdrawn** — a column that is always `False` is worse
than no column, because it reads as a measurement.

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
5-6 stores.

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

* **`public-skus` has never run end to end on Zepto.** The brand query is
  verified (it finds strictly more own SKUs than the keyword set at the same
  store), but the `targeted.py` → `sku_snapshots` path is untested.
* **Overnight rate (22:00-10:00)** unmeasured.
* **`search_listings.extra` is not written for Zepto** — deliberately. At ~212k
  rows per national run a JSON blob costs ~85 MB against a 500 MB quota, for
  fields nothing queries. The richness goes on `sku_snapshots.extra` instead,
  which is 6-17× smaller.
* **Bidding storage.** At 15-minute cadence, storing full listings is ~1 GB/month
  against a 500 MB quota. Store own-SKU rank and price only, plus a retention
  policy — a schema decision to make before the automation is built.
