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

1. **SKU/keyword-level ad attribution — PLANNED.** `ad_campaigns` today has no
   `item_id`/`keyword` (only campaign-level: budget_consumed, impressions, atcs,
   roas, reach). **We are improving the scraper to capture campaign detail —
   keyword performance metrics + per-keyword RoAS.** Once landed, this unlocks
   keyword-level ad ROI views (marked *(needs campaign-detail scraper)* below).
   SKU-level RoAS still depends on whether campaign detail exposes targeted SKUs.
2. **Private sales ↔ public availability can't be joined.** Private = `item_id` +
   `item_name`; public = `sku`/`platform_product_id` + `product_name`. No shared
   key (public has no UPC either). A unified "this SKU: selling + on-shelf +
   ranked" view needs an **`sku_map` table** (`item_id` ↔ `brand_slug`+`sku`),
   populated manually or by fuzzy name match. Until then, keep private and public
   views **separate** rather than faking a join.

Legend: **[E]** existing endpoint · **[N]** new endpoint to build · **[E→N]** extend existing.

---

## Overview — "what needs my attention today"

| Insight | Subsection | Tables.columns | API |
|---|---|---|---|
| Headline KPIs (rev, units, SKUs, spend, impressions) | KPI strip | `blinkit_seller_sales`(qty_sold, mrp_value) + `ad_campaigns`(budget_consumed, impressions) | `analytics/overview` **[E]** |
| Revenue/units trend | Trend chart | `blinkit_seller_sales`(date, mrp_value, qty_sold) | `analytics/revenue` **[E]** |
| **Attention feed** — OOS, low stock, fill-loss, stale data | Alerts list | `inventory_depth`(in_stock) + `blinkit_soh`(frontend_inv_qty) + `blinkit_scorecard_key_skus`(potential_loss) + `scrape_jobs`(status) | `/overview/alerts` **[N]** |
| Data freshness ("sales last synced 2d ago") | Status chips | `scrape_jobs`(dashboard, status, finished_at) | `jobs` **[E]** |

## Sales & Analytics — "where is revenue coming from"

| Insight | Subsection | Tables.columns | API |
|---|---|---|---|
| Revenue/units over time | Main chart | `blinkit_seller_sales`(date, mrp_value, qty_sold) | `analytics/revenue` **[E]** |
| Top SKUs by revenue | Ranked bars/table | `blinkit_seller_sales`(item_id, item_name, mrp_value, qty_sold) | `analytics/top-skus` **[E]** |
| Revenue by city | Bar list / map | `blinkit_seller_sales`(city_name, mrp_value) | `analytics/sales-by-city` **[E]** |
| Revenue by category | Donut | `blinkit_seller_sales`(category, mrp_value) | `analytics/sales-by-category` **[E]** |
| **Category trend over time** | Stacked area | `blinkit_seller_sales`(date, category, mrp_value) | `/analytics/category-trend` **[N]** |
| **City × category matrix** | Heatmap | `blinkit_seller_sales`(city_name, category, mrp_value) | `/analytics/city-category` **[N]** |

## Products — "per-SKU deep dive" (richest composed view)

| Insight | Subsection | Tables.columns | API |
|---|---|---|---|
| SKU list with sales + latest stock | Table | `blinkit_seller_sales` + `blinkit_soh`(frontend_inv_qty, backend_inv_qty) | `products` **[E]** |
| **Product 360**: sales trend + stock + days-of-cover | Detail page | `blinkit_seller_sales`(date, qty_sold, mrp_value) + `blinkit_soh`(backend_inv_qty, frontend_inv_qty per facility) | extend `products/{item_id}` **[E→N]** |
| **Days of cover** = stock ÷ avg daily sales | Detail KPI + list sort | `blinkit_soh`(frontend_inv_qty) ÷ `blinkit_seller_sales`(qty_sold avg) | `/inventory/cover` **[N]** |
| SKU sold across which cities | Detail breakdown | `blinkit_seller_sales`(city_name, qty_sold) WHERE item_id | extend `products/{item_id}` **[N]** |
| SKU's PO history | Detail tab | `blinkit_po_items`(po_number, units_ordered, total_amount) WHERE item_id | `/products/{item_id}/pos` **[N]** |

## Inventory — "what's out or about to be"

| Insight | Subsection | Tables.columns | API |
|---|---|---|---|
| Stock on hand, low-first | Table | `blinkit_soh`(item_id, backend_facility_name, backend_inv_qty, frontend_inv_qty) | `inventory/soh` **[E]** |
| **Reorder list** (days-of-cover ascending) | Table | `blinkit_soh` ÷ `blinkit_seller_sales` velocity | `/inventory/cover` **[N]** |
| Fill rate / PO vs GRN / potential loss | Summary + facility table | `blinkit_scorecard_facilities`(total_po_quantity, total_grn_quantity, fill_rate, potential_loss) | `inventory/fill-rate` **[E]** |
| Public shelf availability (own brand OOS) | Table, city/mp filter | `inventory_depth`(sku, product_name, in_stock, depth, city, mp_slug) | `inventory/availability` **[E]** |
| **Stock-out timeline** (when/how long OOS) | Trend | `inventory_depth`(scraped_at, in_stock) per sku | `/inventory/availability-history` **[N]** |
| **Facility stock heatmap** (SKU × facility low spots) | Matrix | `blinkit_soh`(item_id, backend_facility_name, frontend_inv_qty) | `/inventory/by-facility` **[N]** |

## Ads — "is my spend working"

| Insight | Subsection | Tables.columns | API |
|---|---|---|---|
| Spend/impressions trend | Chart | `ad_performance_summary`(date, budget_consumed, impressions) | `ads/performance` **[E]** |
| Campaign table (RoAS, ATCs, status) | Table | `ad_campaigns`(name, type, status, budget_consumed, impressions, atcs, roas, reach) | `ads/campaigns` **[E]** |
| Budget split by campaign type | Donut | `ad_performance_summary`(budget_distribution JSON) | `ads/performance` **[E]** |
| Sponsored SOV per keyword | Table w/ bars | `sponsored_sov`(keyword, monthly_searches, sov) | `ads/sov` **[E]** |
| RoAS leaderboard / worst spenders | Sorted cards | `ad_campaigns`(name, budget_consumed, roas) ranked | `ads/campaigns?sort=roas` **[E→N]** |
| Visibility plans & collections | Side lists | `visibility_plans`, `brand_collections` | `ads/visibility-plans`, `ads/collections` **[E]** |
| Blended spend vs total revenue (NOT per-SKU) | KPI | `ad_campaigns`(budget_consumed) vs `blinkit_seller_sales`(mrp_value) | fold into `analytics/overview` **[E]** |
| **Keyword performance + per-keyword RoAS** *(needs campaign-detail scraper)* | Keyword table | new campaign-detail columns (keyword, spend, roas) | `/ads/keywords` **[N]** |

## Market / Competition — "how do I look on the shelf"

| Insight | Subsection | Tables.columns | API |
|---|---|---|---|
| Own-brand SOV summary + trend | Card + line | `search_results`(brand_sov, scraped_at, keyword, city) | `competition/share-of-voice` **[E]** |
| Competitor rankings & prices | Table, own rows highlighted | `competitor_rankings`(competitor, position, price, keyword, city) | `competition/rankings` **[E]** |
| **Your rank by keyword × city** (where you're weak) | Heatmap | `search_results`(brand_rank, keyword, city) | `/competition/rank-matrix` **[N]** |
| **Organic vs paid visibility** | Dual bar per keyword | `search_results`(brand_sov) + `sponsored_sov`(sov) on **keyword** | `/competition/visibility` **[N]** |
| **Price vs position** (priced out of top ranks?) | Scatter | `competitor_rankings`(competitor, price, position) incl. own brand | `/competition/price-position` **[N]** |
| **Competitor watch** (who keeps beating you) | Ranked list | `competitor_rankings`(competitor, position) frequency | `/competition/top-competitors` **[N]** |

## Scorecard — "Blinkit's view of my brand health"

| Insight | Subsection | Tables.columns | API |
|---|---|---|---|
| Weekly headline (fill rate, GMV, rank) | KPI cards + week picker | `blinkit_scorecard_weekly`(overall, best_category JSON) | `scorecard/weekly` **[E]** |
| Per-category fill | Bars | `blinkit_scorecard_weekly`(categories JSON) | `scorecard/weekly` **[E]** |
| Key SKUs by potential loss | Table | `blinkit_scorecard_key_skus`(item_name, potential_loss, total_gmv, proxy_category) | `scorecard/key-skus` **[E]** |
| Facilities by potential loss | Table | `blinkit_scorecard_facilities`(facility_name, fill_rate, potential_loss, manufacturer_rank) | `scorecard/facilities` **[E]** |
| **Fill-rate trend across weeks** | Line | `blinkit_scorecard_weekly`(from_date_ist, overall) multi-week | `/scorecard/trend` **[N]** |
| **Fill loss → which POs** (supply story) | Drill-down | `blinkit_scorecard_facilities`(facility_id, potential_loss) + `blinkit_pos`(facility_id, total_units_ordered, total_grn_quantity) | `/scorecard/facility/{id}/pos` **[N]** |

## Ops / Settings

| Insight | Subsection | Tables.columns | API |
|---|---|---|---|
| Watchlist (own + competitors) | Editor | watchlist table | `watchlist` CRUD **[E]** |
| Platform connection status | Cards | `platform_sessions` | `platforms` **[E]** |
| Scrape job history / failures | Table | `scrape_jobs`(dashboard, status, records_written, error, timing) | `jobs` **[E]** |

---

## New endpoints implied (build with their page)

**High value:** `/overview/alerts`, extend `products/{item_id}` (Product 360 + days-of-cover + city split), `/inventory/cover`, `/competition/visibility`, `/competition/rank-matrix`.

**Medium:** `/analytics/category-trend`, `/analytics/city-category`, `/inventory/availability-history`, `/inventory/by-facility`, `/competition/price-position`, `/competition/top-competitors`, `/scorecard/trend`, `/scorecard/facility/{id}/pos`, `/products/{item_id}/pos`, `/ads/keywords` *(after campaign-detail scraper)*.

**Extend existing (cheap):** sort/filter params on `ads/campaigns`; blended spend-vs-revenue into `analytics/overview`.

## Suggested build order

Overview → Products/Analytics → Inventory → Ads → Competition → Scorecard → Settings.
Overview first: it forces the shared shell (client switcher, date range, KPI card,
time-series chart, paginated table) that every other page reuses, and exercises
the full round-trip on the smallest page (existing composite endpoint + one new
SQL-joined endpoint `/overview/alerts`).
