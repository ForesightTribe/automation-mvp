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

Platform sessions — logging Foresight **into** Blinkit and Zepto. (Not app-user auth;
that is `app/routes/auth.py`.) Full design: [platform-auth.md](platform-auth.md).

**No browser is launched and no human is needed.** All three dashboards authenticate over
plain HTTP, and the magic link / OTP is read from the shared auth inbox.

Every command below is **generic over the registry** — the platform is an argument, not a
command. Adding Zepto needed no CLI change at all.

### First time for a tenant — store the credentials

```
python -m cli auth credentials set blinkit        --tenant <tenant_id> --email ops@brand.com
python -m cli auth credentials set blinkit_seller --tenant <tenant_id> --email ops@brand.com
```

Blinkit is passwordless (magic link / OTP), so no password is stored. **Zepto is not** —
it wants email + password *and* an emailed OTP, so it takes `--password`, which prompts
hidden and encrypts at rest with the same Fernet key as sessions:

```
python -m cli auth credentials set zepto --tenant <tenant_id> --email ops@brand.com --password
python -m cli auth credentials list --tenant <tenant_id>      # never shows the password
python -m cli auth credentials remove zepto --tenant <tenant_id>
```

### Log in

```
python -m cli auth login blinkit        --tenant <tenant_id>
python -m cli auth login blinkit_seller --tenant <tenant_id>
python -m cli auth login zepto          --tenant <tenant_id>
```

Unattended by default: it requests the secret, reads it from the auth inbox, and stores
the session — about 15–20 seconds, no typing. Add `--manual` to paste the link/OTP
yourself (useful if the mailbox is unavailable, or for a first login you want to watch).

`auth blinkit` and `auth blinkit-seller` still work as aliases for the two commands above.

### Day-to-day

```
python -m cli auth status  --tenant <tenant_id>          # every platform + health + last error
python -m cli auth probe   blinkit --tenant <tenant_id>  # is the session ACTUALLY alive
python -m cli auth refresh blinkit --tenant <tenant_id>  # extend it, no email needed
python -m cli auth refresh-all      --tenant <tenant_id> # what the auth.refresh job runs
python -m cli auth reset   blinkit --tenant <tenant_id>  # clear the circuit breaker
python -m cli auth platforms                            # registry + mail-rule status
```

⚠️ **Refresh does not apply to Zepto.** Zepto exposes no refresh/rotate endpoint —
`refreshToken` is null in every response — so `auth refresh zepto` does nothing and
`refresh-all` reports it as `not_refreshable` and **exits 0**. That is correct output, not
a failure. Zepto's JWT expires at **local midnight IST** (not after a fixed duration), so
it is re-logged-in daily instead — see the `auth.login` schedule below.

⚠️ **Zepto allows ONE session per user.** A new login server-side revokes the previous
one, in both directions: our login evicts a human's dashboard, and their login kills our
session mid-run. So a Zepto session can be dead long before `expires_at` — `probe` is the
only way to know, and `status` alone will mislead you.

**`status` vs `probe`:** `status` reports what was last _recorded_; `probe` checks the
platform right now (one API call, no browser). A session can read `active` and be dead —
that gap is what let the seller scrape fail silently for weeks. When in doubt, `probe`.

### You rarely need any of this

Scrapers call `ensure()` internally: load → probe → refresh → re-login, doing the least
work that yields a working session. **An expired session repairs itself**, so `auth login`
is for the first login of a new tenant, or after something genuinely broke.

A daily `auth.refresh` job keeps refreshable sessions warm so they never reach expiry:

```
python -m cli schedules add --name "Auth refresh daily" --type auth.refresh     --cron "10 6 * * *" --tenant <tenant_id>
```

**Zepto instead schedules a LOGIN**, because it has nothing to refresh. This is the one
exception to the rule in [platform-auth.md](platform-auth.md) that logins are never
scheduled:

```
python -m cli schedules add --name "Zepto daily login" --type auth.login          --cron "5 0 * * *" --tenant <tenant_id> --catchup platform=zepto
```

Just **after** midnight, for two reasons: the JWT dies at 23:59:59 IST, so a 23:50 login
would buy a ten-minute session; and since every Zepto login evicts whoever is on the
dashboard, midnight is when that costs a human the least. `--catchup` matters here — a
missed login means no session all day, where a missed refresh self-heals.

### When a login fails

Auto-login suspends itself after 3 consecutive **login** failures (ordinary expiry does
not count) — it would otherwise hammer a login endpoint from one datacenter IP and bury a
broken config in noise. `auth status` shows the count and the last error. After fixing the
cause:

```
python -m cli auth reset blinkit --tenant <tenant_id>
```

A run that dies for auth reasons exits with code **3**, which the job runner records as
`jobs.error='auth_expired'` — so auth failures are filterable in Cloud Logging rather than
hiding among anonymous `exit_1`s.

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
collections, and visibility plans. Each covers the whole `--from`/`--to` window — so a
30-day backfill is one pass, not 30 runs.

Since V7 it also pulls each campaign's **configuration**: city targeting, budget, pacing,
spend-to-date, and Blinkit's published **bid range per keyword** (the floor a bid rule may
not go under). Two extra calls per campaign — the keyword one takes the whole keyword list
at once, so it does not grow with keyword count, and campaigns with no keyword targeting
skip it entirely. Cost ≈ `2 + 4·N` (N = campaign count); ~14 min for 63 campaigns, up from
~7.5. ⚠️ Unlike the metric pulls, configuration is fetched for **every** campaign including
`DRAFT`/`SCHEDULED`/`UNDER_REVIEW` — those have no metrics but they do have keywords,
cities and floors, and a just-created campaign is the one someone is about to automate.

`--no-save` prints two extra tables for this: **Targeting & budget floor** (region, cities,
pacing, budget, spend) and **Keyword bid ranges** (live bid vs Blinkit's min/max/suggested,
flagging any live bid that sits below the published minimum).

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

Per-tenant and config-driven. The store catalog and each tenant's
keywords/coverage live in a workbook (`config.xlsx`); the scraper reads them from
the DB. `cities.py` is not used.

**Marketplace.** Every public command takes `--marketplace/-m`, defaulting to
`blinkit` — so every command line below works unchanged. **Blinkit is the only
wired marketplace today**; an unwired or unknown value fails fast and scrapes
nothing. Each marketplace has its **own** catalog, its own coverage rows, and its
own engine; coordinates are never shared between platforms. See [zepto.md](zepto.md).

**1. Configure — `cli sync`.** `config.xlsx` has three sheets:

| Sheet       | Columns                                                                                    | What it is                                                                                                                                                                                                                                                                 |
| ----------- | ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `locations` | `mp, merchant_id, city, state, region, pincode, lat, lon, active, location_name, address`  | that marketplace's **express** store catalog (keyed on `mp` + `merchant_id`); `lat/lon` is the probe point. `mp` is optional, blank → `blinkit`. Longtail/super_longtail hubs are NOT here — they are discovered from scrape responses. See [darkstores.md](darkstores.md) |
| `brands`    | `tenant, brand, relationship (own\|competitor), keywords, aliases, keyword_cap, brand_cap` | per-tenant keywords + brands to track; the two caps are per-scrape tunables (own rows only, optional). Shared across marketplaces                                                                                                                                          |
| `coverage`  | `mp, tenant, city`                                                                         | which cities a tenant scrapes on which marketplace (all that marketplace's stores in each listed city). `mp` blank → `blinkit`                                                                                                                                             |

> ⚠️ **`--prune` only deletes within the marketplaces the file mentions** — a
> workbook with no Zepto rows can never prune Zepto. But a workbook whose `mp`
> column is blank on non-Blinkit rows reads them as Blinkit and will propose
> deleting the real Blinkit catalog. Always `--dry-run` first; a non-zero
> `locations` deletion is a stop-and-check.

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
python -m cli locations list [-m blinkit] [--city delhi] [--tenant <id>]   # catalog, or a tenant's coverage
python -m cli watchlist list --tenant <id>                                # a tenant's brands + keywords
```

There are **two complementary scrapes**, run as separate commands (own SoV/rank vs
own complete inventory). Both reuse one browser and a concurrent worker pool
(Blinkit selects the store from lat/lon headers, so one session serves many stores).

> ⚠️ **Both public scrapes write to a local SQLite staging file, not to Postgres.**
> Push them afterwards with `cli scrape load` (see 2c). A scraped-but-unloaded file is
> the one new failure mode — `cli scrape staged` lists anything pending. Full rationale
> in [staging.md](staging.md).

**2a. Keyword scrape — `cli scrape public-run`.** Every category keyword × covered
store → SoV/rank + declared competitors. Stages rows destined for `search_snapshots` +
`search_listings`.

```bash
python -m cli scrape public-run --tenant <id>                  # full run (new staging file)
python -m cli scrape public-run --tenant <id> -m blinkit       # pick the marketplace (default blinkit)
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
_guarantees_ coverage of every own SKU's price/stock/inventory, closing the gap
where an own product doesn't rank in a category-keyword search.

```bash
python -m cli scrape public-skus --tenant <id>                 # full run (new scrape_job)
python -m cli scrape public-skus --tenant <id> -m blinkit      # pick the marketplace (default blinkit)
python -m cli scrape public-skus --tenant <id> --resume        # continue an interrupted run
python -m cli scrape public-skus --tenant <id> --city delhi    # one city
python -m cli scrape public-skus --tenant <id> --brand-cap 48  # override brand_cap
python -m cli scrape public-skus --tenant <id> --workers 5     # concurrent pool size (default 5)
python -m cli scrape public-skus --all                         # every active tenant
```

**2c. Push to Postgres — `cli scrape staged` / `load` / `discard`.**

```bash
python -m cli scrape staged                      # every staging file + quality signals
python -m cli scrape staged --pending            # only what isn't in the DB yet
python -m cli scrape load --dry-run              # what would be pushed
python -m cli scrape load --file 145458          # push one (Ref from `staged`)
python -m cli scrape load --all                  # push every pending file, oldest first
python -m cli scrape discard --file 145458       # bin a bad run without loading it
```

`staged` shows **Stores** (done/total) and **Err** so a bad run is obvious:

```
Date         Time    Kind     Stores      Rows      Err   State           Ref
2026-07-19   14:53   skus     2,059/2,059  35,802     1   ok · loaded     145345
2026-07-18   09:12   search     500/2,059     100   847   failed · …      091203
```

Each file loads in **one all-or-nothing transaction** — a failure writes nothing, so
rerunning is always safe. With several files pending, bare `load` refuses and makes
you pass `--all` or `--file`; **`--all` refuses outright if any pending run didn't
finish cleanly**, so a crashed run can't be swept in unnoticed. A partial run is never
auto-skipped though — 500 of 2,059 stores is still 500 stores of real data, and only
you can judge that. Loaded files are kept (last 5 per tenant per kind) then pruned.

**Common behaviour (both scrapes).** Each fresh run is a new staging file — run
freely. `--resume` picks up the tenant's last unloaded, unfinished run of that type,
**skipping already-scraped stores** (keyword scrape: by keyword+store; SKU scrape: by
store); it reads the staging file, so resume works even while the database is
unreachable. `--workers N` runs N isolated browser contexts on one browser (~5–6 is a
good IP balance; drop to 3 if Cloudflare throttles) — note the scrape holds **no DB
connections at all**, so the pooler cap no longer bounds this. Transient failures are
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

| Table              | Written by    | Data                                                                                                                                           |
| ------------------ | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_snapshots` | `public-run`  | Per (tenant, keyword, store, scrape): brand rank, share-of-voice %, total results                                                              |
| `search_listings`  | `public-run`  | Per product in the result page: brand, price, MRP, discount %, in-stock, inventory, position, `extra` (group_id, merchant_id, unit, category…) |
| `sku_snapshots`    | `public-skus` | Per (own product × location × scrape), keyed on `platform_product_id`: name, price, MRP, discount %, in-stock, inventory, rating, `is_combo`   |

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
`explorer_runs` record (status + live progress) and saves an `.xlsx` to `out/`
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

| Option                 | Default                 | Notes                                                          |
| ---------------------- | ----------------------- | -------------------------------------------------------------- |
| `--brand` / `-b`       | (required)              | Focus brand (name or slug)                                     |
| `--keyword` / `-k`     | —                       | Comma-separated keywords (required unless `--mode catalog`)    |
| `--city` / `-c`        | all catalog cities      | Comma-separated; must exist in the darkstore catalog           |
| `--competitors`        | discover all            | Comma-separated whitelist; empty = keep every competitor found |
| `--aliases`            | brand                   | Comma-separated brand-name variants for matching               |
| `--marketplace` / `-m` | `blinkit`               | Only Blinkit is wired today                                    |
| `--mode`               | `keyword`               | `keyword` \| `catalog` \| `both`                               |
| `--catalog`            | off                     | Sugar — also scrape the own catalog (folds into `--mode`)      |
| `--sample`             | 50                      | Locations sampled per city (evenly spread)                     |
| `--full`               | off                     | Census — every catalog location (ignores `--sample`)           |
| `--workers` / `-w`     | 5                       | Concurrent browser workers                                     |
| `--cap`                | 12                      | Per-keyword result cap override                                |
| `--brand-cap`          | 60                      | Catalog brand-query cap override                               |
| `--label`              | —                       | Human label stored on the run                                  |
| `--tenant` / `-t`      | —                       | Optional attribution to a client (does **not** scope storage)  |
| `--output` / `-o`      | `out/<brand>_<ts>.xlsx` | Workbook path                                                  |

**Workbook** — rendered by the shared exports writer, so it looks and reads like
`cli export public`: Contents · How to read this · Run Overview · Search Term
Scorecard · Geography · Competitor Landscape · Price & Discount · Availability ·
Own Catalogue (catalog mode) · then Captured — Searches / Products / Own
Catalogue / Locations.

Explorer counts **locations searched**, not dark stores: it samples probe points
and never resolves them to shops, so its numbers are not comparable with the
store-grain figures in `cli export public`. The glossary sheet says so.

- Only cities already in `marketplace_locations` are reachable (add them via `cli sync`).
- Ephemeral: nothing in `search_snapshots` / `search_listings` / `sku_snapshots` — only the
  `explorer_runs` record + the `.xlsx`.
- Instamart/Zepto are registered but not yet wired; selecting them fails fast.

---

## Campaign Manager (`cm`)

Automates Blinkit ad **budgets** and keyword **bids** (v2). Two engines:

- **Budget scheduler** — sets a campaign's daily budget from time/day rules (elevated during a window, back to a default otherwise).
- **Bid optimizer** — a ~15-min control loop that nudges a keyword's CPM to hold a target search position.

**Rules are the source of truth.** You create rules (`cm rules …`); a **reconciler** compiles them into `job_schedules` rows; the runner fires the engines on schedule. See [campaign-manager.md](campaign-manager.md) for the design.

**Two ways to run every engine** (same as `cli scrape …` vs `jobs run scrape.…`):

| Path      | Command                                              | Use                                   |
| --------- | ---------------------------------------------------- | ------------------------------------- |
| Direct    | `python -m cli cm budget-scheduler -t <id>`          | dev / manual / dry-run testing        |
| Scheduler | `python -m cli jobs run cm.budget_scheduler -t <id>` | production (queue + lanes, on the VM) |

> ⚠️ **Dry-run is the default; nothing touches Blinkit unless the tenant is armed (`cm arm`) AND the run carries `--live`.** The engines read real budgets/positions in dry-run but write nothing. Going live is a deliberate per-tenant switch — see "Go live — arm the tenant" below. Engine reads open a browser + use the tenant's session, so run them where the VM would — locally is fine for dry-run testing. Never run the _plain_ `cli runner start` locally (it claims the VM's jobs and scrapes from your home IP); to drive the full queue → schedule → engine loop on a laptop, use **`cli runner start --only-cm`**, which serves only the campaign-manager lanes and fires only `cm.*` schedules (see the "Local Campaign-Manager testing" section of [jobs-runbook.md](jobs-runbook.md)).

### Timing model (rules)

Both systems share the same timing shapes:

| Shape                      | How                                                                            | Example                                     |
| -------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------- |
| **Recurring daily window** | `--start-time`/`--end-time` (+ optional `--days`, `--start-date`/`--end-date`) | boost 4pm–11pm every Fri/Sat/Sun this month |
| **Continuous (all day)**   | omit the times, set a date range                                               | around-the-clock for a 2-day sale           |
| **One-time span**          | `--once --date` (+ times)                                                      | a single night, 6pm–2am                     |
| **Overnight**              | set end ≤ start time (e.g. `16:00`→`02:00`)                                    | window that crosses midnight                |

**Overnight tails belong to the start day**: a Sun 16:00–02:00 rule runs to **Mon 02:00**, and `--days friday,saturday,sunday` still covers Sunday's tail. `--days` is the weekday filter (empty = every day); it applies to budget and bid.

### Manage rules — `cm rules …`

```bash
# Budget: create a schedule (container) for a campaign, optionally with one inline rule
python -m cli cm rules add-budget-schedule -t <id> --campaign <cid> --default-budget 300 \
    --name "Weekend nights" \
    --budget 1500 --days "friday,saturday,sunday" --start-time 16:00 --end-time 02:00 \
    --start-date 2026-07-31 --end-date 2026-08-30

# Budget: add more rules to an existing schedule (id from `cm rules list`)
python -m cli cm rules add-budget-rule --schedule <sid> --budget 2000 --once --date 2026-08-15 --start-time 10:00 --end-time 14:00

# Bid: chase position 3 for a keyword, measured at a specific store (lat/lon)
python -m cli cm rules add-bid -t <id> --campaign <cid> --keyword "goli soda" \
    --target 3 --min-bid 20 --max-bid 120 --lat 12.97 --lon 77.57 \
    --days "friday,saturday,sunday" --start-time 16:00 --stop-time 02:00

python -m cli cm rules list   -t <id>              # budget schedules (+rules) and bid rules
python -m cli cm rules remove-budget --schedule <sid>
python -m cli cm rules remove-bid    --rule <hex>  # full id from `cm rules list`
```

**Budget** (`add-budget-schedule` / `add-budget-rule`):

| Flag                          | Notes                                                                          |
| ----------------------------- | ------------------------------------------------------------------------------ |
| `--campaign`                  | Blinkit campaign id (schedule)                                                 |
| `--default-budget`            | ₹ applied when no rule matches (schedule)                                      |
| `--name` / `--campaign-name`  | labels                                                                         |
| `--budget`                    | ₹ the rule applies (rule; on `add-budget-schedule` it creates one inline rule) |
| `--start-time` / `--end-time` | daily window `HH:MM` IST (end ≤ start = overnight)                             |
| `--days`                      | `"friday,saturday,sunday"` (empty = every day)                                 |
| `--start-date` / `--end-date` | recurring date range `YYYY-MM-DD`                                              |
| `--once` / `--date`           | one-time span on a single date (mutually exclusive with the recurring flags)   |

**Bid** (`add-bid`) — all of the above timing flags (with `--stop-time`/`--stop-date` instead of `--end-*`), plus:

| Flag                      | Notes                                                                                                     |
| ------------------------- | --------------------------------------------------------------------------------------------------------- |
| `--keyword`               | search keyword to chase                                                                                   |
| `--target`                | target sponsored position (e.g. `3`)                                                                      |
| `--min-bid` / `--max-bid` | CPM floor / ceiling (₹)                                                                                   |
| `--lat` / `--lon`         | store to **measure** position at (position is per-store; find one via `cli locations list --city <slug>`) |
| `--location` / `--brand`  | store label / brand-name fallback for product matching                                                    |
| `--match-type`            | `EXACT` (default) or `BROAD`                                                                              |

> One bid rule per (campaign, keyword) — the bid is campaign-wide; `--lat/--lon` only chooses where you measure.

### Reconcile — rules → schedules

After any rule change, compile the rules into `job_schedules` so the runner fires the engines:

```bash
python -m cli cm reconcile -t <id>            # DRY: preview the schedule diff, writes nothing
python -m cli cm reconcile -t <id> --live     # write job_schedules (create/update/delete)
```

Here `--live` means "actually write **`job_schedules`**" (our own table) — reconcile **never** touches Blinkit. It's idempotent: re-running with unchanged rules is a no-op. (The V4 API will enqueue this for you on every edit.)

### Run the engines (dry-run testing)

```bash
python -m cli cm budget-scheduler -t <id>          # reads real budget → "would set ₹X" → writes nothing
python -m cli cm bid-optimizer    -t <id>          # reads live position → "would bid ₹Y" → writes nothing
python -m cli cm bid-optimizer    -t <id> --reset  # end-of-window: de-escalate closed keywords → min_bid (no scrape)
```

Add `--live` to actually write to Blinkit (only takes effect once the tenant is **armed** — see below). History lands in `cm_run_log` (only real changes — no-op/hold rows go to Cloud Logging); bid runtime (last position/CPM) in `cm_bid_runtime`. `cm sync-campaign-data` is a stub.

**`--reset`** is the end-of-window mode: it sets each just-closed keyword's bid back to its `min_bid` (no position scrape), so a bid the optimizer pushed up doesn't keep spending high overnight. The reconciler fires this automatically at each window's stop time — you rarely run it by hand.

### Go live — arm the tenant (the cutover)

The whole automated loop is **dry by default**. Arming is a per-tenant switch (`cm_platform_accounts.live_armed`) that makes the reconciler stamp `--live` onto the engine schedules and the API's set-budget/reset pass live — so scheduled runs and UI actions write to Blinkit for real.

```bash
python -m cli cm set-advertiser -t <id> --id 19802   # one-time: the Blinkit ad-account id (required to arm)
python -m cli cm arm            -t <id>              # ⚡ ARM: set live_armed + reconcile → schedules carry --live
python -m cli cm advertiser     -t <id>              # verify: "LIVE writes: ⚡ ARMED"
python -m cli cm disarm         -t <id>              # back to dry (reconciles the --live off)
```

`cm arm` refuses if no advertiser is set (live writes would be rejected anyway). It auto-reconciles, so existing schedules pick up `--live` immediately. Reversible any time with `cm disarm`.

### Worked example — a solo dry-run pass

```bash
python -m cli cm rules add-budget-schedule -t <id> --campaign <cid> --default-budget 300 \
    --budget 1500 --start-time 16:00 --end-time 02:00 --days "friday,saturday,sunday" \
    --start-date 2026-07-31 --end-date 2026-08-30
python -m cli cm rules add-bid -t <id> --campaign <cid> --keyword "goli soda" \
    --target 3 --min-bid 20 --max-bid 120 --lat 12.97 --lon 77.57 \
    --start-time 16:00 --stop-time 02:00 --days "friday,saturday,sunday"
python -m cli cm rules list        -t <id>
python -m cli cm reconcile         -t <id> --live      # rules → job_schedules
python -m cli cm budget-scheduler  -t <id>             # dry: would-set budgets
python -m cli cm bid-optimizer     -t <id>             # dry: would-bid CPMs
python -m cli cm rules remove-budget --schedule <sid>  # teardown
python -m cli cm rules remove-bid    --rule <hex>
```

### One-off manual controls

Outside the rule engine — act on a single campaign right now. All are dry-run
unless `--live`, except `status`, which is read-only.

```bash
python -m cli cm status         -t <id> --campaign <cid>   # live state: status, budget, bids, dates
python -m cli cm set-budget     -t <id> --campaign <cid> --budget 5000
python -m cli cm set-activation -t <id> --campaign <cid> --status paused|running
python -m cli cm stop           -t <id> --campaign <cid>   # shorthand for --status paused
python -m cli cm restart        -t <id> --campaign <cid>   # shorthand for the reverse
python -m cli cm sync-campaign-data -t <id>                # refresh the keyword/product cache
```

Two more rule commands not shown above:

```bash
python -m cli cm rules set-stop-after-window --schedule <sid> --on|--off
python -m cli cm rules remove-budget-rule --rule <hex>   # drop ONE rule, keep its schedule
```

**The job queue and scheduler have their own reference.** `jobs run|list|logs|types`,
`schedules add|list|show|update|enable|disable|remove` and `runner start` are all
documented in [jobs.md](jobs.md) (design) and [jobs-runbook.md](jobs-runbook.md)
(full command reference, troubleshooting) — they are not repeated here.

---

## Export — reports & raw data (`export`)

Turns **stored** data into files. Nothing here scrapes: for an on-demand scrape of
any brand see `explore` above. Full design in [exports.md](exports.md).

Two artifacts, deliberately separate — the report is a readable client deliverable,
the raw pull is a data dump. One 7-day window of a mid-size client is ~300k rows /
79 MB, which is why it never rides along with the report.

### The client report — `export public`

A 13-sheet workbook: a cover, a plain-English glossary, then shelf presence
(overall / per product / per city / per store), the work queue, the availability
trend, price spread, and the search sheets (visibility, the position grid,
competitors, price vs market).

```bash
python -m cli export public -t <tenant-uuid>                      # latest week with data
python -m cli export public -t <uuid> --from 2026-08-01 --to 2026-08-07
python -m cli export public -t <uuid> --city bengaluru --kind combo
python -m cli export public -t <uuid> --sections summary,rank_grid -o pitch.xlsx
```

| Option              | Meaning                                                                                                                                                                                                                 |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-t, --tenant`      | Client id (**required**) — `cli tenant list`                                                                                                                                                                            |
| `--from` / `--to`   | Inclusive dates. Omit both and it uses **the last 7 days that have data**, not the last 7 days from today — public scrapes are weekly, so a today-anchored window often lands after the last scrape and returns nothing |
| `-c, --city`        | One city at a time (multi-city sections are not built)                                                                                                                                                                  |
| `--kind`            | `main` (default) · `combo` · `all` — combos are stocked selectively, so they are reported apart                                                                                                                         |
| `-m, --marketplace` | Restrict to one marketplace                                                                                                                                                                                             |
| `--sections`        | Comma-separated keys; default is every public section                                                                                                                                                                   |
| `--label`           | Free text printed on the cover                                                                                                                                                                                          |
| `-o, --output`      | Output path (default `out/<Client>_public_<end-date>.xlsx`)                                                                                                                                                             |

```bash
python -m cli export sections     # every section key, its group and glossary terms
python -m cli export sample       # render a fixture workbook — no database needed
```

`export sample` exists to judge the look and catch rendering regressions in
seconds; it uses invented data and touches no database.

### Raw data — `export raw`

The underlying rows as **CSV**, one file per table, on demand. CLI only: this is
never bundled into the report and will not sit behind the future download button.

```bash
python -m cli export raw -t <uuid> --dry-run          # count first — always
python -m cli export raw -t <uuid>                    # write the CSVs
python -m cli export raw -t <uuid> --tables listings --limit 5000
```

| Table key  | File                        | What it is                                                                |
| ---------- | --------------------------- | ------------------------------------------------------------------------- |
| `sku`      | `own_products_by_store.csv` | One row per own product per dark store per scrape                         |
| `listings` | `search_listings.csv`       | Every product seen in a search, yours and competitors'. The biggest table |
| `searches` | `searches.csv`              | One row per search at one probe point                                     |
| `stores`   | `store_catalogue.csv`       | The dark-store catalogue (not date-scoped)                                |

| Option                             | Meaning                                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------------------------- |
| `-t, --tenant`                     | Client id (**required**)                                                                    |
| `--from` / `--to`                  | Same defaulting as `export public`                                                          |
| `--tables`                         | Comma-separated keys; default all four                                                      |
| `-c, --city` / `-m, --marketplace` | Narrow the pull                                                                             |
| `--limit`                          | Cap rows per table — for a quick sample                                                     |
| `--include-extra`                  | Include the scraper's untyped `extra` payload (mostly image URLs; roughly triples the file) |
| `--dry-run`                        | Count and stop, writing nothing                                                             |
| `-o, --out`                        | Output directory (default `out/<Client>_raw_<from>_<to>/`)                                  |

Row counts always print before anything is written — the volume is the thing worth
knowing before you commit to it. CSV is deliberate: at this size a styled workbook
is the wrong container, and Excel opens CSV natively.

> **Legacy:** `python export_to_excel.py <tenant_id>` still dumps the **private**
> marketing/seller tables (ad campaigns, sales, POs, SOH, scorecard) to a workbook.
> It predates this subsystem and is kept until a private report replaces it.

---

## Ads automation (`ads`)

Runs on the VM as jobs; see [jobs.md](jobs.md).

```bash
python -m cli ads budget-scheduler      # apply budget rules for the current IST slot
python -m cli ads bid-optimizer         # one pass of the bid optimizer
python -m cli ads sync-campaign-data    # cache campaign keywords + products in the DB
```

---

## Maintenance & monitoring (`maint`, `monitor`)

```bash
python -m cli maint log-cleanup    # prune old per-run job logs under logs/jobs/
python -m cli monitor heartbeat    # assert every enabled schedule ran, and disk is OK
```

`monitor heartbeat` logs an ERROR per problem (which raises a Cloud Logging alert)
and exits non-zero if anything is wrong. Both run as scheduled jobs on the VM —
see [jobs-runbook.md](jobs-runbook.md).

---

## Notes

- `.env` must have `DATABASE_URL` (Supabase Session Pooler URL) and `ENCRYPTION_KEY`
- Run `alembic upgrade head` once to create all tables before first use
- Create a tenant with `cli tenant create` before running any auth or private scrape commands
- Store credentials (`auth credentials set`) and run `auth login` **once** per tenant per
  platform. After that scrapers self-heal via `ensure()` — you do not run `auth` before
  each `scrape`
- Unattended login needs `AUTH_INBOX_USER` + `AUTH_INBOX_APP_PASSWORD` in `.env`; without
  them `auth login` falls back to prompting (`--manual`)
- `cli sync` and `scrape public --save` auto-create brand + marketplace rows (`ensure_refs`) — no manual seeding
- Public scraping is config-driven: `cli sync --file config.xlsx` before `cli scrape public-run` / `public-skus`
- The two public scrapes are independent commands with independent `scrape_job`s — run them on separate cadences (e.g. `public-skus` daily, `public-run` weekly)
