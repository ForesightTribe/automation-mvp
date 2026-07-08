# Architecture

## Directory Layout

```
automation-mvp/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── config.py              # Pydantic Settings — loads .env, all config lives here
│   │   │   ├── database.py            # engine, AsyncSessionLocal, get_session()
│   │   │   └── security.py            # JWT encode/decode, password hashing
│   │   ├── models/                    # SQLModel table classes — source of truth for schema
│   │   │   ├── brand.py               # Brand, Marketplace
│   │   │   ├── tenant.py              # Tenant, User, TenantWatchlist
│   │   │   ├── job.py                 # ScrapeJob, PlatformSession
│   │   │   ├── search.py              # SearchSnapshot, SearchListing, SkuSnapshot, SkuMap, MarketplaceLocation, TenantLocation, InventoryDepth
│   │   │   ├── blinkit_seller.py      # BlinkitSellerSale, BlinkitPO, BlinkitSOH, BlinkitScorecard*
│   │   │   └── blinkit_marketing.py   # AdPerformanceSummary, AdCampaign, SponsoredSOV, BrandCollection, VisibilityPlan
│   │   ├── api/
│   │   │   ├── routes/                # FastAPI route handlers (thin — call scraper functions directly)
│   │   │   └── deps.py                # get_current_user dependency
│   │   └── utils/
│   │       ├── encryption.py          # encrypt() / decrypt() via Fernet
│   │       ├── logger.py              # loguru setup — always import from here
│   │       ├── exceptions.py          # AppException subclasses + FastAPI handlers
│   │       └── response.py            # success_response() / error_response()
│   ├── alembic/                       # DB migrations
│   │   ├── env.py                     # async Alembic config (imports app.models for autogenerate)
│   │   ├── script.py.mako             # migration template (includes `import sqlmodel`)
│   │   └── versions/                  # generated migration files
│   ├── scraper/
│   │   ├── platforms/
│   │   │   ├── blinkit/
│   │   │   │   ├── selectors.py       # ALL CSS selectors and URL paths — change platform UI here only
│   │   │   │   ├── auth.py            # login flow → returns and saves session to DB
│   │   │   │   ├── dashboard_data/
│   │   │   │   │   ├── marketing/     # scraper.py, parser.py, storage.py
│   │   │   │   │   └── seller/        # scraper.py, parser.py, storage.py
│   │   │   │   └── public_data/       # endpoints.py, scraper.py (one session, lat/lon swap), parser.py, storage.py (search_*), sku_storage.py (sku_snapshots)
│   │   │   ├── instamart/             # public_data/ — OUT OF SCOPE (Blinkit-only)
│   │   │   └── zepto/                 # public_data/ — OUT OF SCOPE (Blinkit-only)
│   │   ├── public/                    # orchestrator.py (keyword scrape) + targeted.py (own-SKU scrape) — watchlist + tenant_locations → per-tenant, worker pool
│   │   └── utils/
│   │       ├── browser.py             # create_browser_context(), write_blocker(), PLAYWRIGHT_ARGS
│   │       ├── cities.py              # LEGACY hardcoded cities — being retired (public scraper reads DB)
│   │       ├── search_result.py       # classify_products(), slugify(), discount_pct(), brand_in()
│   │       ├── session.py             # save_session(), load_session() → platform_sessions table
│   │       ├── storage.py             # ensure_refs() — auto-upserts brands + marketplaces
│   │       ├── jobs.py                # create_scrape_job(), complete_scrape_job(), fail_scrape_job()
│   │       └── retry.py               # @retry decorator with exponential backoff
│   └── cli/
│       ├── main.py                    # typer app entry point: python -m cli
│       └── commands/
│           ├── tenant.py              # cli tenant create / list
│           ├── auth.py                # cli auth blinkit / blinkit-seller / status
│           ├── sync.py                # cli sync — config.xlsx → DB (locations/brands/coverage)
│           ├── locations.py           # cli locations list
│           ├── watchlist.py           # cli watchlist list
│           └── scrape.py              # cli scrape blinkit / ... / public / public-run
├── frontend/                          # React + Vite (skeleton)
└── docs/                              # This documentation
```

---

## Data Flow

```
[CLI command]
     │
     ├── public keyword scrape ─► scraper/public/orchestrator.py (watchlist + tenant_locations)
     │                          │  one Blinkit browser, N context-workers, lat/lon header-swap per store
     │                          │  blinkit/public_data: scraper.py → parser.py (classify own+competitors)
     │                     storage.py  ensure_refs() → append search_snapshots + search_listings
     │
     ├── public own-SKU scrape ─► scraper/public/targeted.py (brand query, own-only)
     │                          │  same worker pool; paginates the brand's whole catalog
     │                     sku_storage.py → append sku_snapshots (keyed on product_id)
     │
     └── private scrape ─► platforms/blinkit/{dashboard}/scraper.py
                                │  Playwright session restored from platform_sessions
                                │  intercepts auth headers → httpx / in-page API calls
                           parser.py  cleans raw strings → typed values
                           storage.py  upserts by upsert_key → platform-specific tables
                                │
                                ▼
                          [PostgreSQL — Supabase]
                                │
                                ▼
                          FastAPI routes (when frontend is wired up)
                                │
                                ▼
                          React dashboard
```

---

## Database Schema

**Connection**: Always use the Supabase Session Pooler URL. The direct connection URL is IPv6-only and will not work in most environments.

### Reference tables (no tenant scope)

| Table | Key columns | Notes |
|---|---|---|
| `brands` | `slug` (PK), `name`, `category` | Auto-upserted by `ensure_refs()` — no manual seeding |
| `marketplaces` | `slug` (PK), `name`, `color` | Auto-upserted by `ensure_refs()` — no manual seeding |

### Tenant tables

| Table | Key columns | Notes |
|---|---|---|
| `tenants` | `id` (UUID PK), `name`, `is_active` | Create with `cli tenant create` |
| `users` | `id`, `tenant_id`, `email`, `hashed_password` | FK to tenants |
| `tenant_watchlist` | `tenant_id`, `brand_slug`, `relationship`, `keywords`, `aliases`, `keyword_cap`, `brand_cap` | Brands + keywords per tenant; the two caps (own rows) tune the keyword vs brand scrape. `cities`/`marketplaces` are legacy — use `tenant_locations` |
| `platform_sessions` | `tenant_id`, `platform`, `encrypted_session` | Fernet-encrypted Playwright sessions |
| `scrape_jobs` | `id`, `tenant_id`, `platform`, `dashboard`, `status` | Audit log for every scrape run |

### Public search tables (per-tenant)

| Table | Key columns | Notes |
|---|---|---|
| `search_snapshots` | `tenant_id`, `job_id`, `brand_slug`, `mp_slug`, `keyword`, `city`, `pincode`, `lat`/`lon`, `brand_rank`, `brand_sov`, `total_results` | **keyword scrape header** — one row per (tenant, keyword, location, scrape) |
| `search_listings` | `snapshot_id`, `tenant_id`, `mp_slug`, `brand_slug`, `is_brand`, `is_combo`, `position`, `price`, `mrp`, `discount_pct`, `in_stock`, `inventory`, `extra` | **keyword scrape detail** — one row per product in the result page (lat/lon via `snapshot_id → search_snapshots`) |
| `sku_snapshots` | `tenant_id`, `job_id`, `brand_slug`, `platform_product_id` (key), `product_name`, `is_combo`, `merchant_id`, `city`, `lat`/`lon`, `price`, `mrp`, `discount_pct`, `in_stock`, `inventory`, `rating` | **targeted own-SKU scrape** — one flat row per (own product × location × scrape) |
| `sku_map` | `tenant_id`, `item_id`, `platform_product_id`, `product_name`, `match_method` | bridges private `item_id` ↔ public `platform_product_id` (name-matched; `cli sku-map`) |
| `marketplace_locations` | `mp_slug`, `merchant_id` (key), `city`, `state`, `region`, `lat`/`lon` | shared darkstore catalog (from `config.xlsx`) |
| `tenant_locations` | `tenant_id`, `mp_slug`, `location_id` | which catalog locations a tenant scrapes |
| `inventory_depth` | `tenant_id`, `brand_slug`, `mp_slug`, `sku`, `city` | old deep per-SKU stock probe — superseded by `sku_snapshots`, no write path |

Append-only (no upsert). `search_*` written by `cli scrape public-run`;
`sku_snapshots` by `cli scrape public-skus` — both via orchestrators under
`scraper/public/`.

**The unit is the serviceable location `(lat, lon)`, not the store.** The catalog
lat/long is a delivery point (several dark stores can share one; the search API
resolves a coordinate to one serving store), so **all public read metrics count
distinct `(lat,lon)`, never `merchant_id`/rows** — see
[docs/public-glossary.md](public-glossary.md) (Reach vs Distribution). `is_combo`
separates combos/multipacks from main SKUs (`?kind=main|combo|all`). The old
`search_results`/`competitor_rankings`/`brand_snapshots`/`scraped_products` tables
were dropped in migration `f3a9c1d7b2e5`.

### Blinkit marketing tables (tenant-scoped)

| Table | Key columns | Granularity |
|---|---|---|
| `blinkit_ad_campaign_daily` | `tenant_id`, `campaign_id`, `date`, `budget_consumed`, `impressions`, `atc`, `quantities_sold`, `ad_sales`, `roas` | per campaign × **day** (metric backbone; account totals = sum of these) |
| `blinkit_ad_campaigns` | `tenant_id`, `campaign_id`, `name`, `type`, `status` | campaign metadata snapshot |
| `blinkit_ad_campaign_detail` | `tenant_id`, `campaign_id`, `target_type`, `target`, `sub_campaign_id`, `match_type`, `budget_consumed`, `direct_roas`, `total_roas`, `snapshot_date` | per keyword/asset, window-aggregate snapshot |
| `blinkit_sponsored_sov` | `tenant_id`, `keyword`, `date`, `sov` | snapshot |
| `blinkit_brand_collections` | `tenant_id`, `collection_id`, `name`, `number_of_products` | snapshot |
| `blinkit_visibility_plans` | `tenant_id`, `plan_id`, `name`, `budget`, `status` | snapshot |

> RoAS is always recomputed over a window as `Σ ad_sales ÷ Σ budget_consumed` from
> `blinkit_ad_campaign_daily` — never by averaging the daily `roas`. There is no
> separate ad-performance-summary table; daily totals and budget-split-by-type are
> derived by summing the daily backbone (it carries `campaign_type`).

### Blinkit seller tables (tenant-scoped)

| Table | Key columns |
|---|---|
| `blinkit_seller_sales` | `tenant_id`, `date`, `item_id`, `city_id`, `qty_sold` |
| `blinkit_seller_sales_summary` | `tenant_id`, `date`, `distinct_skus`, `max_sell_item` |
| `blinkit_pos` | `tenant_id`, `po_number`, `raw` (full JSON) |
| `blinkit_po_snapshots` | `tenant_id`, `window_start`, `raw` (rolling 90-day summary) |
| `blinkit_soh` | `tenant_id`, `date`, `item_id`, `backend_facility_id`, `backend_inv_qty` |
| `blinkit_scorecard_weekly` | `tenant_id`, `from_date_ist`, `overall`, `categories` |
| `blinkit_scorecard_facilities` | `tenant_id`, `from_date_ist`, `facility_id`, `fill_rate` |
| `blinkit_scorecard_key_skus` | `tenant_id`, `from_date_ist`, `item_id`, `potential_loss` |

### Upsert key convention

Every private data table has a `upsert_key: str` with a unique constraint. All writes use:

```python
INSERT INTO ... ON CONFLICT (upsert_key) DO UPDATE SET ...
```

Re-running the same scrape updates existing rows rather than creating duplicates.

---

## Public Scraper — How It Works

### Config & locations (DB-driven)

The darkstore catalog, per-tenant keywords, and coverage live in `config.xlsx` and
are synced to the DB by `cli sync` (`marketplace_locations`, `tenant_watchlist`,
`tenant_locations`). `scraper/utils/cities.py` is **legacy and being retired** — the
scraper reads locations from the DB, not from it. Blinkit selects the dark store
from the **lat/lon** in the request headers; `pincode`/`zone` are metadata only.
`marketplace_locations` is keyed on `merchant_id`.

### Why direct HTTP doesn't work (Cloudflare)

Blinkit's search API (`/v1/layout/search`) is behind Cloudflare. Direct `httpx`
returns 403 even with the browser's cookies — Python's TLS fingerprint differs from
a real browser (verified 403 on both http/1.1 and http/2). So every fetch goes
through an in-page `page.evaluate(fetch(...))` in a real Playwright session.

### One session, reused across all stores (the speed win)

`open_session()` pays the browser warmup **once** — homepage + a warmup search whose
request is intercepted (`page.on("request")`) to capture the session-bound headers
(`auth_key`, `session_uuid`, `device_id`, `lat`, `lon`, `access_token`, …). Then
every store is just a **lat/lon header swap** on the in-page POST — Blinkit returns
that store's catalog in ~0.4s, no per-store relaunch. The API pages **12 products at
a time** (server-capped, ignores higher `limit`), so `search()` follows Blinkit's
`next_url` up to `RESULT_CAP`, stopping when results switch from `basic` to
`similarity`. Extraction reads the typed `atc_action.cart_item` (brand, price, mrp,
inventory, product_id) + `tracking.common_attributes` (position, category, rating,
state).

### Two scrapes, orchestration & resilience

Both scrapes share the same engine (session, in-page fetch, pagination) and a
concurrent **worker pool**: one browser, N isolated contexts each with its own DB
session, pulling stores off a shared queue (`--workers`, default 5). They differ in
query, cap, classification, and storage target:

- **Keyword scrape** — `scraper/public/orchestrator.py`. Category keywords ×
  stores → SoV/rank + declared competitors (`keyword_cap`, default 12), classifying
  each result against the own brand via the API's explicit `brand` field. Writes
  `search_snapshots` + `search_listings`.
- **Targeted own-SKU scrape** — `scraper/public/targeted.py`. Searches the tenant's
  **brand name**, paginates the whole catalog (`brand_cap`, default 60), own-brand
  only. Writes the flat `sku_snapshots` (keyed on `platform_product_id`) —
  guaranteeing coverage of every own SKU regardless of keyword ranking.

One `scrape_job` per run (dashboards `public_search` / `public_skus`). Resilience:
per-fetch retry with backoff, a hard per-fetch timeout (a stalled fetch can't hang a
worker), non-JSON/Cloudflare detection surfaced with the real HTTP status, session
refresh on staleness, incremental commits, `--resume` to continue an interrupted job,
and — after the main pass — **one automatic retry pass** over locations that errored
and returned nothing (fresh sessions recover transient blips; no duplicate rows since
those locations wrote nothing the first time).

Reference: `backend/scraper/platforms/blinkit/public_data/{scraper,storage,sku_storage}.py`
+ `backend/scraper/public/{orchestrator,targeted}.py`. httpx is not usable here (Cloudflare).

---

## Private Scraper — How It Works

### Blinkit marketing — magic link auth

```
1. cli auth blinkit --tenant <uuid>
2. Browser opens (headless=False), navigates to brands.blinkit.com
3. User enters email → receives magic link by email
4. User pastes magic link URL into terminal
5. Browser navigates to magic link, waits for session on /diy/
6. Three-layer session captured: cookies + localStorage + Firebase IndexedDB
7. Encrypted with Fernet → saved to platform_sessions table
```

### Blinkit seller — OTP auth

```
1. cli auth blinkit-seller --tenant <uuid>
2. Browser opens, navigates to partnersbiz.com
3. User enters email → receives 6-digit OTP by email
4. User enters OTP into terminal
5. Session captured and stored (same three-layer approach)
```

### Session restore — critical ordering

When restoring a saved session for scraping, these three steps must happen in this exact order:

```python
ctx = await browser.new_context(storage_state=state)           # 1. cookies + localStorage
await ctx.add_init_script(firebase_idb_inject(session_data))   # 2. Firebase IndexedDB injection
await ctx.route("**/*", write_blocker)                         # 3. block write requests
```

Step 2 must run before any page JavaScript executes. Firebase JS SDK v9+ stores the refresh token in IndexedDB, not localStorage. Without pre-populating IndexedDB at init time, Firebase treats the session as expired even though cookies are valid.

---

## Adding a New Platform

### Public scraper (a new marketplace)

Instamart/Zepto are currently **out of scope** (Blinkit-only). If a marketplace is
added later, mirror the Blinkit public path:

```
scraper/platforms/{platform}/public_data/
├── endpoints.py  — URLs, header keys, request body, RESULT_CAP
├── scraper.py    — open_session()/search() — reuse one session across stores (lat/lon swap)
├── parser.py     — classify_products() → snapshot header + listing rows
└── storage.py    — save(session, result, tenant_id, job_id) → search_snapshots + search_listings
```

Then dispatch to it from `scraper/public/orchestrator.py` (platform-agnostic above
the platform layer). Locations come from `marketplace_locations`/`tenant_locations`
(via `cli sync`), not `cities.py`. Check whether the platform's API blocks direct
httpx — if so, use the in-page fetch technique (as Blinkit does).

### Private scraper (Instamart, Zepto seller dashboards)

```
scraper/platforms/{platform}/
├── auth.py              — login flow → captures and saves session
└── dashboard_data/
    └── {dashboard}/
        ├── scraper.py   — fetch raw data using restored session
        ├── parser.py    — raw strings → typed Python values
        └── storage.py   — upsert to platform-specific tables
```

Then add the new `cli scrape` subcommand in `cli/commands/scrape.py`.
