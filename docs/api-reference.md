# API Reference

The FastAPI backend lives in `backend/app/`. It serves the React dashboard and
is organised as **thin routes → services → models**, with Pydantic **schemas**
as the request/response contracts and **dependencies** as the DI/middleware
layer. See [architecture.md](architecture.md) for the directory layout.

- **Base path:** all endpoints are under `/api`.
- **Interactive docs:** `GET /docs` (Swagger) — fully typed from the route `response_model`s.

---

## Core concepts

### Account → Client → User

- **Account** — the subscriber org that logs in & pays. An *agency* (many
  clients) or a *direct seller* (one client). Has no password.
- **Client** — a managed brand/seller and the unit all data is keyed to
  (`tenants` table, `tenant_id`). An Account has one or many.
- **User** — a person who logs in (email + password). Belongs to an Account; can
  act on any of the Account's Clients.

A direct seller is just an Account with a single Client — same code path.

### Two data planes

| | Public data | Private (dashboard) data |
|---|---|---|
| Examples | rankings, SOV, availability | sales, SOH, ads, scorecards, POs |
| Keyed by | `brand_slug` (shared/global) | `tenant_id` (per client) |
| Scoped on read by | the client's **watchlist** | the client's `tenant_id` |

### Routing convention

Once a client is selected, **everything is under `/api/clients/{client_id}/...`**
— private *and* public. The only non-client routes are `auth`, `clients`, and
`reference`.

### Auth & access

- **Login-only.** No public signup; accounts/users are provisioned via the CLI
  (`python -m cli account create ...`).
- JWT (Bearer token) carries `account_id` + `user_id` + `role`. Send it as
  `Authorization: Bearer <token>`. Token storage on the frontend is localStorage.
- Every `/clients/{client_id}/...` route runs the **`ClientDep`** access check:
  the client must belong to the caller's account, else **404** (so one account
  can never reach another's data).
- **Roles.** Each user is `admin` or `member` (column on `users`; the first user
  of an account is `admin`). Admin-only routes use the **`AdminDep`** dependency
  (`require_admin`) and return **403** for members.

### Response conventions

- Success returns the typed body directly (no envelope), with real HTTP status
  codes (200/201/204).
- Errors are uniform: `{"detail": "..."}` (matches FastAPI's `HTTPException`).
  Validation failures are automatic **422**.
- **Pagination** — list endpoints return:
  ```json
  { "items": [...], "total": 0, "page": 1, "limit": 20, "pages": 0 }
  ```
  Controlled by `?page=` (≥1) and `?limit=` (1–100).
- **Time windows** — dashboard endpoints take `?days=` (default 30) and
  aggregate in SQL, so payloads stay small regardless of row volume.

---

## Modules

### `auth` — `/api/auth`
Authentication. The only place a password is used.

| Method | Path | Purpose |
|---|---|---|
| POST | `/login` | Verify email+password, return a JWT carrying `account_id` + `role`. |
| POST | `/logout` | No-op (stateless JWT); a hook for the frontend to drop the token. |
| GET | `/me` | The current user (id, email, full_name, account_id, role, is_active). |

**User creation is CLI-only — there is no signup/user endpoint.** `cli account
create` makes an account + its first `admin`; `cli account add-user --account
<id> --email <e> [--name <n>] [--admin]` adds more users (`member` by default) to
an existing account. Both prompt for the password (bcrypt-hashed). Data is
account-scoped, so every user of an account sees all its clients; `role` only
gates the admin UI + `require_admin` routes. See
[setup.md](setup.md) and [cli.md](cli.md).

### `clients` — `/api/clients`
The account's clients + the client picker.

| Method | Path | Purpose |
|---|---|---|
| GET | `/clients` | List the clients under the caller's account (the switcher). |
| GET | `/clients/{client_id}` | One client (access-checked by `ClientDep`). |

### `reference` — `/api/reference`
Global dropdown data (login required, not client-scoped).

| Method | Path | Purpose |
|---|---|---|
| GET | `/brands` | All brands (slug, name, category, logo, tint). |
| GET | `/marketplaces` | All marketplaces (slug, name, color). |
| GET | `/cities` | Cities → per-platform zones, from `scraper/utils/cities.py` (no DB). |

### `analytics` — `/api/clients/{id}/analytics` *(private)*
Sales rollups over `blinkit_seller_sales` (+ ads for headline KPIs). Every endpoint
takes the reporting window as `?start=&end=` (or legacy `?days=`) via `PeriodDep` and
an optional comma-separated `?marketplaces=`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/overview` | Headline KPIs, each as `{value, prev, delta_pct}`: revenue, **organic_revenue** (= revenue − ad_sales, clamped ≥0), units, SKUs, ad spend, **ad_sales**, impressions, **RoAS** (= ad_sales÷spend), **visibility** (avg brand_sov), **avg_rank**. Performance plane from `blinkit_ad_campaign_daily`; market plane from `search_snapshots` via the own-brand watchlist. |
| GET | `/trends` | Unified daily series for the Overview charts + KPI sparklines: `{date, ad_spend, ad_sales, impressions, revenue, units}`, built on a full date spine (None on gap days). |
| GET | `/revenue` | Revenue + units **time-series** (per day). |
| GET | `/top-skus` | Best-selling SKUs by revenue (`?limit=`). |
| GET | `/sales-by-city` | Revenue/units grouped by city. |
| GET | `/sales-by-category` | Revenue/units grouped by category. |
| GET | `/category-trend` | Per-day revenue/units **per category** (`{date, category, revenue, units_sold}`) for the stacked-area trend; one row per (date, category) with sales. |
| GET | `/city-category` | City × category revenue matrix (`{city, category, revenue, units_sold}`) for the heatmap, scoped to the top `?limit=` cities (default 15) by revenue. |

### `overview` — `/api/clients/{id}/overview` *(private)*
Composite endpoints for the Overview page that span multiple domains.

| Method | Path | Purpose |
|---|---|---|
| GET | `/marketplaces` | Per-marketplace breakdown (rev, RoAS, spend, units, visibility, rank), each `{value, prev, delta_pct}`. Unconnected marketplaces return bare (`connected=false`). Takes `PeriodDep`. |
| GET | `/monthly-trends` | **Month-on-month** ops trends: `{month, osa_pct, fill_rate, po_amount, po_count}` over a month spine (`?months=`, default 3). OSA from `blinkit_soh` (frontend stock %), fill-rate from `blinkit_scorecard_weekly`, PO from `blinkit_pos`. Tenant-wide (no day-range/marketplace scope). |
| GET | `/alerts` | Attention feed: failed scrapes, OOS (SOH), fill-loss (scorecard), shelf-OOS (public), ordered by severity. |
| GET | `/freshness` | Latest scrape per dashboard with age — the "synced Xh ago" chips. |

### `products` — `/api/clients/{id}/products` *(private)*
Per-SKU performance, derived from sales + stock.

Window via `PeriodDep` (`?start=&end=`, legacy `?days=`); `?marketplaces=` (comma-sep slugs, omit for all).

| Method | Path | Purpose |
|---|---|---|
| GET | `/products` | SKU list joined with latest stock + days-of-cover + health `status`. Returns `{summary, products: Page}` — `summary` = KPI strip (active SKUs, revenue, units, avg price, #out-of-stock, #low-cover) for the search/category/window scope. Params: `?search=` (name), `?category=`, `?sort=revenue\|units\|price\|cover`, `?sku_status=out_of_stock\|low_cover\|no_sales\|healthy`, pagination. |
| GET | `/products/{item_id}` | Product 360: totals + avg price, current stock, days-of-cover + status, scorecard potential loss, daily sales `trend`, daily `stock_trend`, per-`facilities` stock, per-`cities` split. 404 if no sales in window. |
| GET | `/products/{item_id}/pos` | Paginated PO line history for the SKU (`blinkit_po_items` ⨝ `blinkit_pos`): po_number, state, issue_date, facility, units ordered/received/remaining, cost, amount. |
| GET | `/products/{item_id}/public` | **Public** (scraped) view of one SKU, bridged private `item_id` → public `platform_product_id` via **`sku_map`**: on-shelf distribution %, price band (min/median/max), avg discount, rating, and per-keyword rank (from `search_listings`). `?days=`. Returns `mapped: false` when the SKU has no map entry yet. |

### `ads` — `/api/clients/{id}/ads` *(private)*
Paid marketing on the platform (sponsored placements, bidding, plans).

Window endpoints take `PeriodDep` (`?start=&end=`, legacy `?days=`) + optional
comma-separated `?marketplaces=` (omit = all). Only Blinkit has ad data today, so
the marketplace filter is a no-op until more platforms connect.

| Method | Path | Purpose |
|---|---|---|
| GET | `/summary` | KPI strip: ad_spend, ad_sales, RoAS, ACoS, impressions, atc, units_sold, active_campaigns — each a `Metric` (value + prev window + delta). RoAS = ad_sales÷spend; ACoS = spend÷ad_sales. |
| GET | `/performance` | Daily spend / impressions / ad_sales / RoAS **time-series** (summed from `blinkit_ad_campaign_daily`). |
| GET | `/budget-split` | Spend + recomputed RoAS per `campaign_type` (donut + by-type table). |
| GET | `/campaigns` | Paginated campaigns: metadata (`blinkit_ad_campaigns`) + per-window rollup from `blinkit_ad_campaign_daily` (budget, impressions, atc, qty, ad_sales, RoAS). Filter `?status=`; `?sort=spend\|roas\|sales\|impressions` + `?order=asc\|desc` (sort `roas` = RoAS leaderboard / worst spenders). |
| GET | `/keywords` | Paginated keyword/asset performance from the latest `blinkit_ad_campaign_detail` snapshot per campaign (target, match_type, cpm, direct/indirect sales, direct/total RoAS, position, new users). Filter `?campaign_id=`, `?target_type=keyword\|recommendation`; same `?sort`/`?order`. |
| GET | `/sov` | Sponsored share-of-voice, latest per keyword in the window. |
| GET | `/marketplaces` | Per-marketplace ad slice (spend, ad_sales, RoAS, impressions as `Metric`); unconnected MPs returned bare (`connected=false`) for "Not connected" cards. |
| GET | `/visibility-plans` | Visibility/placement plans + budgets. |
| GET | `/collections` | Curated brand collections. |

### `inventory` — `/api/clients/{id}/inventory`
Stock health: private SOH + fill-rate, plus the **public own-SKU** surface from
`sku_snapshots` (populated by `scrape public-skus`). Public endpoints need an `own`
watchlist brand and carry an `as_of` timestamp (weekly cadence → show freshness).
They also take **`?kind=main|combo|all`** (default `main`) — combos/multipacks are
stocked selectively, so they're analysed apart from singular main SKUs.

| Method | Path | Purpose |
|---|---|---|
| GET | `/soh` | Paginated stock-on-hand per SKU (summed across facilities, low-stock first). `?date=` defaults latest. *(private)* |
| GET | `/fill-rate` | PO fill-rate summary (PO vs GRN qty, potential loss). `?from=` defaults latest. *(private)* |
| GET | `/availability` | **Public** stock-out monitoring — latest `sku_snapshots` row per (marketplace, city, product), out-of-stock first. Filters `?city=`, `?marketplace=`, `?days=` (default 30). |
| GET | `/distribution` | **Public** distribution % per own SKU = in-stock stores ÷ stores it appears in (latest snapshot per store); widest gaps first. `?city=`, `?marketplace=`, `?days=`. |
| GET | `/availability-history` | **Public** weekly on-shelf availability % trend for own SKUs. `?days=` (default 84 = 12 weeks), `?city=`, `?marketplace=`. |
| GET | `/pricing` | **Public** per-SKU price dispersion across stores (min/median/max) + avg discount, latest snapshot per store. `?city=`, `?marketplace=`, `?days=`. |

### `scorecard` — `/api/clients/{id}/scorecard` *(private)*
Blinkit brand-health scorecard. **Weekly snapshots** keyed on `from_date_ist`
(not daily) and Blinkit-only, so these navigate by week (`?from=`, default latest)
rather than the global date range / marketplace selectors. Fill-rate fields are
0–100 numbers, not 0–1 fractions.

| Method | Path | Purpose |
|---|---|---|
| GET | `/weeks` | Available weeks (`from_date_ist`), newest first — powers the page's week picker. |
| GET | `/weekly` | Selected (or latest) week: raw `overall`, `best_category`, per-category JSON, plus `metrics{value,prev,delta_pct}` vs the prior week and `prev_from_date`. `?from=`. 404 if none. |
| GET | `/trend` | Per-week overall metrics across the last `?weeks=` snapshots (default 12, oldest first) — fill rate, weighted fill, potential loss, GMV, PO/GRN qty, rank. |
| GET | `/key-skus` | Paginated key SKUs ranked by potential loss. `?from=`. |
| GET | `/facilities` | Paginated facilities ranked by potential loss. `?from=`. |
| GET | `/facility/{facility_id}/pos` | Paginated POs behind a facility's fill loss (`blinkit_pos` joined on `facility_id`), newest issue date first — the "fill loss → which POs" drill-down. |

### `competition` — `/api/clients/{id}/competition` *(public, watchlist-scoped)*
Competitive intel, auto-scoped to the client's **own** brand(s) via the watchlist.

| Method | Path | Purpose |
|---|---|---|
| GET | `/share-of-voice` | Own-brand SOV summary + daily trend. Filters `?keyword=`, `?city=`, `?marketplace=`, `?days=`. |
| GET | `/rank-matrix` | Own-brand avg rank + SoV per (keyword × city) — the "where am I weak" **heatmap**. Returns `keywords` (rows), `cities` (cols), flat `cells`, `as_of`. `?marketplace=`, `?days=` (default 30). |
| GET | `/top-competitors` | Competitor leaderboard: appearances, distinct keywords, avg position/price, share % of all competitor appearances. `?keyword=`, `?city=`, `?marketplace=`, `?days=`, `?limit=` (default 15). |
| GET | `/price-position` | Per keyword: own price band (avg/min/max) vs competitor band (avg/min/median/max) — priced in or out of the set. `?keyword=`, `?city=`, `?marketplace=`, `?days=`. |
| GET | `/rankings` | Paginated competitor positions/prices for the own brand. Filters `?keyword=`, `?city=`, `?marketplace=`, `?competitor=`. |

Empty results until the client has an `own` watchlist entry. `rank-matrix` /
`top-competitors` / `price-position` read the keyword-scrape tables
(`search_snapshots` / `search_listings`); the `inventory/*` public endpoints read
`sku_snapshots`. Each carries an `as_of` for the freshness badge.

### `purchase-orders` — `/api/clients/{id}/purchase-orders` *(private)*
Blinkit POs (`raw` carries vendor + line items).

| Method | Path | Purpose |
|---|---|---|
| GET | `/purchase-orders` | Paginated POs (po_number, scraped_at, full `raw`). |
| GET | `/purchase-orders/snapshots` | Paginated PO window snapshots. |
| GET | `/purchase-orders/{po_number}` | One PO with full `raw`. 404 if not found. |

### `watchlist` — `/api/clients/{id}/watchlist` *(write)*
What the client tracks: own + competitor brands, with keywords/cities/marketplaces.
Drives the public-data scrape set and the client's view of `competition`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/watchlist` | List entries. |
| POST | `/watchlist` | Add an entry (`brand_slug`, `relationship`, cities/keywords/marketplaces). Validates brand exists (400) and relationship enum (422). |
| PUT | `/watchlist/{entry_id}` | Partial update. 404 if not the client's. |
| DELETE | `/watchlist/{entry_id}` | Remove (204). |

### `platforms` — `/api/clients/{id}/platforms`
Platform connection state. **Connecting** is interactive (OTP/browser) and done
via the CLI — the API only exposes status + disconnect.

| Method | Path | Purpose |
|---|---|---|
| GET | `/platforms` | Connected platforms + connected-at. |
| DELETE | `/platforms/{platform}` | Disconnect (delete session). 204, or 404 if none. |

### `jobs` — `/api/clients/{id}/jobs` *(private)*
Scrape-job history — data freshness / failures.

| Method | Path | Purpose |
|---|---|---|
| GET | `/jobs` | Paginated jobs (status, dashboard, records_written, timing). Filter `?status=`. |
| GET | `/jobs/{job_id}` | One job (incl. error). 404 if not the client's. |

---

## Adding a new endpoint

1. **schema** (`schemas/<group>.py`) — Pydantic request/response shapes.
2. **service** (`services/<group>_service.py`) — query logic; `session` first arg;
   private services filter by `tenant_id`, public ones by the watchlist.
3. **route** (`routes/<group>.py`) — thin handler; declare `session: SessionDep`,
   `client: ClientDep` (for client-scoped), `pagination: PaginationDep` as needed.
4. **mount** in `router.py` under `/clients/{client_id}/<group>` (or top-level).

Patterns to reuse: `Page[T]` (paginated lists), `DISTINCT ON` (latest snapshot
per entity), SQL aggregates for dashboards (never ship raw rows), JSON-column
passthrough (`dict[str, Any]`) for scraped blobs.
