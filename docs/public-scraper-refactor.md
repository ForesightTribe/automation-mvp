# Public Scrapers Refactor — Plan

Status: **Phase 1 DONE** (migration `f3a9c1d7b2e5`). **Phase 2 + 3 core DONE for
Blinkit** (rewrite + classification, validated live — `dobra` rank #1, 75% SoV).
**Phase 4 DONE** (per-tenant writer, live-verified). **Phase 5 DONE** —
orchestrator `scraper/public/orchestrator.py` (`run_tenant`/`run_all`) + CLI
`scrape public-run --tenant <id> | --all [--cap N]`; reads watchlist +
tenant_locations from DB, one session per location reused across keywords. **Phase
6 DONE (dormant)** — scheduler wired to `run_public_scrapes` (daily 03:00) but
opt-in: `start_scheduler()` is not called at startup, so it won't fire until added
to the app lifespan/worker. DB pool capped (server + CLI coexist). Instamart/Zepto
**out of scope**. **Config via one workbook + `sync`** (no per-row CRUD verbs): `config.xlsx`
sheets `locations`/`brands`/`coverage` are the source of truth; `cli sync`
reconciles the DB (upsert default, `--dry-run`, `--prune`, `--template`). Dry-run
validated. **Remaining: user fills `config.xlsx` with real data → `sync` → full
run.** Phase 7 read-layer mostly done; competitor price-trend endpoint optional.

## Performance — session reuse (2026-06-30)

The v1 orchestrator opened a fresh browser **per store** (~13s warmup × 2,216 ≈
20h). Reworked to open **one session per run** and sweep stores by swapping the
`lat`/`lon` headers — Blinkit selects the dark store from those headers, so no
re-navigation. Verified live: 3 cities off one session, ~0.4s/fetch, correct store
each. Full run ≈ **~2.7h single-threaded** (was ~20h). Concurrency is a *later*
lever (would take it under an hour).

- `scraper.search(session, kw, cap, lat=, lon=)` overrides the location per call;
  returns `ok` (first fetch got 200) to distinguish failure from empty.
- Orchestrator: one session; per-store fail-fast (skip after 2 fails); session
  refresh after 8 consecutive cross-store failures (cf_bm ~30min expiry); 50ms
  pacing. Modeled on the teammate's `foresight/.../darkstores.py:search_products_batch`.
- **httpx is not usable** — Cloudflare 403s it (TLS fingerprint) even with the
  browser's cookies, on both http1.1 and http2. In-page fetch only.

**Reliability (2026-06-30):**
- **Incremental commits** — `storage.save` commits per (store, keyword), so a
  crash keeps everything already scraped.
- **Retry with backoff** — `_in_page_fetch` retries transient 403/429/5xx/network
  blips (0.5/1.5/3s) before giving up; a 200 returns immediately.
- **Resume is per-JOB, not per-date** — every `public-run` is a `scrape_job`; a
  fresh run always full-scrapes (so you can run 2–3×/day, each a new job).
  `--resume` continues the tenant's last *incomplete* job, skipping the
  `(keyword, lat, lon)` pairs it already saved (`search_snapshots WHERE job_id`).
  Verified via the summary's new `Skipped` column.
- **Page size is hard-capped at 12** server-side (Blinkit ignores `limit`>12), so
  `cap>12` costs extra API calls only on keywords with >12 real results
  (self-limiting); shallow keywords stay 1 call. `RESULT_CAP` currently 30.
- **Competitor whitelist (2026-06-30).** `classify_products(..., competitors=)`
  stores only own-brand + the tenant's **declared** competitors (watchlist rows
  with `relationship=competitor`, matched by slug/aliases); other brands are
  counted for rank/SoV but not stored. SoV/rank are computed over the FULL page,
  not the filtered subset. **No competitor rows declared → keep ALL brands
  (discovery mode); declare competitor rows to narrow to a whitelist.** Workflow:
  run once to discover which brands appear, then curate the whitelist.
- Reference only: `Foresight/foresight` is the teammate's old repo (unrelated to
  automation-mvp); consulted for technique, not reused.

**Concurrency (2026-07-01).** `run_tenant(..., workers=N)` runs a pool of N isolated
browser **contexts on one browser**, each with its own DB session, pulling stores
off a shared `asyncio.Queue`. Since fetches are network-bound, N workers ≈ N×
throughput (fetch-bound: ~40–50s/store at cap 36 → single-thread ~18h; pool of
5–6 → ~3–4h). CLI: `--workers N` (default 5). Shared, safe under asyncio's single
thread: `done` set (resume, read-only), `ensured` (idempotent brand upserts),
`stats` counters. DB `pool_size` raised to 10 to fit ~5–8 workers + main (Supabase
session pooler caps at 15, so keep workers ≤ ~8). Log line now carries the worker
id (`w3`) and `[processed/total]`. **Not yet live-tested** — validate with a
bounded run first (`--city <one> --workers 5`), watch for Cloudflare 403s (drop to
3–4 if they appear).

## Operating it — command surface

```
# 1. Configure (edit the workbook, then reconcile the DB)
cli sync --template --file config.xlsx     # write a starter workbook
cli sync --file config.xlsx --dry-run      # preview changes
cli sync --file config.xlsx                # apply (upsert; add --prune to delete)

# 2. Inspect
cli locations list [--city <slug>] [--tenant <id>]
cli watchlist list --tenant <id>

# 3. Run
cli scrape public-run --tenant <id>                  # full watchlist × coverage
cli scrape public-run --all                          # every active tenant
cli scrape public-run --tenant <id> --keyword soda   # just-in-case: one keyword
cli scrape public-run --tenant <id> --city delhi --cap 36
```

`config.xlsx` is the source of truth (never read by scrapers); `cities.py` is
unused by this path. Tenants must pre-exist (`cli tenant create`); the workbook
references them by name. `config.example.xlsx` is a filled sample.

**Locations keyed on `merchant_id`** (migration `b8d2f4a6c1e3` added
`merchant_id`/`state`/`region` to `marketplace_locations`; unique on
`mp_slug+merchant_id`). Rationale: the source catalog has empty zones and
missing/`grid_` pincodes, so `(city,zone,pincode)` collided and dropped stores;
`merchant_id` is the stable key, lat/lon is what the scraper targets, pincode/zone
are best-effort blanks. `locations` sheet cols: `merchant_id, city, state, region,
zone, pincode, lat, lon, active`.

**Config extraction** (`scripts/extract_config.py`, one-off): converts the
manager's "Dark Store Data" workbook → `config.xlsx`. Keeps reliable fields, blanks
ambiguous ones. First run: 2,216 stores (16 border-dupes deduped), 11 Dobra
keywords, 181 coverage cities. Dry-run synced clean (2216/1/2216). **A full run is
~2,216 stores × 11 keywords ≈ 24k searches — subset mechanism is a later task.**

## Goal

Turn the public scraper from a standalone, manual, tenant-blind tool into a
per-tenant system that is wired into the multi-tenant model the same way the
private (dashboard) scrapers are: spec-driven, job-tracked, and stored per
`tenant_id`.

## Locked decisions

- **Per-tenant storage** — `tenant_id` on every public data row. Public data is
  *not* shared/deduplicated across tenants. Rationale: near-zero keyword overlap
  expected between clients, so dedup saves almost nothing while shared storage
  forces a watchlist-lens read indirection. At near-zero overlap the scrape
  *volume* is identical either way, so partitioning's simplicity wins.
- **Header + detail storage** — a small pre-aggregated header row per search
  (`search_snapshots`) for cheap trend queries, plus per-product detail rows
  (`search_listings`) for drill-down (competitors, discounts, stock).
- **Lean store** — store the tenant's own-brand products + named competitor
  products as rows. The unnamed tail is NOT stored as rows; it survives only as
  `total_results` on the header (enough for SoV math). ~15 rows/search vs ~20.
- **Discounts provisioned, not populated** — `mrp`/`discount_pct` columns exist
  now but stay `NULL`; the scraper change to capture MRP comes later, after the
  core system is fixed. No future migration needed.
- **Shared location reference** — `(marketplace, city, pincode, lat, lon)` is
  objective serviceability data (the DB form of `cities.py`); the tenant *selects*
  which locations it tracks. Pincodes are not copied onto every tenant.
- **Watchlist-driven orchestration** — the per-tenant spec (brands, keywords,
  aliases, locations) drives scraping. Replaces the manual CLI-only flow.
- **Job-lineage parity** — every public scrape opens a `scrape_jobs` row, like
  the private path.

## Current state (what's live vs dead)

- Only `SearchResult` (`search_results`) is ever written — by all three platform
  `public_data/storage.py` `save()` functions, with `products[]`/`competitors[]`
  as JSON blobs. No `tenant_id`, no `scrape_job`.
- `competitor_rankings` — *read* by `competition_service.get_rankings`, but
  **never written** → `/rankings` returns empty today.
- `inventory_depth` — *read* by `inventory_service`/`overview_service`, but
  **never written** → inventory dashboard is dataless.
- `scraped_products`, `brand_snapshots` — not read, not written. Dead.
- Read side is already tenant-scoped via `tenant_watchlist` (the
  `competition_service` filters `search_results` to the client's watched brands).
  The *write* side ignores the watchlist entirely — that's the gap.
- Instamart/Zepto public scrapers ARE implemented (httpx API + Playwright
  fallback) but brittle (guessed JSON paths/selectors). Blinkit is the solid
  reference (in-page `fetch()` to bypass Cloudflare).
- Scheduler is a dead stub: `scheduler/runner.py` is a no-op; `scheduler/jobs.py`
  imports a `BlinkitScraper` class that no longer exists.

## Volume sizing (1 brand, daily, ~4,000 darkstores across all MPs)

Scrape grain = `keyword × darkstore`. Each search → 1 snapshot row + ~15 listing
rows. Rule of thumb: **≈ 0.75 GB / keyword / month** (incl. indexes).

| Keywords | Searches/day | Listings/mo | Storage added/mo |
|---|---|---|---|
| 10 | 40,000 | 18 M | ~7.5 GB |
| 20 | 80,000 | 36 M | ~15 GB |
| 50 | 200,000 | 90 M | ~38 GB |

Append-only → it accumulates (20 kw ≈ 180 GB after 12 months). Supabase $ is
modest (~tens/mo + larger compute tier), but two things bite first:
1. **Scrape throughput** — 20 kw × 4,000 stores ≈ ~1 search/sec sustained 24/7
   per brand. Browser-based scraping won't sustain a full census → **sample
   pincodes** + **reuse the browser session** (capture headers once, loop
   lat/lon+keyword as in-page fetches).
2. **Cumulative growth** → retention + monthly partitioning from day one.

Private data is a rounding error next to public listings.

## Phases

### Phase 1 — Data model & migration

- **Reuse `scrape_jobs`** as-is: `dashboard="public_search"`, `platform=<mp>`.
  No schema change.
- **`search_snapshots`** (evolve `search_results`) — header:
  - **+** `tenant_id` (FK, indexed), `job_id` (FK)
  - keep `mp_slug, brand_slug, keyword, city, pincode, zone, lat, lon,
    scraped_at, brand_rank, brand_sov, total_results`
  - **drop** `products`/`competitors`/`raw` JSON, `merchant_id`, `store_type`
  - indexes: `(tenant_id, mp_slug, keyword, scraped_at)`,
    `(tenant_id, brand_slug, scraped_at)`
- **`search_listings`** (new — replaces `competitor_rankings` + `scraped_products`):
  `id, snapshot_id FK, tenant_id, job_id, mp_slug, keyword, city, pincode,
  scraped_at, position, product_name, brand_slug (nullable), is_brand, price,
  mrp (NULL), discount_pct (NULL), in_stock, inventory, platform_product_id,
  extra JSON`. `scraped_at` denormalized as partition key. Indexes:
  `(tenant_id, mp_slug, keyword, scraped_at)`, `(snapshot_id)`,
  `(tenant_id, brand_slug, scraped_at)`.
- **`marketplace_locations`** (new shared ref — DB form of `cities.py`):
  `id, mp_slug, city, zone, pincode, lat, lon, is_active`. Seed from `cities.py`.
- **`tenant_locations`** (new — per-tenant selection):
  `tenant_id, mp_slug, location_id → marketplace_locations`.
- **`inventory_depth`** — add `tenant_id, job_id` now; write path stays unwired.
- **Watchlist reshape** — add `aliases[]` (for competitor matching); retire the
  flat `cities[]`/`marketplaces[]` (locations move to `tenant_locations`).
- **Drop** `scraped_products`, `brand_snapshots`.
- One Alembic revision does all of it.
- **Resolved:** clean break (drop+recreate). Migration `f3a9c1d7b2e5`
  (down_revision `adcf3ccd495b`).

**As-built (Phase 1):**
- Models: `SearchSnapshot`, `SearchListing`, `MarketplaceLocation`,
  `TenantLocation` added; `InventoryDepth` gains `tenant_id`/`job_id`;
  `SearchResult`/`CompetitorRanking`/`ScrapedProduct`/`BrandSnapshot` removed.
  `search_listings` also carries `zone` (denormalized, for the rankings view).
- `tenant_watchlist.aliases` added (JSON, default `[]`). The flat
  `cities[]`/`marketplaces[]` are **kept for now** (still used by the watchlist
  API); they retire when locations move to `tenant_locations` in a later phase.
- Readers kept importable: `analytics_service` + `competition_service` SoV now
  read `search_snapshots` **and** filter by `tenant_id`. `competition_service.
  get_rankings` was rewired early to `search_listings` (`is_brand=false`,
  tenant-scoped) since `competitor_rankings` is gone — pulled forward from Phase 7.
- The three platform `public_data/storage.py` `save()` are **transitional
  no-ops** (log + skip) until the shared per-tenant writer in Phase 4; `scrape
  public` still scrapes and prints.
- **Applied 2026-06-30.** Note: the DB's `alembic_version` was stale at
  `e428162c451f` while the schema was actually at `adcf3ccd495b` (role + marketing
  restructure applied out-of-band). Reconciled with `alembic stamp adcf3ccd495b`
  before `alembic upgrade head`. Stop the uvicorn dev server before running
  migrations — the app engine has no pool cap and can use all 15 session-pooler
  slots, blocking Alembic.

### Phase 2 — Scraper layer (Blinkit first)

- **Batch by session**: capture location context once per `(mp, location)`
  browser session, loop keywords as in-page fetches → `keywords × locations`
  launches collapse to `≈ locations`.
- Unify each platform to `fetch_batch(location, keywords) -> raw` (one shape);
  move shared Playwright/header-capture into `scraper/utils`.
- **Richer extraction**: `mrp`/original price (provision discount), `inventory`,
  `platform_product_id`, `in_stock`. Raw in `scraper.py`, typed in `parser.py`.

**As-built (Phase 2 — Blinkit, 2026-06-30):**
- `endpoints.py` added — all URLs, header keys, `SEARCH_BODY`, and tunables incl.
  `RESULT_CAP = 12` (the pagination cap; one place to change).
- `scraper.py` rewritten around a **reusable session**: `open_session` captures
  Cloudflare clearance + headers once per location; `search()` paginates Blinkit's
  own `next_url`, stopping at `RESULT_CAP` or when `search_method` flips from
  `basic` to `similarity`. `scrape()` kept CLI-compatible (opens/closes its own
  session); Phase 5 orchestrator will reuse one session across keywords.
- Extraction reads the **typed `cart_item`** block (price/mrp/inventory/brand/
  product_id/group_id/merchant_id/unit) + `tracking.common_attributes`
  (product_position, category l0/l1/l2, ptype, match reason). Stored extras land
  in `search_listings.extra`.
- **Finding:** Blinkit's public search has **no sponsored/ad flag** (checked brand
  + generic queries) — paid placements are blended in unlabeled. Own paid-vs-
  organic stays a private-dashboard concern (`blinkit_sponsored_sov`).
- Snapshot gets `merchant_id` (the dark store) + `total_results` from
  `search_count`.

**As-built (Phase 3 core — classification):**
- `scraper/utils/search_result.py` gained `classify_products()` (+ `slugify`,
  `discount_pct`). Uses each product's explicit `brand` field (exact), falls back
  to name match when absent (Instamart/Zepto until their rewrite). Emits the
  enriched `listings` rows + snapshot summary. `mrp`/`discount_pct` are now
  **populated** (data is free in the response — reversed the earlier "defer").
- Validated offline against the saved `dobra` + `soda` responses: prices, MRP,
  discounts, positions, own-vs-competitor split all correct.

### Phase 3 — Classification (brand vs competitor)

- Replace the "first two words of name" heuristic in
  `scraper/utils/search_result.py:build_result`.
- Match each product against own brand (slug+aliases) and the tenant's
  competitor brands (slug+aliases from watchlist) → assign `brand_slug`+`is_brand`.
  Unmatched → not stored, only counted in `total_results`.
- Emit `brand_rank`, `brand_sov`, per-competitor counts.

### Phase 4 — Storage

- One shared, platform-agnostic `save(session, tenant_id, job_id, parsed)`:
  1 snapshot + N listing rows in one transaction, both carrying
  `tenant_id`+`job_id`. Append-only. `ensure_refs` still upserts
  brands+marketplaces (own + competitor slugs). Retire the three per-platform
  `storage.py` saves.

**As-built (Phase 4 — 2026-06-30):**
- `blinkit/public_data/storage.py` `save(session, result, tenant_id, job_id)`:
  ensure_refs for own + every competitor slug, write 1 `SearchSnapshot` (flush for
  id) + N `SearchListing` rows sharing one `scraped_at`, both tagged
  `tenant_id`/`job_id`. Listing `extra` holds group_id, merchant_id, merchant_type,
  unit, ptype, category, match_reason, image_url. Returns rows written.
- CLI `scrape public` gained `--tenant`; with `--save` it opens a `scrape_jobs`
  row (`dashboard=public_search`), saves per zone, completes/fails the job, prints
  rows written. `--save` now requires `--tenant`.
- Instamart/Zepto `save()` are signature-compatible no-ops (Blinkit-only).
- New CLI: `watchlist add/list` (brand + keywords + aliases per tenant) and
  `locations seed/list/attach` (marketplace_locations + tenant_locations).

**DIRECTIVE — `cities.py` is being retired:** its data is unreliable and is NOT a
source of truth. `marketplace_locations` (DB) is the sole source for locations.
- The Phase 5 orchestrator must read locations ONLY from the DB, never `cities.py`.
- `cities.py` currently lingers in two spots: the ad-hoc `scrape public --city`
  coord lookup, and `locations seed`. Both are testing-only conveniences.
- Final cleanup (once real locations are seeded): repoint ad-hoc `scrape public`
  to resolve coords from `marketplace_locations`, drop the `cities.py` seed path,
  then delete `cities.py`.
- For now it's used ONLY to give approximate coords for save smoke-tests — its
  inaccuracy doesn't affect what those tests check (that the DB write works).
- Pending: a live `--save` run to confirm rows land. The watchlist/locations
  tables are populated now but not yet *consumed* — that's the Phase 5 orchestrator.

### Phase 5 — Orchestrator (the missing wiring)

New `scraper/public/orchestrator.py`:
1. Load target tenant(s).
2. Per tenant: read watchlist (brands, keywords, aliases) + `tenant_locations`.
3. Build task set `(mp, location) → [keywords]`; dedup within tenant; optional
   `sample N` locations/city.
4. Open one `scrape_jobs` row.
5. Per `(mp, location)`: `fetch_batch` → classify → save. Reuse one SERP across
   multiple own-brands.
6. Complete/fail job with `records_written`. Concurrency semaphore + Cloudflare
   jitter pacing.

### Phase 6 — Scheduler + CLI

- `runner.py`: register a daily public job → orchestrator; delete dead
  `scheduler/jobs.py` `BlinkitScraper` reference.
- CLI: `scrape public --tenant <id>` (whole watchlist) + `--all` (every active
  tenant); keep `--keyword/--brand` ad-hoc mode for testing but require
  `--tenant` to persist; add `--sample N`.

### Phase 7 — Read/API rewire

- `competition_service`: swap watchlist-lens filtering for
  `WHERE tenant_id = client.id`. `get_rankings` reads the now-populated
  `search_listings` (not the empty `competitor_rankings`). Add a competitor
  price-trend endpoint (listings grouped by `brand_slug` over time).
- `inventory_service`/`overview_service`: read `search_listings.in_stock/inventory`
  until the deep probe lands.
- `analytics_service`: read `search_snapshots`. Update schemas.

### Phase 8 — Retention & partitioning

- Monthly partition `search_listings` on `scraped_at`.
- Retention: keep raw detail 60–90 days, roll older into daily aggregates (or
  drop partitions); keep `search_snapshots` long-term.

### Phase 9 — Cleanup & tests

- Delete `ScrapedProduct`, `BrandSnapshot`, `CompetitorRanking` models + refs.
- Tests: batch-parse fixtures per platform, classification units, storage
  round-trip, orchestrator task-expansion, rewired read endpoints.

## Suggested PR sequence

1. Schema migration + models + drop dead tables (Phase 1).
2. Scraper batching + richer extraction + classification, Blinkit (Phase 2–3).
3. Storage + orchestrator + CLI per-tenant (Phase 4–6).
4. Read rewire (Phase 7).
5. Scheduler + retention/partitioning (Phase 6/8).
6. Stabilize Instamart/Zepto (Phase 2 applied to the brittle two).

## Open questions to resolve before Phase 1

1. **Census or sampled darkstores?** Sets orchestrator sampling defaults and how
   hard we lean on partitioning/retention. (Sampling hook built either way.)
2. **`search_results` data — preserve or clean break?** Decides migration shape.

---

## Addendum — Targeted own-SKU scrape (`public-skus`) — BUILT

The keyword scrape is a *discovery* lens: an own SKU only shows if it ranks in the
top `cap` for a category keyword. That leaves gaps in own price/inventory (client
flagged this). Fix = a second, complementary scrape.

**Same engine, four differences** (vs `public-run`):

| | keyword scrape | targeted scrape |
|---|---|---|
| query | category keywords (`soda`) | **brand name** (`dobra`) |
| pagination | `keyword_cap` (e.g. 12) | **`brand_cap`** (e.g. 60 — whole catalog) |
| classify | own + competitor whitelist | **own only** (`competitors=[]`) |
| storage | `search_snapshots` + `search_listings` | **`sku_snapshots`** (flat, keyed on `platform_product_id`) |

A brand-name query reliably returns the brand's whole catalog, so it *guarantees*
own coverage where a category keyword can't. Own price/inventory truth → targeted
scrape; SoV/rank + competitors → keyword scrape. Resolve the "overlap" at the read
layer, not by dropping capture (competitors are *only* available via the keyword
scrape).

**Storage — single flat table** (`sku_snapshots`, append-only). One row per
(product × store × scrape): `platform_product_id` (the identity — names drift, ids
don't), `product_name` (display only), store (`merchant_id`/`city`/`lat`/`lon`),
`scraped_at`, and the volatile metrics `price` / `mrp` / `discount_pct` / `in_stock`
/ `inventory` / `rating`. Query/group by `platform_product_id`. No dimension split
(MVP) — the name repeats per row but that's cheap and harmless since joins are on id.

**Config — two caps on the watchlist.** `keyword_cap` + `brand_cap` are columns on
`tenant_watchlist` (own rows), set via the `brands` sheet of `config.xlsx`. No new
settings table — brand-scoped knobs live with the brand. Precedence for both:
`CLI flag > tenant cap (config) > default` (12 / 60). A dedicated `tenant_settings`
table is only warranted once settings become tenant-wide + non-brand (cadence,
workers, per-MP toggles).

**New metric.** `rating` (and `product_state`) are already in the search payload's
`common_attributes` — `_extract_product` now pulls both; `sku_snapshots` stores
`rating`.

**Orchestrator** — `scraper/public/targeted.py` (`run_targeted` / `run_all_targeted`):
same worker-pool as the keyword orchestrator (one browser, N context-workers on a
shared store queue, per-worker DB session), one `scrape_job` (dashboard
`public_skus`), `--resume` skips stores already in `sku_snapshots` for the job.

**CLI**: `scrape public-skus --tenant <id> [--all] [--resume] [--city <slug>]
[--brand-cap N] [--workers N]`.

**Files**: `app/models/search.py` (`SkuSnapshot`), `app/models/tenant.py`
(watchlist caps), migration `c9e1a4b7d206`, `blinkit/public_data/sku_storage.py`,
`scraper/public/targeted.py`, `cli/commands/scrape.py` (`public-skus`),
`cli/commands/sync.py` (caps), `endpoints.py` (`BRAND_RESULT_CAP=60`).

**Not yet live-tested** — validate with `public-skus --tenant <id> --city <one>
--workers 3` before a full run. Apply the migration first: `alembic upgrade head`
(→ `c9e1a4b7d206`; stop uvicorn first — pooler 15-cap).
