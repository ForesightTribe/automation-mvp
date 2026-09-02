# Zepto Private Scraping — Database

Eleven tables, all defined in [`app/models/zepto_seller.py`](../../app/models/zepto_seller.py).
All are private-plane: they hold data only the logged-in seller account can see. The
public plane uses the shared `search_snapshots` / `search_listings` / `sku_snapshots`
tables keyed by `mp_slug` and is not covered here.

See [architecture.md](architecture.md) for how rows get here,
[errorhandling.md](errorhandling.md) for what happens when a write half-fails.

---

## Live row counts

Measured against the shared Supabase database on **2026-09-02**. Tenant is
**Brik Oven** (`fa53082e-7e83-424d-aab9-086fe1b4c680`) for every row.

| Table | Rows | Date column | Earliest | Latest |
|---|---:|---|---|---|
| `zepto_seller_sales_summary` | 47 | `date` | 2026-07-17 | 2026-09-01 |
| `zepto_seller_sales` | 393 | `period_start` | 2026-07-17 | 2026-09-01 |
| `zepto_seller_product_city_daily` | 166 | `date` | 2026-08-14 | 2026-09-01 |
| `zepto_ad_campaign_daily` | 459 | `date` | 2026-08-14 | **2026-08-31** |
| `zepto_ad_keyword_daily` | 1,022 | `date` | 2026-08-14 | **2026-08-31** |
| `zepto_ad_product_daily` | 133 | `date` | 2026-08-14 | **2026-08-31** |
| `zepto_ad_breakdown_daily` | 193 | `date` | 2026-08-14 | **2026-08-31** |
| `zepto_po` | 383 | `po_date` | 2026-04-01 | 2026-09-01 |
| `zepto_po_items` | 1,608 | *(none)* | — | — |
| `zepto_asn` | 368 | `asn_date` | 2026-04-01 | 2026-09-01 |
| `zepto_grn` | 361 | `grn_date` | 2026-04-02 | 2026-09-01 |

> ⚠️ **All four ad tables stop at 31-Aug** while sales and PO reach 1-Sep. The 1-Sep
> ads scrape has not been run. That is a gap in the data, not a bug.

The PO tables reach back to **April** because history was deliberately backfilled to
test whether split deliveries occur. They do — `P4739825` has two GRNs.

---

## Bookkeeping columns — identical on all eleven

Every table carries the same five, matching the Blinkit tables so re-runs behave the
same way everywhere:

| Column | Purpose |
|---|---|
| `id` | surrogate PK |
| `tenant_id` | FK `tenants.id` — **every query must filter on this** |
| `platform` | always `"zepto"` |
| `upsert_key` | **unique**. The idempotency key. See below |
| `scrape_job_id` | FK `scrape_jobs.id`, nullable — which run wrote this row |
| `scraped_at` | IST timestamp of the write |

### `upsert_key` is the whole idempotency story

Built by `make_upsert_key(*parts)`, which is just `":".join(parts)`. Every write is
`INSERT … ON CONFLICT (upsert_key) DO UPDATE`, so **re-running any window is safe** —
it overwrites in place rather than duplicating.

| Table | Key composition |
|---|---|
| `zepto_seller_sales_summary` | `tenant : zepto : seller_sales_daily : brand_id : date` |
| `zepto_seller_sales` | `tenant : zepto : seller_product_perf : pvId : period_start : period_end` |
| `zepto_seller_product_city_daily` | `tenant : zepto : seller_product_city_daily : city_id : pvId : date` |
| `zepto_ad_campaign_daily` | `tenant : zepto : ad_campaign_daily : campaign_id : date` |
| `zepto_ad_keyword_daily` | `tenant : zepto : ad_keyword_daily : category : keyword : match_type : date` |
| `zepto_ad_product_daily` | `tenant : zepto : ad_product_daily : category : pvId : date` |
| `zepto_ad_breakdown_daily` | `tenant : zepto : ad_breakdown_daily : dimension : category : name : date` |
| `zepto_po` | `tenant : zepto : po : po_id` |
| `zepto_grn` | `tenant : zepto : grn : grn_no` |
| `zepto_asn` | `tenant : zepto : asn : asn_no` |
| `zepto_po_items` | `tenant : zepto : po_item : po_id : pvId-or-sku_code` |

Rows sharing a key are collapsed **before** they reach Postgres (`storage.py` dedupes
into a dict), because `ON CONFLICT` cannot update the same row twice in one statement.

Note the supply tables key on the **document id alone, with no date**. A PO scraped in
April and re-scraped in September updates the same row — which is correct, since a PO's
status genuinely changes over its life, but it means **there is no history of how a PO
evolved**. Only its current state.

---

## ⚠️ The three traps

These are the ones that have already produced wrong numbers on a dashboard.

### 1. `zepto_ad_breakdown_daily` triple-counts

One table, three `/metrics/tabular` views stacked: `dimension` ∈ `category` | `city` |
`page`. They are three views of **the same money**.

```sql
-- WRONG — returns ~3× the real spend
select sum(spend) from zepto_ad_breakdown_daily where date = '2026-08-31';

-- RIGHT
select sum(spend) from zepto_ad_breakdown_daily
where date = '2026-08-31' and dimension = 'city';
```

### 2. Never sum sales and city-sales together

`zepto_seller_sales` is SKU × window summed over every city.
`zepto_seller_product_city_daily` splits **the same rupees** by city. Adding them
double-counts. They exist separately precisely so that mixing an all-cities row with
per-city rows in one table cannot happen.

### 3. Scrape-time columns masquerading as date facts

Some columns describe **the moment of the API call**, not the date on the row. One
scrape on 19-Aug wrote `stock_on_hand = 727` to all 28 sales-days it touched; a later
scrape wrote 466 to the same days.

| Column | Table | Truth |
|---|---|---|
| `stock_on_hand` | `zepto_seller_sales` | scrape-time snapshot |
| `week_on_week_growth` | `zepto_seller_sales` | scrape-time (**unproven** — see below) |
| `month_on_month_growth` | `zepto_seller_sales` | scrape-time (**unproven**) |
| `status`, `is_active` | `zepto_ad_campaign_daily` | scrape-time. Four dates fetched back-to-back returned identical counts |
| `daily_budget`, `lifetime_budget`, `base_bid` | `zepto_ad_campaign_daily` | scrape-time |
| `orders`, `sov`, `ad_position`, `roi` | `zepto_ad_campaign_daily` | **lifetime / trailing**, not windowed |

Genuinely per-day and safe to sum: `gmv`, `qty_sold`, `spend`, `impressions`,
`clicks`, `revenue`, `atc`, `windowed_orders`, `available_stores`,
`sales_contribution`.

> An earlier version of the model docstring listed `available_stores` and
> `sales_contribution` as snapshots. That was **wrong** — both vary day to day within
> a single scrape job (18 of 34 SKU-jobs), exactly like `gmv`.

#### `orders` vs `windowed_orders` — the one that inflated a dashboard tile

Both live on `zepto_ad_campaign_daily` and they are not the same number:

- **`orders`** comes from the campaigns endpoint and is a **lifetime** figure that
  ignores the date range entirely (1,584 for one campaign).
- **`windowed_orders`** comes from `campaign_table` and **is** the day's figure (257).

Summing `orders` per day is exactly what inflated the Units-sold tile to 5,845.

#### `_KEEP_IF_NULL` — the guard on the snapshot columns

Re-scraping an older window returns **null** for the three snapshot columns, and a
plain upsert used to write that null over a real reading. Since 2026-08-28
`storage.py` COALESCEs them on conflict:

```python
_KEEP_IF_NULL = {
    "zepto_seller_sales": ("stock_on_hand", "week_on_week_growth", "month_on_month_growth"),
}
```

These three belong in a table keyed on the **scrape job** rather than the sales date.
That is deliberately not built yet: whether the two growth columns are scrape-time
readings or window-level aggregates is **unproven**, and stored data cannot settle it —
the upsert overwrites in place, so no SKU-day has ever had two rows to compare. It
needs a live experiment.

---

## Table reference

### Sales

#### `zepto_seller_sales_summary` — brand × day
GMV and units for the whole brand, one row per calendar day. GMV arrives already
rounded to whole rupees.

Key columns: `date`, `brand_id`, `brand_name`, `gmv`, `units`

#### `zepto_seller_sales` — SKU × window
The Products page reads this. **`period_start`/`period_end` are part of the grain**:
scraping a one-day window gives daily rows; a 30-day window gives one 30-day snapshot.

Key columns: `period_start`, `period_end`, `product_variant_id`, `product_name`,
`sku_name`, `pack_size`, `unit_of_measure`, `category_name`, `subcategory_name`,
`gmv`, `qty_sold`, `sales_contribution`, `available_stores`, `week_on_week_growth`,
`month_on_month_growth`, `stock_on_hand`

Every column on the Products table comes from here: Units = `qty_sold`,
Revenue = `gmv`, Stock = `stock_on_hand` (latest in window). Avg. Price and Cover are
computed in the service layer, not stored.

Categories group by **`subcategory_name`**, not `category_name` — Zepto's
`categoryName` is one broad bucket ("Dairy, Bread & Eggs") covering every SKU on this
account.

#### `zepto_seller_product_city_daily` — SKU × city × day
The finer grain, and the only Zepto table with city **and** category on one row —
which is what the Analytics "Revenue by category & city" heatmap needs.

Zepto exposes no city dimension inside a single response, but `cityIds` filters it, so
a city split costs **one call per city**. `--all-cities` sweeps all 138; without it
only cities already known to sell are queried.

### Ads

All four are written by `zepto-ads` and all four are the same money at different
resolutions. **Pick one; never add them.**

#### `zepto_ad_campaign_daily` — campaign × day
Merges two endpoints because neither is complete: `/campaigns` has the operational
fields (budgets, base bid, targeting, status, dates), `/metrics/tabular?view=campaign_table`
has revenue, add-to-carts and keywords.

Column names follow **Zepto's** own (`spend`, `roi`) rather than Blinkit's
(`budget_consumed`, `roas`). Mapping between them belongs in the service layer.

`campaign_category` is the tab a campaign **actually appeared in** — the campaigns
endpoint ignores its `categoryType` parameter (asking for any of the three returns the
same 26 campaigns), so the scraper overwrites it from the tabular response. A campaign
with no spend appears in no tab and keeps the requested-tab default, so **filter on it
for spend analysis, not for a campaign inventory**.

`roi` is Zepto's "RoAS (including FOC)"; `robas` excludes free-of-cost impressions and
is only populated by the Analytics view.

#### `zepto_ad_keyword_daily` — keyword × match type × day × category
⚠️ **Keywords are reported per BRAND, not per campaign.** The response carries no
campaign id, so a keyword cannot be attributed to the campaign that bid on it — the one
place Blinkit's detail table is richer.

The same keyword bid by two campaigns returns two identical rows; the parser **sums**
them. `ctr`/`cpc`/`cpm`/`roas` are recomputed from the summed components rather than
copied. `robas` is spend-weighted.

#### `zepto_ad_product_daily` — advertised SKU × category × day
Which SKUs the ad spend went to. No other endpoint reports this: the campaigns endpoint
stops at campaign level and `zepto_seller_sales` covers organic sales.

#### `zepto_ad_breakdown_daily` — bucket × category × day
Three structurally identical views in one table, distinguished by `dimension`. See
trap 1. `page` values seen: Search Page, Product Details Page, Trending Page, Category
Page. None of these views reports CTR.

### Supply

The chain is `po_qty → asn_qty → grn_qty`: what Zepto ordered, what the vendor said
shipped, what actually arrived. A shortfall's location tells you which.

#### `zepto_po` — purchase order header
`status` ∈ PENDING_ACKNOWLEDGEMENT, OPEN_TO_FULFILL, … · `total_grn_qty / total_qty`
is the fill rate. `city` keeps Zepto's prefixed form (`"BLR - Bengaluru"`) uncleaned,
matching the seller portal.

#### `zepto_asn` — advance shipping notice
What the vendor declared sent.

#### `zepto_grn` — goods receipt note
What arrived. `po_qty` and `grn_qty` sit on the same row, so fill rate is readable per
receipt without joining back.

**One PO can have several GRNs.** `P4739825` has two. Any "one delivery per PO"
assumption is wrong.

#### `zepto_po_items` — SKU × PO
Two things live here and nowhere else in the system:

- **Cost price** (`unit_price` — e.g. ₹53.33 against an ₹80 `mrp`). The margin Zepto
  takes. No other Zepto endpoint reports it.
- **Per-SKU fill rate** (`grn_qty / po_qty`). The GRN table gives fill rate per
  *delivery*; this gives it per *product* — which is how it emerged that two SKUs were
  halved while two others in the **same** delivery were accepted in full.

Also carries `cgst` / `sgst` / `igst` / `cess`.

---

## Joins

```sql
-- PO lines → Products page. Same id, no name matching, no sku_map bridge.
zepto_po_items.product_variant_id  =  zepto_seller_sales.product_variant_id

-- The supply chain
zepto_po.po_id  =  zepto_asn.po_id  =  zepto_grn.po_id  =  zepto_po_items.po_id
zepto_asn.asn_no  =  zepto_grn.asn_no
```

`product_variant_id` being shared is what makes the scorecard's category-fill query
possible: `zepto_po_items` joined to `zepto_seller_sales` for `subcategory_name`.

---

## Indexes

Every table has a `(tenant_id, <its date>)` index. Additionally:

| Index | On |
|---|---|
| `idx_zabd_dimension` | `zepto_ad_breakdown_daily (tenant_id, dimension, date)` |
| `idx_zspcd_city` | `zepto_seller_product_city_daily (tenant_id, city_id, date)` |
| `idx_zpo_status` | `zepto_po (tenant_id, status)` |
| `idx_zgrn_po` / `idx_zasn_po` | `(tenant_id, po_id)` |
| `idx_zpoi_tenant_po` | `zepto_po_items (tenant_id, po_id)` |
| `idx_zpoi_pv` | `zepto_po_items (tenant_id, product_variant_id)` |

---

## Migrations

⚠️ **One shared Supabase database sits behind every branch.** A migration applied from
one branch changes the database every other branch reads, including branches whose
code has not pulled the change. Coordinate before running one.

Migrations here are **hand-written**, not autogenerated.

---

## Known display bugs (open)

Not database faults, but they surface as wrong-looking data:

- `zepto_products.py:145` renders NULL `stock_on_hand` as `0`, which the UI then
  labels **"Out of stock"**.
- Cover **doubles** when the selected window includes a day that was never scraped.
- The Overview tile labelled "Active campaigns" actually counts campaigns **with
  spend**, which is why it reads 7 when the dashboard shows 3 ACTIVE.
