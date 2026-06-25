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
2. **Private sales ↔ public availability can't be joined.** Private = `item_id` +
   `item_name`; public = `sku`/`platform_product_id` + `product_name`. No shared
   key (public has no UPC either). A unified "this SKU: selling + on-shelf +
   ranked" view needs an **`sku_map` table** (`item_id` ↔ `brand_slug`+`sku`),
   populated manually or by fuzzy name match. Until then, keep private and public
   views **separate** rather than faking a join.

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

| Insight                                                                                          | Subsection        | Tables.columns                                                                                                          | API                                                                            |
| ----------------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Headline KPIs + growth + sparklines (Ad Spend, **Ad Revenue**, **Ad RoAS**, Total Revenue, **Organic Revenue**, units, SKUs, impressions, **visibility**, **avg rank**) | KPI strip | `blinkit_seller_sales` + `blinkit_ad_campaign_daily`(budget, ad_sales) + `search_results`(brand_sov, brand_rank via own watchlist) | `analytics/overview` **[B]** (PeriodDep + `marketplaces`, deltas; RoAS = ad_sales÷spend; organic = revenue−ad_sales) |
| **Marketplace-wise overview** — per-MP rev/RoAS/spend/units/visibility/rank + growth; "Not connected" for MPs without data | Marketplace cards | per-MP slice of the same tables, scoped by `platform` + `mp_slug`                                                      | `/overview/marketplaces` **[B]**                                               |
| **Ad spend vs ad revenue** + **Total revenue** trends (daily) | Two charts | `blinkit_ad_campaign_daily`(budget, ad_sales) + `blinkit_seller_sales`(mrp_value) on a date spine | `analytics/trends` **[B]** (one aligned series for charts + sparklines) |
| **Operations (month-on-month): OSA, fill-rate, PO value** | 3 bar charts | `blinkit_soh`(frontend_inv_qty) + `blinkit_scorecard_weekly`(overall.fill_rate) + `blinkit_pos`(total_po_amount) by month | `/overview/monthly-trends` **[B]** (`?months=`, default 3; tenant-wide, not day-range scoped) |
| **Attention feed** — failed scrapes, OOS, fill-loss                                             | Alerts list       | `scrape_jobs`(status) + `blinkit_soh`(frontend_inv_qty) + `blinkit_scorecard_key_skus`(potential_loss) + `inventory_depth`(in_stock) | `/overview/alerts` **[B]**                                                      |
| Data freshness ("sales last synced 2d ago")                                                     | Status chips      | `scrape_jobs`(dashboard, status, completed_at) latest per dashboard                                                    | `/overview/freshness` **[B]**                                                   |

## Sales & Analytics — "where is revenue coming from"

Single page. Each section is a `ChartTableCard` — a chart with a Chart/Table
toggle over the same data (the table view shows exact numbers / full lists where
the chart truncates).

| Insight                      | Subsection        | Tables.columns                                                  | API                                   |
| ---------------------------- | ----------------- | --------------------------------------------------------------- | ------------------------------------- |
| Revenue/units over time      | Main chart (metric toggle) | `blinkit_seller_sales`(date, mrp_value, qty_sold)     | `analytics/revenue` **[E]**           |
| Top SKUs by revenue          | Ranked bars/table | `blinkit_seller_sales`(item_id, item_name, mrp_value, qty_sold) | `analytics/top-skus` **[E]** (now PeriodDep + `marketplaces`) |
| Revenue by city              | Bar list / table  | `blinkit_seller_sales`(city_name, mrp_value)                    | `analytics/sales-by-city` **[E]** (now PeriodDep + `marketplaces`) |
| Revenue by category          | Donut / table     | `blinkit_seller_sales`(category, mrp_value)                     | `analytics/sales-by-category` **[E]** (now PeriodDep + `marketplaces`) |
| **Category trend over time** | Stacked area / table | `blinkit_seller_sales`(date, category, mrp_value)           | `/analytics/category-trend` **[B]**   |
| **City × category matrix**   | Heatmap / table   | `blinkit_seller_sales`(city_name, category, mrp_value)          | `/analytics/city-category` **[B]** (top-`limit` cities) |

## Products — "per-SKU deep dive" (richest composed view)

| Insight                                              | Subsection             | Tables.columns                                                                                                    | API                                   |
| ---------------------------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| SKU list with sales + latest stock                   | Table                  | `blinkit_seller_sales` + `blinkit_soh`(frontend_inv_qty, backend_inv_qty)                                         | `products` **[E]**                    |
| **Product 360**: sales trend + stock + days-of-cover | Detail page            | `blinkit_seller_sales`(date, qty_sold, mrp_value) + `blinkit_soh`(backend_inv_qty, frontend_inv_qty per facility) | extend `products/{item_id}` **[E→N]** |
| **Days of cover** = stock ÷ avg daily sales          | Detail KPI + list sort | `blinkit_soh`(frontend_inv_qty) ÷ `blinkit_seller_sales`(qty_sold avg)                                            | `/inventory/cover` **[N]**            |
| SKU sold across which cities                         | Detail breakdown       | `blinkit_seller_sales`(city_name, qty_sold) WHERE item_id                                                         | extend `products/{item_id}` **[N]**   |
| SKU's PO history                                     | Detail tab             | `blinkit_po_items`(po_number, units_ordered, total_amount) WHERE item_id                                          | `/products/{item_id}/pos` **[N]**     |

## Inventory — "what's out or about to be"

| Insight                                               | Subsection               | Tables.columns                                                                                   | API                                       |
| ----------------------------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------ | ----------------------------------------- |
| Stock on hand, low-first                              | Table                    | `blinkit_soh`(item_id, backend_facility_name, backend_inv_qty, frontend_inv_qty)                 | `inventory/soh` **[E]**                   |
| **Reorder list** (days-of-cover ascending)            | Table                    | `blinkit_soh` ÷ `blinkit_seller_sales` velocity                                                  | `/inventory/cover` **[N]**                |
| Fill rate / PO vs GRN / potential loss                | Summary + facility table | `blinkit_scorecard_facilities`(total_po_quantity, total_grn_quantity, fill_rate, potential_loss) | `inventory/fill-rate` **[E]**             |
| Public shelf availability (own brand OOS)             | Table, city/mp filter    | `inventory_depth`(sku, product_name, in_stock, depth, city, mp_slug)                             | `inventory/availability` **[E]**          |
| **Stock-out timeline** (when/how long OOS)            | Trend                    | `inventory_depth`(scraped_at, in_stock) per sku                                                  | `/inventory/availability-history` **[N]** |
| **Facility stock heatmap** (SKU × facility low spots) | Matrix                   | `blinkit_soh`(item_id, backend_facility_name, frontend_inv_qty)                                  | `/inventory/by-facility` **[N]**          |

## Ads — "is my spend working"

| Insight                                                                      | Subsection    | Tables.columns                                                                      | API                                               |
| ---------------------------------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------- |
| Spend/impressions/sales trend                                               | Chart         | `blinkit_ad_campaign_daily`(date, budget_consumed, impressions, ad_sales) summed     | `ads/performance` **[B]**                         |
| Campaign table (RoAS, spend, status)                                        | Table         | `blinkit_ad_campaigns`(name, type, status) + `blinkit_ad_campaign_daily` rollup       | `ads/campaigns` **[B]**                           |
| Budget split by campaign type                                                | Donut         | `blinkit_ad_campaign_daily`(campaign_type, budget_consumed) summed                    | `ads/performance` **[E→N]** (derive)              |
| Sponsored SOV per keyword                                                    | Table w/ bars | `blinkit_sponsored_sov`(keyword, monthly_searches, sov)                               | `ads/sov` **[B]**                                 |
| RoAS leaderboard / worst spenders                                            | Sorted cards  | `blinkit_ad_campaign_daily` rollup (ad_sales ÷ budget) ranked                         | `ads/campaigns?sort=roas` **[E→N]**               |
| Visibility plans & collections                                               | Side lists    | `blinkit_visibility_plans`, `blinkit_brand_collections`                               | `ads/visibility-plans`, `ads/collections` **[B]** |
| Blended (store) spend vs revenue                                            | KPI           | `blinkit_ad_campaign_daily`(budget) vs `blinkit_seller_sales`(mrp_value)              | fold into `analytics/overview` **[E]**            |
| **Keyword / asset performance + per-keyword RoAS**                          | Keyword table | `blinkit_ad_campaign_detail`(target, match_type, budget, direct/total_roas, …)        | `/ads/keywords` **[N]** (data ready, view pending)|

## Market / Competition — "how do I look on the shelf"

| Insight                                             | Subsection                  | Tables.columns                                                     | API                                    |
| --------------------------------------------------- | --------------------------- | ------------------------------------------------------------------ | -------------------------------------- |
| Own-brand SOV summary + trend                       | Card + line                 | `search_results`(brand_sov, scraped_at, keyword, city)             | `competition/share-of-voice` **[E]**   |
| Competitor rankings & prices                        | Table, own rows highlighted | `competitor_rankings`(competitor, position, price, keyword, city)  | `competition/rankings` **[E]**         |
| **Your rank by keyword × city** (where you're weak) | Heatmap                     | `search_results`(brand_rank, keyword, city)                        | `/competition/rank-matrix` **[N]**     |
| **Organic vs paid visibility**                      | Dual bar per keyword        | `search_results`(brand_sov) + `blinkit_sponsored_sov`(sov) on **keyword**  | `/competition/visibility` **[N]**      |
| **Price vs position** (priced out of top ranks?)    | Scatter                     | `competitor_rankings`(competitor, price, position) incl. own brand | `/competition/price-position` **[N]**  |
| **Competitor watch** (who keeps beating you)        | Ranked list                 | `competitor_rankings`(competitor, position) frequency              | `/competition/top-competitors` **[N]** |

## Scorecard — "Blinkit's view of my brand health"

| Insight                                  | Subsection              | Tables.columns                                                                                                                    | API                                    |
| ---------------------------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Weekly headline (fill rate, GMV, rank)   | KPI cards + week picker | `blinkit_scorecard_weekly`(overall, best_category JSON)                                                                           | `scorecard/weekly` **[E]**             |
| Per-category fill                        | Bars                    | `blinkit_scorecard_weekly`(categories JSON)                                                                                       | `scorecard/weekly` **[E]**             |
| Key SKUs by potential loss               | Table                   | `blinkit_scorecard_key_skus`(item_name, potential_loss, total_gmv, proxy_category)                                                | `scorecard/key-skus` **[E]**           |
| Facilities by potential loss             | Table                   | `blinkit_scorecard_facilities`(facility_name, fill_rate, potential_loss, manufacturer_rank)                                       | `scorecard/facilities` **[E]**         |
| **Fill-rate trend across weeks**         | Line                    | `blinkit_scorecard_weekly`(from_date_ist, overall) multi-week                                                                     | `/scorecard/trend` **[N]**             |
| **Fill loss → which POs** (supply story) | Drill-down              | `blinkit_scorecard_facilities`(facility_id, potential_loss) + `blinkit_pos`(facility_id, total_units_ordered, total_grn_quantity) | `/scorecard/facility/{id}/pos` **[N]** |

## Ops / Settings

| Insight                       | Subsection | Tables.columns                                                   | API                      |
| ----------------------------- | ---------- | ---------------------------------------------------------------- | ------------------------ |
| Watchlist (own + competitors) | Editor     | watchlist table                                                  | `watchlist` CRUD **[E]** |
| Platform connection status    | Cards      | `platform_sessions`                                              | `platforms` **[E]**      |
| Scrape job history / failures | Table      | `scrape_jobs`(dashboard, status, records_written, error, timing) | `jobs` **[E]**           |

---

## New endpoints implied (build with their page)

**High value:** `/overview/alerts`, extend `products/{item_id}` (Product 360 + days-of-cover + city split), `/inventory/cover`, `/competition/visibility`, `/competition/rank-matrix`.

**Medium:** `/analytics/category-trend`, `/analytics/city-category`, `/inventory/availability-history`, `/inventory/by-facility`, `/competition/price-position`, `/competition/top-competitors`, `/scorecard/trend`, `/scorecard/facility/{id}/pos`, `/products/{item_id}/pos`, `/ads/keywords` _(detail data ready in `blinkit_ad_campaign_detail`; just needs the endpoint + view)_.

**Extend existing (cheap):** sort/filter params on `ads/campaigns`; blended spend-vs-revenue into `analytics/overview`.

## Suggested build order

Overview → Products/Analytics → Inventory → Ads → Competition → Scorecard → Settings.
Overview first: it forces the shared shell (client switcher, date range, KPI card,
time-series chart, paginated table) that every other page reuses, and exercises
the full round-trip on the smallest page (existing composite endpoint + one new
SQL-joined endpoint `/overview/alerts`).
