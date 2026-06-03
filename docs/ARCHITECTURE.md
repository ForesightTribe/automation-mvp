# Architecture Guide

## Overview

Foresight is a unified seller intelligence platform for quick-commerce (Blinkit, Zepto, Instamart).
It scrapes seller dashboards, normalizes the data into a common format, stores it in MongoDB,
and serves it through a REST API to a React frontend.

```
automation-mvp/
├── backend/        Python — FastAPI server + Playwright scraper
├── frontend/       JavaScript — React dashboard
└── docs/           This documentation
```

The backend and scraper share the same codebase and Python process. They share the database
connection, models, config, and utilities. The scraper writes to MongoDB; the FastAPI app reads from it.

---

## Data Flow

```
[Blinkit Seller Dashboard]
         │
         │  Playwright browser / HTTP session
         ▼
[scraper/platforms/blinkit/scraper.py]   ← fetches raw API responses
         │
         │  parser.py maps raw → normalized schema
         ▼
[scraper/normalizer/schema.py]           ← canonical dataclasses
         │
         │  writes to MongoDB
         ▼
[MongoDB]
         │
         │  FastAPI reads
         ▼
[app/api/routes/]                        ← REST endpoints
         │
         │  HTTP/JSON
         ▼
[React Frontend]                         ← renders charts and tables
```

---

## Backend

### `app/`

The FastAPI application. Handles HTTP requests, authentication, and serving data from MongoDB.

---

#### `app/main.py`

The entry point. Creates the FastAPI app, registers middleware, exception handlers, and routes.
Also manages the application lifespan — connects to MongoDB on startup, closes on shutdown.
The scheduler (scraper jobs) will be started here once it's ready.

---

#### `app/core/`

Foundational pieces that everything else depends on. Nothing in `core/` depends on the rest of the app.

| File | Purpose |
|------|---------|
| `config.py` | Reads environment variables from `.env` using pydantic-settings. All config lives here — never hardcode URLs or secrets anywhere else. Import `settings` from here. |
| `database.py` | Opens the MongoDB connection using Motor (async driver) and initializes Beanie (ODM) with all document models. Called once on app startup. |
| `security.py` | Password hashing (bcrypt), JWT creation, and JWT decoding. Used by auth routes and the auth dependency. |

---

#### `app/models/`

MongoDB document definitions using Beanie (an ODM built on Motor). Each class maps directly
to a MongoDB collection. These are the source of truth for what's stored in the database.
Both the FastAPI app and the scraper import from here.

| File | Collection | Purpose |
|------|-----------|---------|
| `user.py` | `users` | Platform users (email, hashed password, tenant reference) |
| `tenant.py` | `tenants` | A tenant is one seller account / brand using the platform |
| `product.py` | `products` | Normalized product listings scraped from platforms |
| `sales.py` | `sales` | Daily sales records (units sold, revenue) per product per platform |
| `inventory.py` | `inventory` | Stock levels and days-of-inventory per product |
| `scrape_job.py` | `scrape_jobs` | Audit log of every scraper run — status, timestamps, errors |

---

#### `app/schemas/`

Pydantic models for what goes **in and out of the API**. These are separate from `models/`
because what the API accepts/returns is often a subset or transformation of what's stored.

For example, `models/user.py` stores a `hashed_password`, but `schemas/auth.py` accepts
`password` (plain) on login and returns only a token — never the hash.

| File | Purpose |
|------|---------|
| `auth.py` | LoginRequest, RegisterRequest, TokenResponse |
| `product.py` | ProductOut — the shape returned by the products API |
| `analytics.py` | OverviewStats, RevenuePoint — shapes for analytics endpoints |

---

#### `app/services/`

Business logic. Routes call services; services call models. This keeps route handlers thin
and logic testable in isolation.

| File | Purpose |
|------|---------|
| `analytics_service.py` | Aggregates sales/product data for dashboard metrics |
| `platform_service.py` | Saves and retrieves encrypted platform credentials |

---

#### `app/api/`

The HTTP layer. Defines URL routes and calls into services.

| File | Purpose |
|------|---------|
| `router.py` | Registers all route modules under `/api`. Add new route files here. |
| `deps.py` | Shared FastAPI dependencies. Currently: `get_current_user` — validates JWT and returns the user payload. Inject into any route that requires auth. |

**`app/api/routes/`** — one file per resource:

| File | Prefix | Purpose |
|------|--------|---------|
| `auth.py` | `/api/auth` | Login, register, logout |
| `analytics.py` | `/api/analytics` | Revenue trends, overview stats |
| `products.py` | `/api/products` | List and view products |
| `inventory.py` | `/api/inventory` | Stock levels |
| `ads.py` | `/api/ads` | Campaign performance |
| `platforms.py` | `/api/platforms` | Connect/disconnect seller accounts |

---

#### `app/utils/`

Shared utilities used across both the FastAPI app and the scraper.

| File | Purpose |
|------|---------|
| `logger.py` | Configures Loguru — structured logging to stdout and `logs/app.log`. Import `logger` from here everywhere instead of using `print`. |
| `response.py` | `success_response()` and `error_response()` — every API endpoint returns the same JSON shape: `{ success, data, message }`. |
| `exceptions.py` | Custom exception classes (`NotFoundError`, `UnauthorizedError`, `ScraperError`, etc.) and the FastAPI exception handlers that convert them to `response.py` format. Registered in `main.py`. |
| `pagination.py` | `PaginationParams` — a FastAPI dependency that reads `?page=1&limit=20` from query params. `paginate()` wraps a list result with total/page/limit metadata. |
| `encryption.py` | Symmetric encryption using Fernet. Used to encrypt seller credentials before storing them in MongoDB. `generate_key()` produces a key to put in `.env`. |

---

### `scraper/`

The data acquisition layer. Runs on a schedule, logs into seller dashboards, pulls data,
and writes normalized records to MongoDB. Shares `app/models/`, `app/core/`, and `app/utils/`.

---

#### `scraper/platforms/`

Each platform is an isolated adapter. Adding a new platform never touches existing code.

**`base.py`** — Abstract base class that defines the contract every platform must implement:
- `login()` — authenticate and establish a session
- `fetch_products()` — pull product listings
- `fetch_sales(days)` — pull sales history
- `fetch_inventory()` — pull stock levels
- `fetch_ads()` — pull ad campaign data
- `run_all()` — calls all of the above in sequence

**`blinkit/`** — Blinkit implementation (currently stubbed, ready to implement):

| File | Purpose |
|------|---------|
| `auth.py` | Handles Blinkit's OTP login flow using Playwright. Returns session cookies. |
| `scraper.py` | Implements `BasePlatformScraper` for Blinkit. Makes HTTP calls to Blinkit's internal API using the session cookies from auth. Each method has the `@retry` decorator. |
| `parser.py` | Maps Blinkit's raw API response fields to the normalized schema types. All platform-specific field name quirks are handled here — nowhere else. |

**`zepto/` and `instamart/`** — Empty stubs. When implementing a new platform: create `auth.py`, `scraper.py`, `parser.py` inside the folder following the same pattern as Blinkit. Register a job in `scheduler/jobs.py`. That's it.

---

#### `scraper/normalizer/`

The bridge between platform-specific data and the database.

| File | Purpose |
|------|---------|
| `schema.py` | Canonical dataclasses: `NormalizedProduct`, `NormalizedSales`, `NormalizedInventory`, `NormalizedAd`. Every platform's `parser.py` outputs these types. The database models mirror these shapes. |
| `transformer.py` | Shared helper functions used by parsers across platforms (e.g. `safe_float`, `safe_int` for handling missing/malformed API values). |

**Why a separate normalizer?** Each platform uses different field names, types, and structures.
The parser handles the translation. Once data is in the normalized schema, the rest of the
system (storage, API, frontend) never needs to know which platform it came from.

---

#### `scraper/scheduler/`

Controls when scraping runs.

| File | Purpose |
|------|---------|
| `runner.py` | Sets up APScheduler and starts it. Called from `app/main.py` on startup. Add new cron jobs here as platforms are implemented. |
| `jobs.py` | One async function per platform job. Each function instantiates the platform's scraper, calls `run_all()`, and handles the result. Kept separate from `runner.py` so jobs are testable without the scheduler. |

---

#### `scraper/utils/`

Scraper-specific utilities.

| File | Purpose |
|------|---------|
| `browser.py` | Factory function that launches a Playwright browser context with stealth configuration — custom user agent, masked `navigator.webdriver` property, realistic viewport. Use this instead of launching Playwright directly. |
| `retry.py` | `@retry(max_attempts, delay, backoff)` decorator for async functions. Retries with exponential backoff on any exception. Used on all scraper fetch methods to handle transient network failures. |

---

## Frontend

### `src/`

React application built with Vite.

---

#### `src/api/`

All HTTP communication with the backend. Nothing outside this folder should call `fetch` or `axios` directly.

| File | Purpose |
|------|---------|
| `client.js` | Configured axios instance. Automatically attaches the JWT from localStorage to every request. Redirects to `/login` on 401. All other API files import from here. |
| `auth.js` | `login()`, `register()`, `logout()` |
| `analytics.js` | `getOverview()`, `getRevenue()` |
| `products.js` | `listProducts()`, `getProduct()` |

---

#### `src/store/`

Global client-side state using Zustand. Keep stores small — only truly global state lives here.
Component-local state (open/closed, form values) stays in `useState`.

| File | Purpose |
|------|---------|
| `authStore.js` | Tracks the logged-in user, JWT token, and `isAuthenticated`. `login()` saves the token to localStorage; `logout()` clears it. |
| `platformStore.js` | Tracks which platform is currently active (Blinkit / Zepto / Instamart). All data-fetching components read from this to know what to request. |

---

#### `src/features/`

Self-contained modules organized by business domain. Each feature owns its own components
and hooks. This prevents cross-feature coupling and makes features easy to find.

```
features/
├── auth/           Login form, auth hooks
├── dashboard/      Overview cards, summary widgets
├── analytics/      Revenue charts, trends
├── products/       Product table, filters
├── inventory/      Stock table, low-stock alerts
└── ads/            Campaign table, performance metrics
```

When building a new feature, everything related to it lives in its folder.
Pages import from features — not the other way around.

---

#### `src/components/`

Generic, reusable UI building blocks with no knowledge of business logic.

```
components/
├── ui/       Button, Badge, Card, Table, Modal, Spinner, Input
└── charts/   Wrappers around the charting library (LineChart, BarChart, MetricCard)
```

A component in `ui/` should work in any project. If a component needs to know about
"products" or "platforms", it belongs in `features/`, not `components/`.

---

#### `src/pages/`

Thin route-level components. A page composes features together — it doesn't contain logic itself.

| File | Route | Purpose |
|------|-------|---------|
| `DashboardPage.jsx` | `/` | Main overview |
| `AnalyticsPage.jsx` | `/analytics` | Revenue and trend charts |
| `ProductsPage.jsx` | `/products` | Product listing |
| `LoginPage.jsx` | `/login` | Auth screen |

---

#### `src/layouts/`

Shell wrappers that wrap groups of pages with shared chrome (sidebar, topbar, etc.).

| File | Wraps | Purpose |
|------|-------|---------|
| `AppLayout.jsx` | All authenticated pages | Renders sidebar navigation + main content area |
| `AuthLayout.jsx` | Login/register pages | Centered card layout, no sidebar |

---

#### `src/router.jsx`

React Router configuration. Maps URL paths to page components and wraps them in the correct layout.
Add new pages here.

---

#### `src/hooks/`

Shared React hooks used across multiple features. If a hook is only used by one feature, it lives
in `features/<name>/hooks/` instead.

| File | Purpose |
|------|---------|
| `useDebounce.js` | Delays a value update — used for search inputs to avoid firing an API call on every keystroke |

---

#### `src/utils/`

Pure functions with no React dependencies.

| File | Purpose |
|------|---------|
| `formatters.js` | Display formatting for Indian market: `formatCurrency` (₹), `formatNumber` (L/Cr/K), `formatPercent`, `formatDate`, `formatROAS`. Use these everywhere instead of inline formatting. |
| `constants.js` | `PLATFORMS`, `PLATFORM_LABELS`, `ROUTES`, `DATE_RANGES`. Single source of truth for string values used across the app. |

---

## Adding a New Platform (Zepto example)

1. **Create the scraper** — implement `auth.py`, `scraper.py`, `parser.py` in `scraper/platforms/zepto/`
   following the same structure as `blinkit/`. Extend `BasePlatformScraper`.

2. **Add a job** — add `scrape_zepto()` to `scraper/scheduler/jobs.py` and register it in `runner.py`.

3. **Add the constant** — `PLATFORMS.ZEPTO` already exists in `frontend/src/utils/constants.js`.

4. **Connect UI** — the platform switcher in the frontend reads from `platformStore`. No other
   changes needed — all data-fetching components already pass `activePlatform` to the API.

That's it. The normalizer, models, API routes, and frontend are already platform-agnostic.

---

## Key Design Decisions

**Scraper inside backend** — They share MongoDB models, config, and utilities. Keeping them
in one deployable unit avoids a network boundary and duplication. They can be split into
separate services later if scale requires it.

**Normalized schema** — Platform-specific field names and quirks are handled in `parser.py`.
Once data is normalized, nothing else in the system knows or cares which platform it came from.
This is what makes adding platforms cheap.

**Schemas separate from Models** — `models/` defines what's stored; `schemas/` defines what
the API accepts and returns. They often differ (e.g. passwords, computed fields, partial updates).

**No v1 prefix on routes** — Added when there's an actual second version with clients on it.
Not before.
