# Architecture

## Directory Layout

There are **four top-level Python packages** under `backend/`, each a peer:
`app/` (the API + shared application core), `cli/` (terminal entry point),
`scraper/` (the browser work), `jobs/` (the job/runner/scheduler subsystem), plus
`ad_campaigns/` (the coworker-owned campaign manager). `app/` is **not** API-only â€”
it holds the shared core (`core/`, `models/`, `utils/`, `services/`) that every
entry point imports, alongside the API layer (`routes/`, `router.py`, `schemas/`).

```
automation-mvp/
â”œâ”€â”€ backend/
â”‚   â”œâ”€â”€ app/                           # API layer + SHARED application core (imported by cli/, scraper/, jobs/)
â”‚   â”‚   â”œâ”€â”€ main.py                    # FastAPI app + lifespan (in-API APScheduler for the campaign manager)
â”‚   â”‚   â”œâ”€â”€ router.py                  # aggregates all routers under /api
â”‚   â”‚   â”œâ”€â”€ dependencies.py            # get_current_user, ClientDep, SessionDep, require_admin
â”‚   â”‚   â”œâ”€â”€ core/
â”‚   â”‚   â”‚   â”œâ”€â”€ config.py              # Pydantic Settings â€” loads .env; BASE_DIR, LOG_DIR, LANE_SLOTS, DB_POOL_SIZE
â”‚   â”‚   â”‚   â”œâ”€â”€ database.py            # engine (pool_size=DB_POOL_SIZE), AsyncSessionLocal, get_session()
â”‚   â”‚   â”‚   â””â”€â”€ security.py            # JWT encode/decode, password hashing
â”‚   â”‚   â”œâ”€â”€ models/                    # SQLModel table classes â€” source of truth for schema (Alembic autogens from here)
â”‚   â”‚   â”‚   â”œâ”€â”€ account.py             # Account
â”‚   â”‚   â”‚   â”œâ”€â”€ tenant.py              # Tenant, User, TenantWatchlist
â”‚   â”‚   â”‚   â”œâ”€â”€ job.py                 # ScrapeJob, PlatformSession, Job (queue row), Lane
â”‚   â”‚   â”‚   â”œâ”€â”€ search.py              # SearchSnapshot, SearchListing, SkuSnapshot, SkuMap, MarketplaceLocation, TenantLocation, InventoryDepth
â”‚   â”‚   â”‚   â”œâ”€â”€ blinkit_seller.py      # BlinkitSellerSale, BlinkitPO, BlinkitSOH, BlinkitScorecard*
â”‚   â”‚   â”‚   â”œâ”€â”€ blinkit_marketing.py   # BlinkitAdCampaign(Daily/Detail), SponsoredSOV, BrandCollection, VisibilityPlan
â”‚   â”‚   â”‚   â”œâ”€â”€ campaign_manager.py    # BudgetSchedule*, BidOptimizer* (coworker)
â”‚   â”‚   â”‚   â””â”€â”€ explorer.py            # ExplorerRun
â”‚   â”‚   â”œâ”€â”€ routes/                    # FastAPI route handlers (thin â€” call services)
â”‚   â”‚   â”œâ”€â”€ services/                  # SHARED business logic â€” called by BOTH routes and CLI commands
â”‚   â”‚   â”‚   â”œâ”€â”€ ads_service.py         # marketing + campaign-manager orchestration (coworker-adjacent)
â”‚   â”‚   â”‚   â”œâ”€â”€ job_service.py         # reads the scrape_jobs audit table (NOT the jobs queue â€” that's jobs/)
â”‚   â”‚   â”‚   â”œâ”€â”€ sku_map_service.py     # CLI-only service (imported by cli/commands/sku_map.py)
â”‚   â”‚   â”‚   â””â”€â”€ â€¦ (analytics, auth, client, competition, inventory, overview, â€¦)
â”‚   â”‚   â”œâ”€â”€ schemas/                   # Pydantic request/response models for the API
â”‚   â”‚   â””â”€â”€ utils/
â”‚   â”‚       â”œâ”€â”€ logger.py              # loguru setup (absolute LOG_DIR) â€” always import from here
â”‚   â”‚       â”œâ”€â”€ time.py               # now_ist() â€” naive IST wall-clock, used everywhere
â”‚   â”‚       â”œâ”€â”€ encryption.py          # encrypt() / decrypt() via Fernet
â”‚   â”‚       â””â”€â”€ exceptions.py          # AppException subclasses + FastAPI handlers
â”‚   â”œâ”€â”€ jobs/                          # â† job/runner/scheduler subsystem (see docs/jobs.md)
â”‚   â”‚   â”œâ”€â”€ queue.py                   # jobs-queue DB ops: enqueue, atomic claim (SKIP LOCKED), complete, reap_stale
â”‚   â”‚   â”œâ”€â”€ types.py                   # job-type registry: type â†’ lane, timeout, argv builder (the one extension point)
â”‚   â”‚   â”œâ”€â”€ runner.py                  # runner daemon: producer + consumer (per-lane claim, subprocess dispatch, per-run logs, RSS, reaper)
â”‚   â”‚   â”œâ”€â”€ scheduler.py               # cron producer: reads job_schedules, enqueues when due (catchup/misfire logic)
â”‚   â”‚   â”œâ”€â”€ monitor.py                 # deadman/heartbeat: last-success-per-schedule + disk check â†’ ERROR logs
â”‚   â”‚   â””â”€â”€ maintenance.py             # prune_logs() â€” the maint.log_cleanup job
â”‚   â”œâ”€â”€ ad_campaigns/                  # coworker-owned campaign manager (budget scheduler + bid optimizer) â€” OFF-LIMITS
â”‚   â”œâ”€â”€ alembic/                       # DB migrations (env.py imports app.models for autogenerate)
â”‚   â”œâ”€â”€ scraper/
â”‚   â”‚   â”œâ”€â”€ platforms/
â”‚   â”‚   â”‚   â”œâ”€â”€ blinkit/
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ selectors.py       # ALL CSS selectors and URL paths â€” change platform UI here only
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ auth.py            # login flow â†’ returns and saves session to DB
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ dashboard_data/
â”‚   â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ marketing/     # scraper.py, parser.py, storage.py
â”‚   â”‚   â”‚   â”‚   â”‚   â””â”€â”€ seller/        # scraper.py, parser.py, storage.py
â”‚   â”‚   â”‚   â”‚   â””â”€â”€ public_data/       # endpoints.py, scraper.py (one session, lat/lon swap), parser.py, storage.py, sku_storage.py
â”‚   â”‚   â”‚   â”œâ”€â”€ instamart/             # public_data/ â€” stub, NOT wired (old one-shot interface)
â”‚   â”‚   â”‚   â””â”€â”€ zepto/                 # public_data/ â€” dead stub; see docs/zepto.md (planned)
â”‚   â”‚   â”œâ”€â”€ public/                    # MARKETPLACE-AGNOSTIC scrape engine â€” nothing here imports a platform
â”‚   â”‚   â”‚   â”œâ”€â”€ providers.py           # marketplace registry: slug â†’ open_session/search/close_session/parse + cap floors
â”‚   â”‚   â”‚   â”œâ”€â”€ orchestrator.py        # keyword scrape (worker pool), mp_slug-parameterised
â”‚   â”‚   â”‚   â”œâ”€â”€ targeted.py            # own-SKU brand scrape, same pool
â”‚   â”‚   â”‚   â”œâ”€â”€ staging.py             # local SQLite per run (mp_slug column + filename segment)
â”‚   â”‚   â”‚   â”œâ”€â”€ loader.py              # staging â†’ Postgres, one all-or-nothing COPY transaction
â”‚   â”‚   â”‚   â””â”€â”€ explorer/              # ad-hoc scrape â†’ Excel (re-exports providers.py)
â”‚   â”‚   â””â”€â”€ utils/
â”‚   â”‚       â”œâ”€â”€ browser.py             # create_browser_context(), write_blocker(), PLAYWRIGHT_ARGS
â”‚   â”‚       â”œâ”€â”€ session.py             # save_session(), load_session() â†’ platform_sessions table
â”‚   â”‚       â”œâ”€â”€ storage.py             # ensure_refs() â€” auto-upserts brands + marketplaces
â”‚   â”‚       â”œâ”€â”€ jobs.py                # create_scrape_job()/complete/fail â†’ the scrape_jobs AUDIT table (not the jobs/ queue)
â”‚   â”‚       â””â”€â”€ retry.py               # @retry decorator with exponential backoff
â”‚   â””â”€â”€ cli/
â”‚       â”œâ”€â”€ main.py                    # typer app entry point: python -m cli
â”‚       â””â”€â”€ commands/                  # thin wrappers â€” account, auth, tenant, sync, locations, watchlist,
â”‚           â”‚                          #   scrape, sku_map, explore, jobs, runner
â”‚           â”œâ”€â”€ scrape.py              # cli scrape blinkit / seller / scorecard / public-run / public-skus
â”‚           â”œâ”€â”€ jobs.py                # cli jobs types / run / list / logs   â†’ imports jobs/
â”‚           â””â”€â”€ runner.py             # cli runner start                     â†’ imports jobs/
â”œâ”€â”€ frontend/                          # React + Vite
â””â”€â”€ docs/                              # This documentation
```

> **Naming caution:** "job" and "scheduler" each name two unrelated things.
> `scraper/utils/jobs.py` + `scrape_jobs` table = a scrape's *internal* progress
> (drives `--resume`); `jobs/` + the `jobs` table = the *work-order queue*, which
> links to the former via `ref_job_id`. And `ad_campaigns/scheduler.py` (coworker,
> ad-budget timing) is unrelated to `jobs/scheduler.py` (infra cron). See docs/jobs.md.

---

## Data Flow

Every scrape below is triggered one of two ways, both ending in the **same CLI
command**: you run it by hand, **or** the `jobs/` runner claims a queued job and
spawns that exact `python -m cli â€¦` as a subprocess (scheduled or UI-triggered).
The runner is a thin dispatch layer above this diagram â€” see docs/jobs.md.

```
[CLI command  |  jobs/ runner â†’ subprocess]
     â”‚
     â”œâ”€â”€ public keyword scrape â”€â–º scraper/public/orchestrator.py (watchlist + tenant_locations)
     â”‚                          â”‚  one Blinkit browser, N context-workers, lat/lon header-swap per store
     â”‚                          â”‚  blinkit/public_data: scraper.py â†’ parser.py (classify own+competitors)
     â”‚                     storage.py  ensure_refs() â†’ append search_snapshots + search_listings
     â”‚
     â”œâ”€â”€ public own-SKU scrape â”€â–º scraper/public/targeted.py (brand query, own-only)
     â”‚                          â”‚  same worker pool; paginates the brand's whole catalog
     â”‚                     sku_storage.py â†’ append sku_snapshots (keyed on product_id)
     â”‚
     â”œâ”€â”€ explorer custom scrape â”€â–º scraper/public/explorer/ (ad-hoc ExplorerSpec, NO watchlist/tenant)
     â”‚                          â”‚  same worker pool; keywords/brand Ã— SAMPLED catalog locations
     â”‚                     in-memory â†’ insights.py â†’ export.py (.xlsx); only explorer_runs persisted
     â”‚
     â””â”€â”€ private scrape â”€â–º platforms/blinkit/{dashboard}/scraper.py
                                â”‚  Playwright session restored from platform_sessions
                                â”‚  intercepts auth headers â†’ httpx / in-page API calls
                           parser.py  cleans raw strings â†’ typed values
                           storage.py  upserts by upsert_key â†’ platform-specific tables
                                â”‚
                                â–¼
                          [PostgreSQL â€” Supabase]
                                â”‚
                                â–¼
                          FastAPI routes (when frontend is wired up)
                                â”‚
                                â–¼
                          React dashboard
```

---

## Database Schema

**Connection**: Always use the Supabase Session Pooler URL. The direct connection URL is IPv6-only and will not work in most environments.

### Reference tables (no tenant scope)

| Table | Key columns | Notes |
|---|---|---|
| `brands` | `slug` (PK), `name`, `category` | Auto-upserted by `ensure_refs()` â€” no manual seeding |
| `marketplaces` | `slug` (PK), `name`, `color` | Auto-upserted by `ensure_refs()` â€” no manual seeding |

### Tenant tables

| Table | Key columns | Notes |
|---|---|---|
| `tenants` | `id` (UUID PK), `name`, `is_active` | Create with `cli tenant create` |
| `users` | `id`, `tenant_id`, `email`, `hashed_password` | FK to tenants |
| `tenant_watchlist` | `tenant_id`, `brand_slug`, `relationship`, `keywords`, `aliases`, `keyword_cap`, `brand_cap` | Brands + keywords per tenant; the two caps (own rows) tune the keyword vs brand scrape. `cities`/`marketplaces` are legacy â€” use `tenant_locations` |
| `platform_sessions` | `tenant_id`, `platform`, `encrypted_session` | Fernet-encrypted Playwright sessions |
| `scrape_jobs` | `id`, `tenant_id`, `platform`, `dashboard`, `status` | Audit log for every scrape run |

### Public search tables (per-tenant)

| Table | Key columns | Notes |
|---|---|---|
| `search_snapshots` | `tenant_id`, `job_id`, `brand_slug`, `mp_slug`, `keyword`, `city`, `pincode`, `lat`/`lon`, `brand_rank`, `brand_sov`, `total_results` | **keyword scrape header** â€” one row per (tenant, keyword, location, scrape) |
| `search_listings` | `snapshot_id`, `tenant_id`, `mp_slug`, `brand_slug`, `is_brand`, `is_combo`, `position`, `price`, `mrp`, `discount_pct`, `in_stock`, `inventory`, `extra` | **keyword scrape detail** â€” one row per product in the result page (lat/lon via `snapshot_id â†’ search_snapshots`) |
| `sku_snapshots` | `tenant_id`, `job_id`, `brand_slug`, `platform_product_id` (key), `product_name`, `is_combo`, `merchant_id`, `city`, `lat`/`lon`, `price`, `mrp`, `discount_pct`, `in_stock`, `inventory`, `rating` | **targeted own-SKU scrape** â€” one flat row per (own product Ã— location Ã— scrape) |
| `sku_map` | `tenant_id`, `item_id`, `platform_product_id`, `product_name`, `match_method` | bridges private `item_id` â†” public `platform_product_id` (name-matched; `cli sku-map`) |
| `marketplace_locations` | `mp_slug`, `merchant_id` (key), `city`, `state`, `region`, `lat`/`lon` | shared darkstore catalog (from `config.xlsx`) |
| `tenant_locations` | `tenant_id`, `mp_slug`, `location_id` | which catalog locations a tenant scrapes |
| `inventory_depth` | `tenant_id`, `brand_slug`, `mp_slug`, `sku`, `city` | old deep per-SKU stock probe â€” superseded by `sku_snapshots`, no write path |

Append-only (no upsert). `search_*` and `sku_snapshots` are written by
`cli scrape load`, **not** by the scrapes themselves â€” `public-run` / `public-skus`
write to a local SQLite staging file and the load pushes it in one transaction. See
[staging.md](staging.md).

**The unit is the STORE (`merchant_id`); the coordinate is only the probe.** Every
product in a response carries the store that fulfils it and the tier it is sold under
(`merchant_type`), read **per product** â€” one response can span several stores, and
one store can answer several coordinates. So public read metrics should
`COUNT(DISTINCT merchant_id)` and take one row per `(store, product)`.

> âš ï¸ **Superseded 2026-07-18.** This section previously stated the unit was the
> serviceable location `(lat,lon)` "not the store", on the belief that we could not
> tell which store answered. We can â€” exactly, on every product. See
> [darkstores.md](darkstores.md) for the evidence.
> **The read services still aggregate by `(lat,lon)` and have not been migrated**
> (`competition_service`, `inventory_service`, `product_service`).

`is_combo` separates combos/multipacks from main SKUs (`?kind=main|combo|all`). The
old `search_results`/`competitor_rankings`/`brand_snapshots`/`scraped_products`
tables were dropped in migration `f3a9c1d7b2e5`.

### Blinkit marketing tables (tenant-scoped)

| Table | Key columns | Granularity |
|---|---|---|
| `blinkit_ad_campaign_daily` | `tenant_id`, `campaign_id`, `date`, `budget_consumed`, `impressions`, `atc`, `quantities_sold`, `ad_sales`, `roas` | per campaign Ã— **day** (metric backbone; account totals = sum of these) |
| `blinkit_ad_campaigns` | `tenant_id`, `campaign_id`, `name`, `type`, `status` | campaign metadata snapshot |
| `blinkit_ad_campaign_detail` | `tenant_id`, `campaign_id`, `target_type`, `target`, `sub_campaign_id`, `match_type`, `budget_consumed`, `direct_roas`, `total_roas`, `snapshot_date` | per keyword/asset, window-aggregate snapshot |
| `blinkit_sponsored_sov` | `tenant_id`, `keyword`, `date`, `sov` | snapshot |
| `blinkit_brand_collections` | `tenant_id`, `collection_id`, `name`, `number_of_products` | snapshot |
| `blinkit_visibility_plans` | `tenant_id`, `plan_id`, `name`, `budget`, `status` | snapshot |

> RoAS is always recomputed over a window as `Î£ ad_sales Ã· Î£ budget_consumed` from
> `blinkit_ad_campaign_daily` â€” never by averaging the daily `roas`. There is no
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

## Public Scraper â€” How It Works

### Config & locations (DB-driven)

The darkstore catalog, per-tenant keywords, and coverage live in `config.xlsx` and
are synced to the DB by `cli sync` (`marketplace_locations`, `tenant_watchlist`,
`tenant_locations`). `scraper/utils/cities.py` is **legacy and being retired** â€” the
scraper reads locations from the DB, not from it. Blinkit selects the dark store
from the **lat/lon** in the request headers; `pincode`/`location_name`/`address` are
metadata only. `marketplace_locations` is keyed on `merchant_id` â€” one row per
**express** store, holding the coordinate to probe it at.

One coordinate resolves to **several** stores, not one: the express store plus any
longtail/super_longtail hubs serving it. Every product in the response names its own
store (`merchant_id`) and tier (`merchant_type`) â€” read them per product, never per
response. See [darkstores.md](darkstores.md).

### Why direct HTTP doesn't work (Cloudflare)

Blinkit's search API (`/v1/layout/search`) is behind Cloudflare. Direct `httpx`
returns 403 even with the browser's cookies â€” Python's TLS fingerprint differs from
a real browser (verified 403 on both http/1.1 and http/2). So every fetch goes
through an in-page `page.evaluate(fetch(...))` in a real Playwright session.

### One session, reused across all stores (the speed win)

`open_session()` pays the browser warmup **once** â€” homepage + a warmup search whose
request is intercepted (`page.on("request")`) to capture the session-bound headers
(`auth_key`, `session_uuid`, `device_id`, `lat`, `lon`, `access_token`, â€¦). Then
every store is just a **lat/lon header swap** on the in-page POST â€” Blinkit returns
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

- **Keyword scrape** â€” `scraper/public/orchestrator.py`. Category keywords Ã—
  stores â†’ SoV/rank + declared competitors (`keyword_cap`, default 12), classifying
  each result against the own brand via the API's explicit `brand` field. Writes
  `search_snapshots` + `search_listings`.
- **Targeted own-SKU scrape** â€” `scraper/public/targeted.py`. Searches the tenant's
  **brand name**, paginates the whole catalog (`brand_cap`, default 60), own-brand
  only. Writes the flat `sku_snapshots` (keyed on `platform_product_id`) â€”
  guaranteeing coverage of every own SKU regardless of keyword ranking.
- **Explorer (ad-hoc, ephemeral)** â€” `scraper/public/explorer/`. The same worker
  pool driven by an `ExplorerSpec` (any brand / keywords / cities, **no tenant or
  watchlist**), over *sampled* catalog locations. Accumulates in memory â†’
  `build_insights` â†’ an Excel workbook; writes **nothing** to the fact tables (only
  an `explorer_runs` record). Marketplace-abstracted via a provider registry. See
  [explorer.md](explorer.md).

One `scrape_job` per run (dashboards `public_search` / `public_skus`). Resilience:
retry with backoff on transient failures, a hard per-fetch timeout (a stalled fetch
can't hang a worker), non-JSON/Cloudflare detection surfaced with the real HTTP
status, session refresh on staleness, incremental commits, and `--resume` to
continue an interrupted job (skips already-scraped stores).

Reference: `backend/scraper/platforms/blinkit/public_data/{scraper,storage,sku_storage}.py`
+ `backend/scraper/public/{orchestrator,targeted}.py` + the ephemeral
`backend/scraper/public/explorer/` package. httpx is not usable here (Cloudflare).

---

## Private Scraper â€” How It Works

### Blinkit marketing â€” magic link auth

*Rewritten 2026-08-04: no browser is involved in logging in. See
[platform-auth.md](platform-auth.md).*

```
1. cli auth login blinkit --tenant <uuid>
2. POST brands.blinkit.com/adservice/v1/users/request-magic-link  (X-User-Email header)
3. Blinkit emails a SendGrid-wrapped Firebase action link
4. The auth inbox is polled over IMAP; the link is matched on recipient +
   arrival time + sender + subject, and the redirect resolved to get its oobCode
5. POST identitytoolkit accounts:signInWithEmailLink â†’ idToken + refreshToken
6. A three-layer storage_state is SYNTHESIZED from those tokens
   (cookies empty + localStorage + Firebase IndexedDB)
7. Encrypted with Fernet â†’ saved to platform_sessions
```

There is no backend session exchange â€” the Firebase ID token *is* the credential
(`firebase_user_token`). Cookies are deliberately empty: Chromium earns its own
Cloudflare cookies on first navigation.

### Blinkit seller â€” OTP auth

```
1. cli auth login blinkit_seller --tenant <uuid>
2. POST partnersbiz.com/auth/api/v1/email/send_otp     â†’ 6-digit code by email
3. The auth inbox is polled; the OTP is read from the message's VISIBLE text
   (raw HTML is full of six-digit hex colours)
4. POST .../email/verify_otp                           â†’ access + refresh token
5. GET  /v1/get-user-entities/                         â†’ the entity
6. Session stored: tokens + entity, plus a browser projection and ready API headers
```

The entity is **part of the credential** â€” `/v1/*` returns 403 without
`X-Entity-Id`/`X-Entity-Type`. The old "account selection screen" was pure client
state (`localStorage.myEntity`), so it is resolvable over HTTP.

Both platforms refresh indefinitely (`securetoken` / `tokens/rotate`), so a warm
session never needs a second secret. Consumers call `platform_auth.service.ensure()`
rather than loading a session directly, so expiry self-heals.

### Session restore â€” critical ordering

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

Everything under `scraper/public/` is **marketplace-agnostic** â€” the orchestrators,
staging, the loader and the Explorer all resolve the engine through
`scraper/public/providers.py`. Adding a marketplace means writing an engine and
registering it; you should not need to touch the shared path at all.

**1. Write the engine.** No `storage.py` â€” the public path stages through
`scraper/public/staging.py`.

```
scraper/platforms/{platform}/public_data/
â”œâ”€â”€ endpoints.py  â€” ALL URLs, header keys, request body, cap floors. Nothing inline elsewhere
â”œâ”€â”€ scraper.py    â€” open_context_session()/search()/close_session() â€” one session reused
â”‚                   across stores; raw extraction only
â”œâ”€â”€ parser.py     â€” classify_products() â†’ snapshot header + listing rows
â””â”€â”€ api.txt       â€” a captured response, verbatim (documentation, not code)
```

`search()` must return `{products, total_results, merchant_id, ok, error}`, with each
product using the shared key names (`product_id`, `name`, `brand`, `price`, `mrp`,
`unit`, `inventory`, `in_stock`, `rating`, `position`, `merchant_id`, `merchant_type`).
Translating the platform's own vocabulary happens **inside** the engine.

**2. Register it** in `scraper/public/providers.py` with `wired=True`. That is the
whole integration: `cli scrape public-run -m {platform}` starts working, as does the
Explorer and the `marketplace=` job param.

**3. Give it its own catalog.** Locations come from `marketplace_locations` /
`tenant_locations` via `cli sync` (`mp` column), never `cities.py` â€” and never
another platform's coordinates. A store's probe point is that platform's catchment.

Check whether the platform's API blocks direct httpx â€” if so, use the in-page fetch
technique (as Blinkit does). Worked example + open questions: [zepto-public.md](zepto-public.md).

### Private scraper (Instamart, Zepto seller dashboards)

```
scraper/platforms/{platform}/
â”œâ”€â”€ auth.py              â€” login flow â†’ captures and saves session
â””â”€â”€ dashboard_data/
    â””â”€â”€ {dashboard}/
        â”œâ”€â”€ scraper.py   â€” fetch raw data using restored session
        â”œâ”€â”€ parser.py    â€” raw strings â†’ typed Python values
        â””â”€â”€ storage.py   â€” upsert to platform-specific tables
```

Then add the new `cli scrape` subcommand in `cli/commands/scrape.py`.
