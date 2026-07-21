# Dashboard Views — Insight Catalog

The reference for **what the dashboard shows and where the data comes from**. Each
row is a question the dashboard answers, the page/subsection it lives in, the
tables+columns that must be clubbed, and the API that serves it. Living doc —
update as views are built and the schema evolves.

See [api-reference.md](api-reference.md) for the existing endpoint surface and
[architecture.md](architecture.md) for the DB schema.

---

## Design principles

- **Page = question, section = sub-question.** Don't mirror the API one-card-per-endpoint. Each section pulls whatever endpoints it needs.
- **Place ≠ join.** Placing data side by side → frontend composition (fetch 3–4 endpoints in parallel, lay out coherently). Computing a number that needs both sources → a new SQL-joined (BFF-style) endpoint.
- **Build endpoints view-by-view, not speculatively.** Lay out the page, see exactly what it needs, then write the endpoint to match. Avoids shipping fields no card renders.
- **Two data planes** (keep them distinct in the UI):
    - **Your performance** (private, `tenant_id`-scoped): sales, stock, ads, POs, scorecard — "how am I doing?"
    - **The market** (public, watchlist-scoped): rankings, SOV, availability — "how do I look on the shelf vs competitors?"

## Join keys that exist

- Private data keys on **`item_id`** + **`city_id`/`city_name`** + **`date`** + **`category`**.
- Ads key on **`campaign_id`** and **`keyword`** (separately).
- Public data keys on **`brand_slug`** + **`mp_slug`** + **`city`** + **`zone`** + **`keyword`**.

## Data gaps (decisions, not queries)

1. **Keyword-level ad attribution — DONE; SKU-level still open.** The marketing
   scraper now captures **per-campaign daily** metrics (`blinkit_ad_campaign_daily`:
   budget, impressions, atc, qty, ad_sales, roas) and a **per-keyword / per-asset
   breakdown** (`blinkit_ad_campaign_detail`: target, match_type, direct/total
   RoAS, sales, etc.). So keyword-level ad ROI is unlocked. **SKU-level** RoAS is
   still not available — the report breaks down by keyword/asset, not by `item_id`
   — so that remains dependent on an `sku_map` (gap #2).
2. **Private sales ↔ public availability — now bridged (`sku_map`, BUILT).** Private
   = `item_id`; public = `platform_product_id` (different Blinkit id systems, no
   shared UPC). The **`sku_map`** table links them (name-matched via `cli sku-map`),
   so the Product 360 now shows *sold* (private) next to *on-shelf + ranked* (public)
   at `/products/{item_id}/public`. **Public counts are distinct dark stores
   (`merchant_id`), not `(lat,lon)`** — see [darkstores.md](darkstores.md) and
   [public-glossary.md](public-glossary.md) (Reach = listed÷scraped, Distribution =
   in-stock÷listed). The UI relabels these **"on shelf"** / **"in stock"** for a sales
   reader (FMCG "distribution" means breadth — the opposite — so the raw words mislead).

Legend: **[E]** existing endpoint · **[N]** new endpoint to build · **[E→N]** extend existing · **[B]** built for this catalog.

## Global controls (app shell)

Two app-owned selectors live in the Navbar and feed every marketplace/date-aware
query via its React Query key (Context holds the selection; React Query holds the
data — they never overlap):

- **Date range** (`DateRangeContext`) — canonical `{ from, to }` window; presets
  (7/30/90d) are sugar that compute it, custom picks both ends. Sent to the API
  as `?start=&end=`. Resolved server-side by **`PeriodDep`** (in
  `app/dependencies.py`), which also returns the equal-length **previous window**
  so any endpoint can compute period-over-period growth. `PeriodDep` still
  accepts legacy `?days=`, so endpoints migrate to it view-by-view (not all at
  once); unmigrated endpoints keep working unchanged.
- **Marketplace** (`MarketplaceContext`) — multi-select + "All", persisted. Only
  **connected** marketplaces are selectable; the rest show disabled ("soon").
  Connectivity comes from `GET /reference/marketplaces` (`connected` flag, from
  `settings.CONNECTED_MARKETPLACES` = `["blinkit"]` today; later derived from
  successful `scrape_jobs`). Sent to the API as comma-separated `?marketplaces=`.

**Growth/deltas:** every Overview metric is a `{ value, prev, delta_pct }`
(`Metric` schema). `delta_pct` is null when there's no prior value; `value` is
null when there are no samples. Rendered by the shared `DeltaBadge`/`MetricTile`
(avg rank is lower-is-better → inverted colors).

---

## Overview — "what needs my attention today"

| Insight                                                                                                                                                                 | Subsection        | Tables.columns                                                                                                                       | API                                                                                                                  |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Headline KPIs + growth + sparklines (Ad Spend, **Ad Revenue**, **Ad RoAS**, Total Revenue, **Organic Revenue**, units, SKUs, impressions, **visibility**, **avg rank**) | KPI strip         | `blinkit_seller_sales` + `blinkit_ad_campaign_daily`(budget, ad_sales) + `search_snapshots`(brand_sov, brand_rank via own watchlist)   | `analytics/overview` **[B]** (PeriodDep + `marketplaces`, deltas; RoAS = ad_sales÷spend; organic = revenue−ad_sales) |
| **Marketplace-wise overview** — per-MP rev/RoAS/spend/units/visibility/rank + growth; "Not connected" for MPs without data                                              | Marketplace cards | per-MP slice of the same tables, scoped by `platform` + `mp_slug`                                                                    | `/overview/marketplaces` **[B]**                                                                                     |
| **Ad spend vs ad revenue** + **Total revenue** trends (daily)                                                                                                           | Two charts        | `blinkit_ad_campaign_daily`(budget, ad_sales) + `blinkit_seller_sales`(mrp_value) on a date spine                                    | `analytics/trends` **[B]** (one aligned series for charts + sparklines)                                              |
| **Operations (month-on-month): OSA, fill-rate, PO value**                                                                                                               | 3 bar charts      | `blinkit_soh`(frontend_inv_qty) + `blinkit_scorecard_weekly`(overall.fill_rate) + `blinkit_pos`(total_po_amount) by month            | `/overview/monthly-trends` **[B]** (`?months=`, default 3; tenant-wide, not day-range scoped)                        |
| **Attention feed** — failed scrapes, OOS, fill-loss                                                                                                                     | Alerts list       | `scrape_jobs`(status) + `blinkit_soh`(frontend_inv_qty) + `blinkit_scorecard_key_skus`(potential_loss) + `sku_snapshots`(in_stock) | `/overview/alerts` **[B]**                                                                                           |
| Data freshness ("sales last synced 2d ago")                                                                                                                             | Status chips      | `scrape_jobs`(dashboard, status, completed_at) latest per dashboard                                                                  | `/overview/freshness` **[B]**                                                                                        |

## Sales & Analytics — "where is revenue coming from"

Single page. Each section is a `ChartTableCard` — a chart with a Chart/Table
toggle over the same data (the table view shows exact numbers / full lists where
the chart truncates).

| Insight                      | Subsection                 | Tables.columns                                                  | API                                                                    |
| ---------------------------- | -------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------- |
| KPIs: revenue, units, SKUs, avg price/unit (+ deltas, sparklines) | KPI strip | `blinkit_seller_sales`(mrp_value, qty_sold, item_id) | `analytics/overview` **[E]** + `analytics/trends` (sparklines). Sales-plane only; blended ad tiles (organic rev, ad spend, RoAS) are present in code but commented out — re-enable if a blended read is wanted. |
| Revenue/units over time      | Main chart (metric toggle) | `blinkit_seller_sales`(date, mrp_value, qty_sold)               | `analytics/revenue` **[E]**                                            |
| Top SKUs by revenue          | Ranked bars/table          | `blinkit_seller_sales`(item_id, item_name, mrp_value, qty_sold) | `analytics/top-skus` **[E]** (now PeriodDep + `marketplaces`)          |
| Revenue by city              | Bar list / table           | `blinkit_seller_sales`(city_name, mrp_value)                    | `analytics/sales-by-city` **[E]** (now PeriodDep + `marketplaces`)     |
| Revenue by category & city   | Stacked bars / matrix table (group-by toggle) | `blinkit_seller_sales`(category, city_name, mrp_value)          | `analytics/sales-by-category` **[E]** (bar totals) + `/analytics/city-category` **[B]** (segments, top-`limit` cities; the uncovered remainder folds into "Other") |
| **Category trend over time** | Stacked area / table       | `blinkit_seller_sales`(date, category, mrp_value)               | `/analytics/category-trend` **[B]**                                    |

## Products — "per-SKU deep dive" (richest composed view)

**Live.** List view = KPI strip + filterable/sortable/paginated SKU table (rows
link to detail); detail = Product 360 route `/products/:itemId`. Private plane
only (no public shelf/rank join yet — gap #2).

| Insight                                              | Subsection             | Tables.columns                                                                                                    | API                                   |
| ---------------------------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| SKU list + latest stock + cover + health status; KPI strip (active SKUs, rev, units, avg price, #OOS, #low-cover) | Table + KPI strip | `blinkit_seller_sales` + latest `blinkit_soh`(frontend_inv_qty, backend_inv_qty) | `products` **[B]** (`PeriodDep` + `marketplaces`; `sort=revenue\|units\|price\|cover`, `sku_status` filter, `search`, `category`; returns `{summary, products: Page}`) |
| **Product 360**: sales trend + stock-over-time + per-facility stock + days-of-cover + scorecard loss | Detail page | `blinkit_seller_sales`(date, qty_sold, mrp_value, city) + `blinkit_soh`(backend/frontend per facility & per day) + `blinkit_scorecard_key_skus`(potential_loss) | `products/{item_id}` **[B]** (`PeriodDep` + `marketplaces`) |
| **Days of cover** = current frontend stock ÷ avg daily sales | List sort/status + detail KPI | `blinkit_soh`(frontend_inv_qty) ÷ `blinkit_seller_sales`(qty_sold ÷ window-days) | helpers `cover_metrics`/`cover_status` in `product_service` **[B]**; `/inventory/cover` page endpoint still **[N]** (reuse helpers) |
| SKU sold across which cities                         | Detail breakdown       | `blinkit_seller_sales`(city_name, qty_sold, mrp_value) WHERE item_id                                              | `products/{item_id}` (`cities[]`) **[B]** |
| SKU's PO history                                     | Detail tab             | `blinkit_po_items`(units_ordered, remaining_quantity, cost_price, total_amount) ⨝ `blinkit_pos`(issue_date, po_state, facility_name) WHERE item_id | `/products/{item_id}/pos` **[B]** (paginated; received = ordered − remaining) |

## Inventory — "what's out or about to be"

| Insight                                               | Subsection               | Tables.columns                                                                                   | API                                       |
| ----------------------------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------ | ----------------------------------------- |
| Stock on hand, low-first                              | Table                    | `blinkit_soh`(item_id, backend_facility_name, backend_inv_qty, frontend_inv_qty)                 | `inventory/soh` **[E]**                   |
| **Reorder list** (days-of-cover ascending)            | Table                    | `blinkit_soh` ÷ `blinkit_seller_sales` velocity                                                  | `/inventory/cover` **[N]**                |
| Fill rate / PO vs GRN / potential loss                | Summary + facility table | `blinkit_scorecard_facilities`(total_po_quantity, total_grn_quantity, fill_rate, potential_loss) | `inventory/fill-rate` **[E]**             |
| **Needs attention** (worst products + worst cities)   | Ranked lists, 2 tabs     | `/inventory/distribution` (per-SKU OOS / missing) + `/inventory/cities`                          | `inventory/distribution`+`cities` **[B]** |
| **Where you're on the shelf** (city/store/product)    | Sortable table, 3 lenses; row → drawer | `/inventory/cities`, `/inventory/stores`, `/inventory/distribution`                | `inventory/cities`+`stores`+`distribution` **[B]** |
| **Store shelf** (drawer: one store, every SKU)        | Slide-over               | `/inventory/stores/{merchant_id}` — listed + not-carried per SKU                                 | `/inventory/stores/{id}` **[B]**          |
| **Product spread** (drawer: one SKU, every store)     | Slide-over               | `/inventory/products/{product_id}/stores`                                                        | `/inventory/products/{id}/stores` **[B]** |
| **City detail** (drawer: one city's stores)           | Slide-over               | `/inventory/stores?city=`                                                                        | `/inventory/stores` **[B]**               |
| **Availability trend** (weekly in-stock %)            | Trend, `?weeks=`         | `sku_snapshots`(scraped_at, in_stock) per `merchant_id`/week                                     | `/inventory/availability-history` **[B]** |
| **Own-SKU price differences between stores**          | Table                    | `sku_snapshots`(platform_product_id, price, mrp, discount_pct) per `merchant_id`                 | `/inventory/pricing` **[B]**              |
| **SKU 360 public panel** (on shelf, in stock, rank)   | Meters + rank list       | `sku_map` ⨝ `sku_snapshots` + `search_listings` (per-keyword rank), distinct `merchant_id`       | `/products/{item_id}/public` **[B]**      |
| **Facility stock heatmap** (SKU × facility low spots) | Matrix                   | `blinkit_soh`(item_id, backend_facility_name, frontend_inv_qty)                                  | `/inventory/by-facility` **[N]**          |

## Ads — "is my spend working"

| Insight                                            | Subsection    | Tables.columns                                                                   | API                                                |
| -------------------------------------------------- | ------------- | -------------------------------------------------------------------------------- | -------------------------------------------------- |
| KPI strip: spend, ad revenue, RoAS, ACoS, impressions, ATC, units, #active campaigns (+ deltas, sparklines) | KPI strip | `blinkit_ad_campaign_daily`(budget, ad_sales, impressions, atc, quantities_sold, campaign_id) | `ads/summary` **[B]** (PeriodDep + `marketplaces`, `Metric` per tile); sparklines reuse `ads/performance` |
| Spend/impressions/sales + RoAS trend               | Chart         | `blinkit_ad_campaign_daily`(date, budget_consumed, impressions, ad_sales) summed | `ads/performance` **[B]** (now PeriodDep + `marketplaces`, emits daily `roas`) |
| Campaign table (RoAS, spend, status)               | Table         | `blinkit_ad_campaigns`(name, type, status) + `blinkit_ad_campaign_daily` rollup  | `ads/campaigns` **[B]** (now `?sort`/`?order` + PeriodDep + `marketplaces`) |
| Budget split by campaign type                      | Donut         | `blinkit_ad_campaign_daily`(campaign_type, budget_consumed, ad_sales) summed     | `ads/budget-split` **[B]**                         |
| Sponsored SOV per keyword                          | Table w/ bars | `blinkit_sponsored_sov`(keyword, monthly_searches, sov)                          | `ads/sov` **[B]** (now PeriodDep + `marketplaces`) |
| RoAS leaderboard / worst spenders                  | Sorted cards  | `blinkit_ad_campaign_daily` rollup (ad_sales ÷ budget) ranked                    | `ads/campaigns?sort=roas&order=asc\|desc` **[B]**  |
| **Ads by marketplace** — per-MP spend/revenue/RoAS; "Not connected" for MPs without ad data | Marketplace cards | per-MP slice of `blinkit_ad_campaign_daily`, scoped by `platform`         | `ads/marketplaces` **[B]**                         |
| Visibility plans & collections                     | Side lists    | `blinkit_visibility_plans`, `blinkit_brand_collections`                          | `ads/visibility-plans`, `ads/collections` **[B]**  |
| Blended (store) spend vs revenue                   | KPI           | `blinkit_ad_campaign_daily`(budget) vs `blinkit_seller_sales`(mrp_value)         | fold into `analytics/overview` **[E]**             |
| **Keyword / asset performance + per-keyword RoAS** | Keyword table | `blinkit_ad_campaign_detail`(target, match_type, budget, direct/total_roas, …)   | `ads/keywords` **[B]**                             |

## Market / Competition — "how do I look on the shelf"

| Insight                                             | Subsection                  | Tables.columns                                                            | API                                    |
| --------------------------------------------------- | --------------------------- | ------------------------------------------------------------------------- | -------------------------------------- |
| Own-brand SOV summary + trend                       | Card + line                 | `search_snapshots`(brand_sov, scraped_at, keyword, city)                    | `competition/share-of-voice` **[E]**   |
| Competitor rankings & prices                        | Table, own rows highlighted | `competitor_rankings`(competitor, position, price, keyword, city)         | `competition/rankings` **[E]**         |
| **Your rank by keyword × city** (where you're weak) | Heatmap                     | `search_snapshots`(brand_rank, keyword, city)                               | `/competition/rank-matrix` **[N]**     |
| **Organic vs paid visibility**                      | Dual bar per keyword        | `search_snapshots`(brand_sov) + `blinkit_sponsored_sov`(sov) on **keyword** | `/competition/visibility` **[N]**      |
| **Price vs position** (priced out of top ranks?)    | Scatter                     | `competitor_rankings`(competitor, price, position) incl. own brand        | `/competition/price-position` **[N]**  |
| **Competitor watch** (who keeps beating you)        | Ranked list                 | `competitor_rankings`(competitor, position) frequency                     | `/competition/top-competitors` **[N]** |

## Scorecard — "Blinkit's view of my brand health"

**Built (2026-06-29).** Scorecard data is **weekly snapshots** keyed on
`from_date_ist`, and Blinkit-only — so the page navigates by a **page-local week
picker** (`/scorecard/weeks`, latest by default), and the global date-range +
marketplace selectors are no-ops here (like Overview's monthly-trends takes its
own `?months=`). `scorecard/weekly` was extended to also return the previous
week's metrics so the KPI tiles get period-over-period deltas via the shared
`MetricTile`/`DeltaBadge` (fill-rate & GMV better-up; potential-loss & rank
better-down). Note `fill_rate`/`weighted_fill_rate_percent` are stored as 0–100
numbers (not 0–1 fractions) — format directly, don't ×100.

| Insight                                  | Subsection              | Tables.columns                                                                                                                    | API                                    |
| ---------------------------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Available weeks (for the picker)         | Week dropdown           | `blinkit_scorecard_weekly`(from_date_ist DISTINCT)                                                                                | `scorecard/weeks` **[B]**              |
| Weekly headline + deltas (fill rate, GMV, potential loss, rank, PO/GRN) | KPI cards + week picker | `blinkit_scorecard_weekly`(overall, best_category JSON) — current + prior week | `scorecard/weekly` **[E→N]** (now returns `metrics{value,prev,delta_pct}` + `prev_from_date`) |
| Per-category fill                        | Bars + table            | `blinkit_scorecard_weekly`(categories JSON)                                                                                       | `scorecard/weekly` **[E]** (fed from the same fetch) |
| Key SKUs by potential loss               | Table                   | `blinkit_scorecard_key_skus`(item_name, potential_loss, total_gmv, proxy_category)                                                | `scorecard/key-skus` **[E]**           |
| Facilities by potential loss             | Table (expandable rows) | `blinkit_scorecard_facilities`(facility_name, fill_rate, potential_loss, manufacturer_rank)                                       | `scorecard/facilities` **[E]**         |
| **Fill-rate trend across weeks**         | Line (metric toggle) + table | `blinkit_scorecard_weekly`(from_date_ist, overall) multi-week                                                                | `/scorecard/trend` **[B]** (`?weeks=`, default 12) |
| **Fill loss → which POs** (supply story) | Row drill-down          | `blinkit_scorecard_facilities`(facility_id, potential_loss) + `blinkit_pos`(facility_id, total_units_ordered, total_grn_quantity) | `/scorecard/facility/{id}/pos` **[B]** (paginated, lazy on expand) |

## Ops / Settings

| Insight                       | Subsection | Tables.columns                                                   | API                      |
| ----------------------------- | ---------- | ---------------------------------------------------------------- | ------------------------ |
| Watchlist (own + competitors) | Editor     | watchlist table                                                  | `watchlist` CRUD **[E]** |
| Platform connection status    | Cards      | `platform_sessions`                                              | `platforms` **[E]**      |
| Scrape job history / failures | Table      | `scrape_jobs`(dashboard, status, records_written, error, timing) | `jobs` **[E]**           |

---

## New endpoints implied (build with their page)

**High value:** `/overview/alerts`, `/inventory/cover`, `/competition/visibility`, `/competition/rank-matrix`. _(Products page endpoints — extended list, Product 360, `/products/{item_id}/pos` — now built; `/inventory/cover` can reuse `product_service.cover_metrics`/`cover_status`.)_

**Medium:** `/inventory/availability-history`, `/inventory/by-facility`, `/competition/price-position`, `/competition/top-competitors`.

**Done (Scorecard):** full page surface built — `scorecard/weeks` + `scorecard/trend` + `scorecard/facility/{id}/pos` added; `scorecard/weekly` extended with prev-week deltas. Frontend `features/scorecard/` built (week picker, KPI strip, fill-rate trend, category fill, key-SKUs table, facilities table with PO drill-down).

**Done (Sales & Analytics):** `/analytics/category-trend`, `/analytics/city-category` built; `top-skus` / `sales-by-city` / `sales-by-category` migrated to `PeriodDep` + `marketplaces`. Page is live (single page, `ChartTableCard` per section).

**Done (Ads):** full page surface built — `ads/summary`, `ads/budget-split`, `ads/keywords`, `ads/marketplaces` added; `ads/campaigns` (`?sort`/`?order`), `ads/performance` (daily RoAS), `ads/sov` migrated to `PeriodDep` + `marketplaces`. Frontend `features/ads/` built (KPI strip, spend-vs-revenue trend, budget-split donut, campaigns table, keyword/asset table, ads-by-marketplace breakdown, SOV table, visibility-plans/collections side rail).

**Extend existing (cheap):** blended spend-vs-revenue into `analytics/overview`.

## Suggested build order

Overview → Products/Analytics → Inventory → Ads → Competition → Scorecard → Settings.
Overview first: it forces the shared shell (client switcher, date range, KPI card,
time-series chart, paginated table) that every other page reuses, and exercises
the full round-trip on the smallest page (existing composite endpoint + one new
SQL-joined endpoint `/overview/alerts`).
