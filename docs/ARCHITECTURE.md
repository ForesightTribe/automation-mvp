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
│   │   │   ├── search.py              # SearchResult, CompetitorRanking, BrandSnapshot, ScrapedProduct, InventoryDepth
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
│   │   │   │   └── public_data/       # scraper.py, parser.py, storage.py
│   │   │   ├── instamart/
│   │   │   │   └── public_data/       # scraper.py, parser.py, storage.py (pending Playwright fix)
│   │   │   └── zepto/
│   │   │       └── public_data/       # scraper.py, parser.py, storage.py (pending)
│   │   └── utils/
│   │       ├── browser.py             # create_browser_context(), write_blocker(), PLAYWRIGHT_ARGS
│   │       ├── cities.py              # CITIES dict — 20+ Indian cities with zones (lat/lon/pincode)
│   │       ├── search_result.py       # build_result(), norm_price(), brand_in(), dig()
│   │       ├── session.py             # save_session(), load_session() → platform_sessions table
│   │       ├── storage.py             # ensure_refs() — auto-upserts brands + marketplaces
│   │       ├── jobs.py                # create_scrape_job(), complete_scrape_job(), fail_scrape_job()
│   │       └── retry.py               # @retry decorator with exponential backoff
│   └── cli/
│       ├── main.py                    # typer app entry point: python -m cli
│       └── commands/
│           ├── tenant.py              # cli tenant create / list
│           ├── auth.py                # cli auth blinkit / blinkit-seller / status
│           └── scrape.py              # cli scrape blinkit / blinkit-seller / blinkit-scorecard / public
├── frontend/                          # React + Vite (skeleton)
└── docs/                              # This documentation
```

---

## Data Flow

```
[CLI command]
     │
     ├── public scrape ──► platforms/{platform}/public_data/scraper.py
     │                          │  Playwright in-page fetch (Blinkit)
     │                          │  or direct API (Zepto/Instamart — pending)
     │                     parser.py  normalises raw → typed dicts
     │                     storage.py  calls ensure_refs() → appends to search_results
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
| `tenant_watchlist` | `tenant_id`, `brand_slug`, `relationship`, `cities`, `keywords` | Brands to monitor per tenant |
| `platform_sessions` | `tenant_id`, `platform`, `encrypted_session` | Fernet-encrypted Playwright sessions |
| `scrape_jobs` | `id`, `tenant_id`, `platform`, `dashboard`, `status` | Audit log for every scrape run |

### Public search tables (scoped to brand + marketplace, not tenant)

| Table | Key columns | Notes |
|---|---|---|
| `search_results` | `brand_slug`, `mp_slug`, `city`, `zone`, `keyword` | One row per keyword × location × scrape run |
| `competitor_rankings` | `brand_slug`, `mp_slug`, `competitor`, `position` | Per-product competitor rows |
| `brand_snapshots` | `brand_slug`, `mp_slug`, `date`, `metrics` | Daily aggregate metrics per brand |
| `scraped_products` | `brand_slug`, `mp_slug`, `name`, `position`, `keyword` | Individual product appearances |
| `inventory_depth` | `brand_slug`, `mp_slug`, `sku`, `city`, `zone` | Stock depth per SKU per zone |

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

### Location data

`scraper/utils/cities.py` is a hardcoded dict of 20+ Indian cities. Each city has a default `lat`/`lon`/`pincode` plus named zones (dark-store service areas), each with their own coordinates. No external geocoding API is used.

```
bengaluru → default + zones: koramangala, indiranagar, whitefield, ...
mumbai    → default + zones: andheri, bandra, powai, ...
```

`--all-zones` scrapes every zone sequentially to capture location-specific ranking differences.

### Why direct HTTP doesn't work (Cloudflare)

Blinkit's search API (`/v1/layout/search`) is behind Cloudflare bot protection. Direct `httpx` requests always return 403 regardless of headers or cookies — Python's SSL library has a different TLS fingerprint from real browsers.

### The in-page fetch technique (Blinkit reference implementation)

Make the API call from *inside* the Playwright browser using `page.evaluate()`. Because the request originates from a real browser process with a Cloudflare-verified TLS fingerprint, session cookies, and bot-detection tokens, it passes through cleanly.

```
Step 1 — Set location context
   page.goto("https://blinkit.com/?lat={lat}&lon={lon}")
   Blinkit reads lat/lon from URL query params to determine the dark store.

Step 2 — Warmup search (header capture)
   page.goto("https://blinkit.com/s/?q=water")
   Triggers a real /v1/layout/search request from the browser.
   Intercepted via page.on("request") to capture session-bound headers:
   app_client, auth_key, session_uuid, device_id, web_app_version, etc.

Step 3 — In-page POST for actual keyword
   page.evaluate(fetch("/v1/layout/search", {headers: captured, body: {q: keyword}}))
   Runs inside the browser — Cloudflare treats it as a legitimate user action.
   Response format: response.snippets[] — snippets with atc_action are products.
```

Reference implementation: `backend/scraper/platforms/blinkit/public_data/scraper.py`

This is the established pattern for Cloudflare-protected endpoints. Check whether Instamart/Zepto also block direct requests before deciding httpx vs Playwright.

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

### Public scraper (Zepto, Instamart)

Create three files:

```
scraper/platforms/{platform}/public_data/
├── scraper.py   — async scrape(keyword, brand_slug, city_slug, ...) → dict
├── parser.py    — normalise raw API response → list of product dicts
└── storage.py   — save(session, result): call ensure_refs(), append SearchResult rows
```

Contract for `scraper.py`:

```python
async def scrape(
    keyword: str,
    brand_slug: str,
    city_slug: str = "bengaluru",
    zone: str = "",
    pincode: str = "",
    lat: float | None = None,
    lon: float | None = None,
    aliases: list[str] | None = None,
) -> dict:
    # returns: {platform, keyword, brand_slug, city, zone, pincode, lat, lon, aliases, products}
```

Use the Blinkit implementation as reference. Test whether the platform's API blocks direct requests — if yes, use the in-page fetch technique.

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
