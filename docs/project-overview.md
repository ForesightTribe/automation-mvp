# Project Overview

Foresight is a multi-tenant marketing analytics platform for quick-commerce brands (Blinkit, Zepto, Instamart). It scrapes data from seller dashboards and consumer-facing search results, normalises it into a common PostgreSQL schema, and serves it through a REST API to a React dashboard.

## Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.12+, fully async/await |
| API | FastAPI + Uvicorn |
| Database | PostgreSQL via Supabase — SQLModel ORM, asyncpg driver, Alembic migrations |
| Browser automation | Playwright (Chromium) |
| Encryption | Fernet (`cryptography` library) — for storing platform sessions |
| Logging | loguru |
| CLI | typer + rich — current interface; FastAPI routes will call the same scraper functions when the frontend is ready |
| Frontend | React + Vite (skeleton only, not production-ready) |

## Multi-Tenant Design

Every piece of private data is scoped to a `tenant_id` UUID. A tenant represents one seller or brand using the platform. Each tenant has their own:

- Encrypted platform sessions
- Scraped dashboard data
- Watchlist configuration

Tenants never see each other's data. Public search data is not tenant-scoped — it reflects what any consumer would see.

## Platform Coverage

### Public data — no login required

Per-tenant and config-driven: a darkstore catalog of 2,000+ Blinkit stores, each
tenant's keywords/brands/coverage kept in `config.xlsx` and synced to the DB.
Scraped via Playwright in-page fetch (Cloudflare bypass), one session serving many
stores by lat/lon header-swap, run through a concurrent worker pool.

| Platform | Status |
|---|---|
| Blinkit | Working (Playwright in-page fetch — Cloudflare bypass) |
| Instamart | Out of scope (Blinkit-only) |
| Zepto | Out of scope (Blinkit-only) |

### Private data — requires seller login

| Platform | Dashboard | Status |
|---|---|---|
| Blinkit | Marketing (`brands.blinkit.com`) | Working |
| Blinkit | Seller (`partnersbiz.com`) — sales, PO, SOH, scorecard | Working |
| Instamart | TBD | Pending |
| Zepto | TBD | Pending |

## What Data Is Collected

### Public search (Blinkit) — two complementary scrapes

**Keyword scrape** (`public-run` → `search_snapshots` / `search_listings`) — the
competitive lens, per category keyword × store:
- Brand rank (best position in search results)
- Share of voice % (brand products ÷ total products)
- Declared competitors with prices, MRP, discount %, stock, position
- Total results for the keyword

**Targeted own-SKU scrape** (`public-skus` → `sku_snapshots`) — the own-inventory
lens, per own product × store, keyed on `product_id`; guarantees coverage of every
own SKU even when it doesn't rank in a keyword search:
- Price, MRP, discount %
- In-stock + inventory count
- Rating

### Blinkit marketing dashboard
- Ad performance summary (total spend, impressions)
- Per-campaign: name, type, budget, impressions, ATCs, RoAS
- Sponsored share-of-voice by keyword
- Brand collections (static/dynamic product groupings)
- Visibility plans (paid slot bookings)

### Blinkit seller dashboard
- Daily sales per SKU per city (qty, MRP value)
- Purchase orders with line items
- Stock-on-hand per SKU per facility
- Weekly scorecard: fill rates, potential loss, key SKUs
