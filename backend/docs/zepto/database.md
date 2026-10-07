# Zepto Private Scraping — Database

Fifteen tables, all defined in [`app/models/zepto_seller.py`](../../app/models/zepto_seller.py).
All are private-plane: they hold data only the logged-in seller account can see. The
public plane uses the shared `search_snapshots` / `search_listings` / `sku_snapshots`
tables keyed by `mp_slug` and is not covered here.

See [architecture.md](architecture.md) for how rows get here,
[errorhandling.md](errorhandling.md) for what happens when a write half-fails.

---

## Live row counts

Measured read-only against the shared Supabase database on **2026-10-07**. Two tenants:
**Brik Oven** (`fa53082e-7e83-424d-aab9-086fe1b4c680`) and **Sereko**.

| Table | Rows | Date column | Earliest | Latest |
|---|---:|---|---|---|
| `zepto_seller_sales_summary` | 105 | `date` | 2026-07-17 | 2026-10-06 |
| `zepto_seller_sales` | 858 | `period_start` | 2026-07-17 | 2026-10-06 |
| `zepto_seller_product_city_daily` | 1,144 | `date` | 2026-08-14 | 2026-10-06 |
| `zepto_soh` | 0 | `date` (scrape day) | — | — |
| `zepto_ad_campaign_daily` | 2,672 | `date` | 2026-07-17 | 2026-10-06 |
| `zepto_ad_campaign_detail` | 0 | `date` | — | — |
| `zepto_ad_keyword_daily` | 9,994 | `date` | 2026-07-17 | 2026-10-06 |
| `zepto_ad_product_daily` | 724 | `date` | 2026-07-17 | 2026-10-06 |
| `zepto_ad_breakdown_daily` | 2,560 | `date` | 2026-07-17 | 2026-10-06 |
| `zepto_ad_campaigns` | 59 | *(current state)* | — | — |
| `zepto_ad_campaign_keywords` | 4,343 | *(current state)* | — | — |
| `zepto_po` | 503 | `po_date` | 2026-04-01 | 2026-10-07 |
| `zepto_po_items` | 2,054 | *(none)* | — | — |
| `zepto_asn` | 477 | `asn_date` | 2026-04-01 | 2026-10-06 |
| `zepto_grn` | 449 | `grn_date` | 2026-04-02 | 2026-10-06 |

`zepto_soh` and `zepto_ad_campaign_detail` are empty on purpose: both are written by code
that is built but not yet deployed (the VM still runs the older scrape). A 30-day backfill
of the detail table is planned once everything else lands.

The PO tables reach back to **April** because history was deliberately backfilled to
test whether split deliveries occur. They do — `P4739825` has two GRNs.

---

## Bookkeeping columns — identical on all fifteen

Every table carries the same set, matching the Blinkit tables so re-runs behave the
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
| `zepto_soh` | `tenant : zepto : soh : pvId : scrape_date` |
| `zepto_ad_campaign_daily` | `tenant : zepto : ad_campaign_daily : campaign_id : date` |
| `zepto_ad_campaign_detail` | `tenant : zepto : ad_campaign_detail : campaign_id : keyword : match_type : date` |
| `zepto_ad_keyword_daily` | `tenant : zepto : ad_keyword_daily : category : keyword : match_type : date` |
| `zepto_ad_product_daily` | `tenant : zepto : ad_product_daily : category : pvId : date` |
| `zepto_ad_breakdown_daily` | `tenant : zepto : ad_breakdown_daily : dimension : category : name : date` |
| `zepto_ad_campaigns` | `tenant : zepto : campaign : campaign_id` |
| `zepto_ad_campaign_keywords` | `tenant : zepto : ad_kw_bid : campaign_id : keyword : match_type` |
| `zepto_po` | `tenant : zepto : po : po_id` |
| `zepto_grn` | `tenant : zepto : grn : grn_no` |
| `zepto_asn` | `tenant : zepto : asn : asn_no` |
| `zepto_po_items` | `tenant : zepto : po_item : po_id : pvId-or-sku_code` |

Rows sharing a key are collapsed **before** they reach Postgres (`storage.py` dedupes
into a dict), because `ON CONFLICT` cannot update the same row twice in one statement.

Note the supply tables and the catalogue key on the **id alone, with no date**. A PO
scraped in April and re-scraped in September updates the same row — correct, since a
PO's status genuinely changes over its life, but **there is no history of how a PO (or a
campaign's configuration) evolved**. Only its current state.

---

## ⚠️ The traps

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

`zepto_seller_sales` is SKU × day summed over every city.
`zepto_seller_product_city_daily` splits **the same rupees** by city. Adding them
double-counts. Across every day that has both, the two agree to the rupee — which makes
the difference a free completeness check: a day whose city rows sum short is missing a city.

### 3. Readings of the moment, stored against a date

Some columns describe **the moment of the API call**, not the date on the row. Zepto's
product report returns the same stock and growth for every day a run asks about, and the
values move from one run to the next (2026-10-07: Brik Oven Sour Cream, sales days
09-29 … 10-06 all held stock 102 / week-on-week −53.16, all written by that morning's run).

| Column | Table | Truth |
|---|---|---|
| `stock_on_hand` | `zepto_seller_sales` | reading at scrape time → moving to `zepto_soh` |
| `week_on_week_growth` | `zepto_seller_sales` | reading at scrape time (settled 2026-10-07) → `zepto_soh` |
| `month_on_month_growth` | `zepto_seller_sales` | reading at scrape time (settled 2026-10-07) → `zepto_soh` |
| `status`, `is_active` | `zepto_ad_campaign_daily` | scrape-time. Four dates fetched back-to-back returned identical counts |
| `daily_budget`, `lifetime_budget`, `base_bid`, targeting, start/end dates | `zepto_ad_campaign_daily` | scrape-time — the catalogue is the current answer |
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

#### Stock and growth: `zepto_soh`, in three steps

Keyed on the sales day, a reading of the moment smears: the 8-day sales re-scrape writes
today's stock onto all 8 days, so the product page's stock trend was one flat line for the
last 8 days and lagged ~8 days before that. The fix moves them to `zepto_soh`, keyed on
the day the scrape **asked**, in three steps so the shared database never breaks:

1. **(built, migration applied 2026-10-07)** add `zepto_soh`; the scrape writes it AND
   keeps writing the old columns. Old code never touches the new table.
2. **(built 2026-10-07, not deployed)** the Products page reads stock from `zepto_soh` —
   readings from the window's first day to the morning after its last — and falls back,
   per product, to the old column where `zepto_soh` has no reading yet (so deploy day
   changes nothing; the stock trend shows real readings once a window has any).
3. drop the three columns from `zepto_seller_sales` — only once every running copy of the
   code (VM, UAT, laptops) writes `zepto_soh`; old code writes those columns, so dropping
   them first would fail its sales save.

Until step 3, `_KEEP_IF_NULL` in `storage.py` still guards the old columns: re-scraping an
older window returns **null** for them, and a plain upsert used to write that null over a
real reading, so they are COALESCEd on conflict (since 2026-08-28):

```python
_KEEP_IF_NULL = {
    "zepto_seller_sales": ("stock_on_hand", "week_on_week_growth", "month_on_month_growth"),
}
```

### 4. Two keyword tables — the brand-level one is on its way out

`zepto_ad_keyword_daily` (brand grain) covers keywords from **every** kind of campaign.
`zepto_ad_campaign_detail` (per campaign) was at first fetched only for keyword-bid PLA
campaigns — about half of Sereko's keyword spend (last 30 days: keyword PLA ₹1.94 L,
subcategory-targeted PLA ₹1.01 L, sponsored-brands Display ₹0.79 L). Since 2026-10-07 it is
fetched for **every campaign with impressions** (the report answers for all three kinds —
probed read-only on Sereko). Once the detail is backfilled and its daily sums match the
brand table, the brand table can retire. Until then: never add the two together.

---

## Table reference

### Sales

#### `zepto_seller_sales_summary` — brand × day
GMV and units for the whole brand, one row per calendar day — including zero-sale days, so
its day count is "days Zepto has data for" (the divisor the Products page's cover uses).
GMV arrives already rounded to whole rupees.

Key columns: `date`, `brand_id`, `brand_name`, `gmv`, `units`

#### `zepto_seller_sales` — SKU × day
The Products page reads this. Every scrape asks one day per call, so rows are day grain;
**`period_start`/`period_end` are part of the key** (a one-off multi-day window would make
one window row, which the services exclude with `period_start = period_end`).

Key columns: `period_start`, `period_end`, `product_variant_id`, `product_name`,
`sku_name`, `pack_size`, `unit_of_measure`, `category_name`, `subcategory_name`,
`gmv`, `qty_sold`, `sales_contribution`, `available_stores`, and — until step 3 above —
`week_on_week_growth`, `month_on_month_growth`, `stock_on_hand`.

Products table mapping: Units = `qty_sold`, Revenue = `gmv`, Stock = `stock_on_hand`
(latest reading in the window). Avg. price and cover are computed in the service layer:
average daily units divide by the days **with data**, not the window's calendar length,
and a SKU with no stock reading shows "No stock data", never "Out of stock" (P11).

Categories group by **`subcategory_name`**, not `category_name` — Zepto's
`categoryName` is one broad bucket ("Dairy, Bread & Eggs") covering every SKU on this
account.

#### `zepto_seller_product_city_daily` — SKU × city × day
The finer grain, and the only Zepto table with city **and** category on one row —
which is what the Analytics "Revenue by category & city" heatmap needs.

Zepto exposes no city dimension inside a single response, but `cityIds` filters it, so
a city split costs **one call per city**. Every run sweeps all ~145 cities for the
newest day of the window, and asks only the cities known to sell (plus any the sweep just
found) for the older days. `--all-cities` sweeps every city on every day (one-off
backfills).

#### `zepto_soh` — SKU × scrape day
Stock on hand and the two growth figures, as Zepto reported them when the scrape asked
(trap 3). One row per product per scrape day; a second run that day overwrites it. A
product appears only when it sold on some day of the run's window — Zepto's product
report omits SKUs with no sales — so absent means "no reading", never zero stock.

Key columns: `date`, `product_variant_id`, `sku_name`, `stock_on_hand`,
`week_on_week_growth`, `month_on_month_growth`

### Ads

The four daily tables plus the detail table are the same money at different resolutions.
**Pick one; never add them.**

#### `zepto_ad_campaign_daily` — campaign × day
Merges two endpoints because neither is complete: `/campaigns` has the operational
fields (budgets, base bid, targeting, status, dates), `/metrics/tabular?view=campaign_table`
has revenue and add-to-carts.

Column names follow **Zepto's** own (`spend`, `roi`) rather than Blinkit's
(`budget_consumed`, `roas`). Mapping between them belongs in the service layer.

`campaign_category` is the tab a campaign **actually appeared in** — the campaigns
endpoint ignores its `categoryType` parameter, so the scraper overwrites it from the
tabular response. A campaign with no spend appears in no tab and keeps the requested-tab
default, so **filter on it for spend analysis, not for a campaign inventory**.

A day on which every campaign was paused comes back with every metric blank. Yesterday's
blank is treated as "not computed yet" and fetched on the next run; an older blank day
we already hold spend for keeps its stored rows (a Zepto glitch); any other blank day is
saved as genuine zeros (`run.blank_ads_day`).

`roi` is Zepto's "RoAS (including FOC)"; `robas` excludes free-of-cost impressions and
is only populated by the Analytics view.

#### `zepto_ad_campaign_detail` — campaign × keyword × match type × day
Keyword performance **per campaign**, from the campaign detail page's own report
(`POST …/brands/campaigns/analytics/metrics/tabular` with `campaign_id` +
`view=keyword_table`). One call per campaign per day — a multi-day window comes back as
one total and a per-day breakdown is refused. Asked for every campaign with impressions
that day — keyword-bid PLA, subcategory-targeted PLA and Display alike (the report ignores
the tab parameter). A missing row means "no activity", never "not scraped".
Named after Blinkit's `blinkit_ad_campaign_detail`, whose rows are one window total where
these are per day. A campaign-day's rows sum to its `zepto_ad_campaign_daily` row.

`same_skus` + `other_skus` = `orders`: they are **order counts** — direct (the advertised
product) and halo (another product of the brand) — not sales.

#### `zepto_ad_keyword_daily` — keyword × match type × day × category
⚠️ **Keywords are reported per BRAND, not per campaign.** The response carries no
campaign id. The same keyword bid by two campaigns returns two identical rows; the parser
**sums** them. `ctr`/`cpc`/`cpm`/`roas` are recomputed from the summed components rather
than copied. `robas` is spend-weighted. See trap 4 for why it stays beside the detail table.

#### `zepto_ad_product_daily` — advertised SKU × category × day
Which SKUs the ad spend went to. No other endpoint reports this: the campaigns endpoint
stops at campaign level and `zepto_seller_sales` covers organic sales.

#### `zepto_ad_breakdown_daily` — bucket × category × day
Three structurally identical views in one table, distinguished by `dimension`. See
trap 1. `page` values seen: Search Page, Product Details Page, Trending Page, Category
Page. None of these views reports CTR.

### Campaign catalogue (current state, for the campaign manager)

#### `zepto_ad_campaigns` — one row per campaign
Every campaign's **current** configuration — Zepto's answer to `blinkit_ad_campaigns`.
List fields (name, status, type, budgets, dates) are written by the daily scrape and by the
campaign manager's Refresh; detail fields (city targeting, products) only by the scrape,
only for PLA campaigns, and a list-only refresh never blanks them. Landed campaign-manager
writes patch it in place.

Until 2026-10-07 it missed most **Display** campaigns: the list call sent
`campaign_category=sponsored_products`, which — unlike `categoryType` — filters, so only PLA
and swap-and-save campaigns came back (Sereko: 36 of 57; probed read-only). The parameter is
gone; the next scrape after deploy fills them in as list-only rows (Display campaigns have no
PLA detail). Until then the Ads campaigns list falls back to the daily row's status and
budget for them.

#### `zepto_ad_campaign_keywords` — campaign × keyword × match type
What each campaign bids on, with the live bid and Zepto's published minimum
(`keyword/config`). A campaign's rows are replaced whole on each detail read, so a keyword
removed in the dashboard disappears. `min_bid` NULL means "unknown", never "no floor".

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

Also carries `cgst` / `sgst` / `igst` / `cess`. One call per PO fetches the lines; a PO
whose call fails is re-checked once and then fails the run, so a PO with no lines here
genuinely has none.

---

## Joins

```sql
-- PO lines / stock → Products page. Same id, no name matching, no sku_map bridge.
zepto_po_items.product_variant_id  =  zepto_seller_sales.product_variant_id
zepto_soh.product_variant_id       =  zepto_seller_sales.product_variant_id

-- The supply chain
zepto_po.po_id  =  zepto_asn.po_id  =  zepto_grn.po_id  =  zepto_po_items.po_id
zepto_asn.asn_no  =  zepto_grn.asn_no

-- Ads
zepto_ad_campaign_detail.campaign_id    =  zepto_ad_campaign_daily.campaign_id
zepto_ad_campaign_keywords.campaign_id  =  zepto_ad_campaigns.campaign_id
```

`product_variant_id` being shared is what makes the scorecard's category-fill query
possible: `zepto_po_items` joined to `zepto_seller_sales` for `subcategory_name`.

---

## Indexes

Every time-series table has a `(tenant_id, <its date>)` index. Additionally:

| Index | On |
|---|---|
| `idx_zac_tenant` | `zepto_ad_campaigns (tenant_id)` |
| `idx_zackw_tenant_campaign` | `zepto_ad_campaign_keywords (tenant_id, campaign_id)` |
| `idx_zacdet_tenant_campaign_date` | `zepto_ad_campaign_detail (tenant_id, campaign_id, date)` |
| `idx_zabd_dimension` | `zepto_ad_breakdown_daily (tenant_id, dimension, date)` |
| `idx_zspcd_city` | `zepto_seller_product_city_daily (tenant_id, city_id, date)` |
| `idx_zpo_status` | `zepto_po (tenant_id, status)` |
| `idx_zgrn_po` / `idx_zasn_po` | `(tenant_id, po_id)` |
| `idx_zpoi_tenant_po` | `zepto_po_items (tenant_id, po_id)` |
| `idx_zpoi_pv` | `zepto_po_items (tenant_id, product_variant_id)` |

⚠️ **Index names are database-wide in Postgres**, not per table. `idx_zacd_*` was taken by
`zepto_ad_campaign_daily` when the detail table first tried it (2026-10-06) — hence
`idx_zacdet_*`. Check `pg_class` before naming a new one.

---

## Migrations

⚠️ **One shared Supabase database sits behind every branch.** A migration applied from
one branch changes the database every other branch reads, including branches whose
code has not pulled the change.

- Migrations here are **hand-written**, not autogenerated.
- Apply a migration **before** deploying code whose models declare its table.
- Applying a migration and pushing its file are one action: an applied-but-unpushed file
  leaves every other branch with "Can't locate revision".
- Two branches migrating at once split the chain; rejoin with an empty merge revision
  (`f1a8c3e5b7d2` rejoined the Zepto and Instamart lines on 2026-10-07) and `alembic
  stamp` it.

Recent Zepto migrations: `c3a9e5d7f2b1` (`zepto_ad_campaign_detail`, 2026-10-06),
`e7b2c9d4a6f3` (`zepto_soh`, 2026-10-07).
