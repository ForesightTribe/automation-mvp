# CLI Reference

Run from `backend/` with the virtual environment active.

```bash
cd automation-mvp/backend
python -m cli --help
```

---

## Account

An **account** is the subscriber org that logs in. Create it first; it also makes
the first user (an `admin`). Add more users (teammates) to the same account so
they can see all of its clients' data — `member` by default, or `--admin`.

```bash
# Create an account + its first admin user (prompts for password)
python -m cli account create --name "Dobra" --admin-email anita@dobra.com

# Add another user to an existing account (prompts for password)
python -m cli account add-user --account <account-id> --email teammate@dobra.com
python -m cli account add-user --account <account-id> --email lead@dobra.com --name "Team Lead" --admin

python -m cli account list                       # show all accounts + their UUIDs
```

Data is account-scoped: any user under an account sees all of that account's
clients. Role (`member`/`admin`) only gates Settings/admin UI, not data.

---

## Tenant

Create a tenant once before using any private (auth-required) scraper. The printed UUID is what you pass as `--tenant` in all subsequent commands.

```bash
python -m cli tenant create --name "My Brand"   # creates a tenant row, prints UUID
python -m cli tenant list                        # show all tenants and their UUIDs
```

---

## Auth

### Blinkit marketing (`brands.blinkit.com`) — magic link

```
python -m cli auth blinkit --tenant <tenant_id>
```

Browser opens → fill email → paste magic link from email into terminal.

### Blinkit seller (`partnersbiz.com`) — OTP

```
python -m cli auth blinkit-seller --tenant <tenant_id>
```

Browser opens → fills email → enter 6-digit OTP from email into terminal.

Used for all seller commands: `blinkit-seller` (sales + PO + SOH) and `blinkit-scorecard`.

### Check session status

```
python -m cli auth status --tenant <tenant_id>
```

---

## Scrape

### Blinkit marketing dashboard

```bash
# Daily run — defaults to the last 7 days (catches late metric revisions)
python -m cli scrape blinkit --tenant <tenant_id>

# Backfill a window (one pass) — e.g. last 30 days
python -m cli scrape blinkit --tenant <tenant_id> --from 2026-05-25 --to 2026-06-24

python -m cli scrape blinkit --tenant <tenant_id> --no-save   # dry run, print only
```

One pass fetches the campaign list, then for **each campaign** its **daily** metric
series and its **keyword / recommendation breakdown**, plus sponsored SOV, brand
collections, and visibility plans. Cost ≈ `1 + 2·N` API calls (N = campaign count),
each covering the whole `--from`/`--to` window — so a 30-day backfill is one pass,
not 30 runs.

| Option             | Default    | Notes                                               |
| ------------------ | ---------- | --------------------------------------------------- |
| `--from`           | 7 days ago | Window start `YYYY-MM-DD`. Use to backfill history. |
| `--to`             | today      | Window end `YYYY-MM-DD`.                            |
| `--save/--no-save` | `--save`   | `--no-save` prints counts without writing.          |

**What it saves:**

| Table                        | Granularity                                     | Data                                                                                                                       |
| ---------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `blinkit_ad_campaign_daily`  | per campaign × **day**                          | budget, impressions, ATC, qty sold, ad sales, RoAS — the metric **backbone**                                               |
| `blinkit_ad_campaigns`       | per campaign (metadata)                         | name, type, status, start/end, infinite — the catalog                                                                      |
| `blinkit_ad_campaign_detail` | per campaign × keyword/asset (window aggregate) | keyword/recommendation: impressions, budget, CPM, direct/indirect ATC & sales, qty, new users, position, direct/total RoAS |
| `blinkit_sponsored_sov`      | per keyword (snapshot)                          | monthly searches, your sponsored share of voice %                                                                          |
| `blinkit_brand_collections`  | snapshot                                        | static/dynamic product collections you've set up                                                                           |
| `blinkit_visibility_plans`   | snapshot                                        | paid slot bookings: name, type, budget, dates, status                                                                      |

Idempotent: daily rows upsert on `campaign_id + date`, detail on
`campaign_id + target + snapshot_date`, so re-running a window updates in place.
Account totals (spend/impressions) and budget-split-by-type are derived by
summing `blinkit_ad_campaign_daily` — there is no separate performance-summary
table. RoAS is always recomputed as `Σ ad_sales ÷ Σ budget` over the window.

---

### Blinkit seller — sales + PO + SOH

```bash
# Daily run — scrapes all three: sales (yesterday), PO, and stock on hand
python -m cli scrape blinkit-seller --tenant <tenant_id>

# Sales only
python -m cli scrape blinkit-seller --tenant <tenant_id> --sales

# Sales with date range (historical backfill)
python -m cli scrape blinkit-seller --tenant <tenant_id> --sales --from 2026-06-01 --to 2026-06-05

# PO only
python -m cli scrape blinkit-seller --tenant <tenant_id> --po

# PO with custom rolling window (default: 90 days)
python -m cli scrape blinkit-seller --tenant <tenant_id> --po --po-days-back 60

# SOH only
python -m cli scrape blinkit-seller --tenant <tenant_id> --soh

# Dry run
python -m cli scrape blinkit-seller --tenant <tenant_id> --no-save
```

**Sales** — scrapes day-by-day over the given range (default: yesterday). Each day upserted by `item_id + city + date`; re-running the same date updates in place.

**PO** — scrapes a rolling window of POs by issue date. Upserted by `po_number` so re-running updates state without duplicating. SKU line items fetched only for POs not already in the DB — first run is expensive, subsequent runs fetch only new POs.

**SOH** — scrapes today's stock levels per SKU per facility. Upserted by `item_id + facility_id + date`; re-running the same day updates in place.

**What it saves:**

| Table                          | Data                                                                     |
| ------------------------------ | ------------------------------------------------------------------------ |
| `blinkit_seller_sales`         | Per-day per-SKU per-city: qty sold, MRP value                            |
| `blinkit_seller_sales_summary` | Per-day totals: distinct SKUs, categories, top selling item              |
| `blinkit_pos`                  | Each PO with state, city, facility, units, amount + SKU line items       |
| `blinkit_po_snapshots`         | Rolling 90-day summary: raised/scheduled/cancelled/expired, total amount |
| `blinkit_soh`                  | Per-SKU per-facility: backend inventory qty, frontend inventory qty      |

---

### Blinkit seller — scorecard (fill rates)

```bash
# Standard run — fetches the most recently published week
python -m cli scrape blinkit-scorecard --tenant <tenant_id>

# Specific week — pass the Monday start date
python -m cli scrape blinkit-scorecard --tenant <tenant_id> --week 2026-06-09

# Dry run
python -m cli scrape blinkit-scorecard --tenant <tenant_id> --no-save
```

Blinkit publishes each week's scorecard on the following Monday, so the default always fetches last week's data (current Monday − 7 days). Intended to run once per week. Uses the same `blinkit_seller` session — no separate auth needed.

The `--week` date must be a Monday (`YYYY-MM-DD`). A non-Monday will return empty data from Blinkit.

**What it saves:**

| Table                          | Data                                                                    |
| ------------------------------ | ----------------------------------------------------------------------- |
| `blinkit_scorecard_weekly`     | Overall fill rate, weighted fill rate, PO/GRN qty, GMV, rank — per week |
| `blinkit_scorecard_facilities` | Per-facility fill rate, potential loss, rank                            |
| `blinkit_scorecard_key_skus`   | SKUs with highest potential revenue loss, with GMV and category         |

---

### Public product search (Blinkit) — no login required

Per-tenant and config-driven (Blinkit only; Instamart/Zepto out of scope). The
darkstore catalog and each tenant's keywords/coverage live in a workbook
(`config.xlsx`); the scraper reads them from the DB. `cities.py` is not used.

**1. Configure — `cli sync`.** `config.xlsx` has three sheets:

| Sheet | Columns | What it is |
|---|---|---|
| `locations` | `merchant_id, city, state, region, pincode, lat, lon, active, location_name, address` | the global **express** darkstore catalog (keyed on `merchant_id`); `lat/lon` is the probe point. Longtail/super_longtail hubs are NOT here — they are discovered from scrape responses. See [darkstores.md](darkstores.md) |
| `brands` | `tenant, brand, relationship (own\|competitor), keywords, aliases, keyword_cap, brand_cap` | per-tenant keywords + brands to track; the two caps are per-scrape tunables (own rows only, optional) |
| `coverage` | `tenant, city` | which cities a tenant scrapes (all stores in each listed city) |

The two caps (own rows only; blank → code default): **`keyword_cap`** bounds the
keyword scrape (`public-run`, default 48), **`brand_cap`** bounds the targeted
brand scrape (`public-skus`, default 60). Precedence for both: CLI flag > config
value > default.

```bash
python -m cli sync --file config.xlsx --template   # write a starter workbook
python -m cli sync --file config.xlsx --dry-run     # preview changes
python -m cli sync --file config.xlsx               # apply (upsert; --prune also deletes rows missing from the file)
```

Edit the workbook, re-sync. Tenants must already exist (`cli tenant create`); the
workbook references them by name. Inspect what synced:

```bash
python -m cli locations list [--city delhi] [--tenant <id>]   # catalog, or a tenant's coverage
python -m cli watchlist list --tenant <id>                    # a tenant's brands + keywords
```

There are **two complementary scrapes**, run as separate commands (own SoV/rank vs
own complete inventory). Both reuse one browser and a concurrent worker pool
(Blinkit selects the store from lat/lon headers, so one session serves many stores).

**2a. Keyword scrape — `cli scrape public-run`.** Every category keyword × covered
store → SoV/rank + declared competitors. Writes `search_snapshots` + `search_listings`.

```bash
python -m cli scrape public-run --tenant <id>                  # full run (new scrape_job)
python -m cli scrape public-run --tenant <id> --resume         # continue an interrupted run
python -m cli scrape public-run --tenant <id> --city delhi     # one city
python -m cli scrape public-run --tenant <id> --keyword "soda" # one keyword
python -m cli scrape public-run --tenant <id> --cap 30         # override keyword_cap (Blinkit pages 12 at a time)
python -m cli scrape public-run --tenant <id> --workers 5      # concurrent pool size (default 5)
python -m cli scrape public-run --all                          # every active tenant
```

**2b. Targeted own-SKU scrape — `cli scrape public-skus`.** Searches the tenant's
**brand name** and paginates its whole catalog to `brand_cap`, own-brand only →
`sku_snapshots` (one row per product × store, keyed on `product_id`). This
*guarantees* coverage of every own SKU's price/stock/inventory, closing the gap
where an own product doesn't rank in a category-keyword search.

```bash
python -m cli scrape public-skus --tenant <id>                 # full run (new scrape_job)
python -m cli scrape public-skus --tenant <id> --resume        # continue an interrupted run
python -m cli scrape public-skus --tenant <id> --city delhi    # one city
python -m cli scrape public-skus --tenant <id> --brand-cap 48  # override brand_cap
python -m cli scrape public-skus --tenant <id> --workers 5     # concurrent pool size (default 5)
python -m cli scrape public-skus --all                         # every active tenant
```

**Common behaviour (both).** Each fresh run is a new `scrape_job` — run freely.
`--resume` picks up the tenant's last incomplete job of that type, **skipping
already-scraped stores** (keyword scrape: by keyword+store; SKU scrape: by store);
commits are incremental so a crash keeps its progress. `--workers N` runs N
isolated browser contexts on one browser, each with its own DB connection (~5–6 is
a good IP/DB balance; drop to 3 if Cloudflare throttles). Transient failures are
retried with backoff and each fetch has a hard timeout; a persistent failure logs a
single line with the reason — e.g. `HTTP 403 · non-JSON body (Cloudflare?)` (the
throttle signal — reduce `--workers`) vs `HTTP 400` (a genuinely bad store/keyword,
ignorable in small numbers).

**Ad-hoc single scrape — `cli scrape public`.** One keyword at one location for
quick checks (no config needed). `--save` writes per-tenant rows and needs `--tenant`.

```bash
python -m cli scrape public --keyword "soda" --brand "dobra" --platform blinkit --city delhi          # print only
python -m cli scrape public --keyword "soda" --brand "dobra" --tenant <id> --city delhi --save        # persist
```

**What they save:**

| Table | Written by | Data |
|---|---|---|
| `search_snapshots` | `public-run` | Per (tenant, keyword, store, scrape): brand rank, share-of-voice %, total results |
| `search_listings`  | `public-run` | Per product in the result page: brand, price, MRP, discount %, in-stock, inventory, position, `extra` (group_id, merchant_id, unit, category…) |
| `sku_snapshots`    | `public-skus` | Per (own product × location × scrape), keyed on `platform_product_id`: name, price, MRP, discount %, in-stock, inventory, rating, `is_combo` |

> **Metrics count serviceable locations, not stores.** The catalog lat/long is a
> delivery point several stores can share, so all public read endpoints count
> distinct `(lat,lon)`. See [public-glossary.md](public-glossary.md) (Reach vs
> Distribution, Main vs Combo).

**3. Map private ↔ public — `cli sku-map`.** Bridges the private seller `item_id`
to the public `platform_product_id` (different Blinkit id systems, no shared UPC),
built by normalized name-matching. Powers the Products page public panel.

```bash
python -m cli sku-map build --tenant <id>                 # auto-match + write a review workbook (sku_map.xlsx)
#   → open the workbook, fill platform_product_id for any unmatched rows
python -m cli sku-map apply --tenant <id> --file sku_map.xlsx   # apply manual corrections (method='manual', preserved on rebuild)
```

Run `build` **after** `public-skus` (it matches against `sku_snapshots`). Re-runnable;
preserves manual mappings.

---

## Explore — on-demand custom scrape → Excel (agency-facing)

`cli explore` runs an **ad-hoc** public scrape for **any** brand / keywords /
competitors / cities and writes a multi-sheet Excel report. Unlike `public-run`,
it is **not** tied to a tenant's watchlist and **writes nothing** to the fact
tables — it's for profiling a prospect or a one-off deep-dive. Each run logs one
`explorer_runs` record (status + live progress) and saves an `.xlsx` to `exports/`
(gitignored). Full design: [explorer.md](explorer.md).

```bash
# Keyword scrape: SoV / rank / competitors for a brand across sampled locations
python -m cli explore --brand dobra --keyword "goli soda,nimbu soda" --city bengaluru

# Add the own-brand catalog (per-SKU price/stock) with --catalog
python -m cli explore --brand dobra --keyword "cola,soda" --city bengaluru,mumbai --catalog

# Narrow the competitor set, widen the sample, label the run
python -m cli explore --brand dobra --keyword "soda" --competitors "paper boat,7up" \
  --sample 80 --label "Dobra Q3 pitch"

# Full census of a city (not a sample); custom output path
python -m cli explore --brand dobra --keyword "soda" --city bengaluru --full -o dobra.xlsx
```

| Option | Default | Notes |
| --- | --- | --- |
| `--brand` / `-b` | (required) | Focus brand (name or slug) |
| `--keyword` / `-k` | — | Comma-separated keywords (required unless `--mode catalog`) |
| `--city` / `-c` | all catalog cities | Comma-separated; must exist in the darkstore catalog |
| `--competitors` | discover all | Comma-separated whitelist; empty = keep every competitor found |
| `--aliases` | brand | Comma-separated brand-name variants for matching |
| `--marketplace` / `-m` | `blinkit` | Only Blinkit is wired today |
| `--mode` | `keyword` | `keyword` \| `catalog` \| `both` |
| `--catalog` | off | Sugar — also scrape the own catalog (folds into `--mode`) |
| `--sample` | 50 | Locations sampled per city (evenly spread) |
| `--full` | off | Census — every catalog location (ignores `--sample`) |
| `--workers` / `-w` | 5 | Concurrent browser workers |
| `--cap` | 12 | Per-keyword result cap override |
| `--brand-cap` | 60 | Catalog brand-query cap override |
| `--label` | — | Human label stored on the run |
| `--tenant` / `-t` | — | Optional attribution to a client (does **not** scope storage) |
| `--output` / `-o` | `exports/<brand>_<ts>.xlsx` | Workbook path |

**Workbook** (insight sheets first, raw last): Run Overview · Keyword Scorecard ·
Geography · Competitor Landscape · Price & Discount · Availability · Own Catalog
(catalog mode) · then Raw — Snapshots / Listings / Catalog SKUs / Locations.

- Only cities already in `marketplace_locations` are reachable (add them via `cli sync`).
- Ephemeral: nothing in `search_snapshots` / `search_listings` / `sku_snapshots` — only the
  `explorer_runs` record + the `.xlsx`.
- Instamart/Zepto are registered but not yet wired; selecting them fails fast.

---

## Export to Excel

Export all scraped data for a tenant to a multi-sheet Excel workbook.

```bash
python export_to_excel.py <tenant_id>
python export_to_excel.py <tenant_id> --output report.xlsx
```

Sheets produced: Ad Performance Summary, Ad Campaigns, Sponsored SOV, Brand Collections, Visibility Plans, Seller Sales, Sales Summary, Purchase Orders, PO Line Items, PO Snapshots, Stock On Hand, Scorecard Weekly, Scorecard Categories, Scorecard Facilities, Scorecard Key SKUs.

---

## Notes

- `.env` must have `DATABASE_URL` (Supabase Session Pooler URL) and `ENCRYPTION_KEY`
- Run `alembic upgrade head` once to create all tables before first use
- Create a tenant with `cli tenant create` before running any auth or private scrape commands
- Run `auth` before `scrape` for each tenant
- `cli sync` and `scrape public --save` auto-create brand + marketplace rows (`ensure_refs`) — no manual seeding
- Public scraping is config-driven: `cli sync --file config.xlsx` before `cli scrape public-run` / `public-skus`
- The two public scrapes are independent commands with independent `scrape_job`s — run them on separate cadences (e.g. `public-skus` daily, `public-run` weekly)
