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

Consumer-facing search scraped across 20+ Indian cities, with 6–12 zones per city.

| Platform | Status |
|---|---|
| Blinkit | Working (Playwright in-page fetch — Cloudflare bypass) |
| Instamart | Pending — needs the same Playwright fix as Blinkit |
| Zepto | Pending |

### Private data — requires seller login

| Platform | Dashboard | Status |
|---|---|---|
| Blinkit | Marketing (`brands.blinkit.com`) | Working |
| Blinkit | Seller (`partnersbiz.com`) — sales, PO, SOH, scorecard | Working |
| Instamart | TBD | Pending |
| Zepto | TBD | Pending |

## What Data Is Collected

### Public search (all platforms)
- Brand rank (best position in search results)
- Share of voice % (brand products ÷ total products)
- Top 8 competitors with product counts
- Brand product list with prices and stock status

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
