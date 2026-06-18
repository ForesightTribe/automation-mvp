# CLI Reference

Run from `backend/` with the virtual environment active.

```bash
cd automation-mvp/backend
python -m cli --help
```

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
python -m cli scrape blinkit --tenant <tenant_id>
python -m cli scrape blinkit --tenant <tenant_id> --no-save   # dry run, print only
```
Scrapes campaigns, sponsored SOV, brand collections, and visibility plans. No date range — always current state.

**What it saves:**

| Table | Data |
|---|---|
| `ad_performance_summary` | Total budget consumed, impressions, budget split by campaign type |
| `ad_campaigns` | Per-campaign: name, type, status, budget, impressions, ATCs, RoAS, reach |
| `sponsored_sov` | Per keyword: monthly searches, your sponsored share of voice % |
| `brand_collections` | Static/dynamic product collections you've set up |
| `visibility_plans` | Paid slot bookings: name, type, budget, dates, status |

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

| Table | Data |
|---|---|
| `blinkit_seller_sales` | Per-day per-SKU per-city: qty sold, MRP value |
| `blinkit_seller_sales_summary` | Per-day totals: distinct SKUs, categories, top selling item |
| `blinkit_pos` | Each PO with state, city, facility, units, amount + SKU line items |
| `blinkit_po_snapshots` | Rolling 90-day summary: raised/scheduled/cancelled/expired, total amount |
| `blinkit_soh` | Per-SKU per-facility: backend inventory qty, frontend inventory qty |

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

| Table | Data |
|---|---|
| `blinkit_scorecard_weekly` | Overall fill rate, weighted fill rate, PO/GRN qty, GMV, rank — per week |
| `blinkit_scorecard_facilities` | Per-facility fill rate, potential loss, rank |
| `blinkit_scorecard_key_skus` | SKUs with highest potential revenue loss, with GMV and category |

---

### Public product search — no login required

Scrapes consumer-facing search results from Blinkit, Instamart (Swiggy), and Zepto. No auth needed.

```bash
# Basic — scrapes all 3 platforms for default city (Bengaluru)
python -m cli scrape public --keyword "cola" --brand "dobra"

# Specific platform
python -m cli scrape public --keyword "cola" --brand "dobra" --platform blinkit
python -m cli scrape public --keyword "cola" --brand "dobra" --platform instamart
python -m cli scrape public --keyword "cola" --brand "dobra" --platform zepto

# Different city
python -m cli scrape public --keyword "cola" --brand "dobra" --city mumbai

# Scrape all zones within a city (different dark-store areas = different rankings)
python -m cli scrape public --keyword "cola" --brand "dobra" --city bengaluru --all-zones

# Brand name aliases — used to match products to your brand
python -m cli scrape public --keyword "cola" --brand "dobra" --aliases "dobra,dobra cola,dobradrink"

# Save results to PostgreSQL
python -m cli scrape public --keyword "cola" --brand "dobra" --save
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--keyword` / `-k` | required | Search term (e.g. `"cola"`, `"sunflower oil"`) |
| `--brand` / `-b` | required | Brand slug used to classify your products vs competitors |
| `--platform` / `-p` | `all` | `blinkit` \| `instamart` \| `zepto` \| `all` |
| `--city` / `-c` | `bengaluru` | City slug — see `scraper/utils/cities.py` for full list |
| `--all-zones` | off | Scrape every zone defined for the city (6–12 per city) |
| `--aliases` | none | Comma-separated brand name variants for product matching |
| `--save` | off | Write results to PostgreSQL `search_results` table |

**Supported cities:** bengaluru, mumbai, delhi, hyderabad, pune, chennai, kolkata, ahmedabad, jaipur, surat, lucknow, kochi, chandigarh, nagpur, bhopal, indore, visakhapatnam, patna — full list in `scraper/utils/cities.py`.

**What it saves (per keyword per city/zone):**

| Table | Data |
|---|---|
| `search_results` | Brand rank (best position), share of voice %, top 8 competitors with counts, brand product list |

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
- `--save` on `scrape public` auto-creates brand and marketplace rows — no manual seeding needed
