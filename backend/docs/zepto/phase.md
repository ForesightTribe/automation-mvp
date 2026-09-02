# Zepto Private Scraping — Phases

Where this work has been, where it is, and what is left. Ticket **FST-10**.
Client **Brik Oven** (`fa53082e-7e83-424d-aab9-086fe1b4c680`).

Status as of **2026-09-02**.

---

## At a glance

| Phase | What | Status |
|---|---|---|
| 0 | Recon — can the seller portal be reached at all | ✅ Done |
| 1 | Browser login + session health | ⚰️ **Superseded & deleted** |
| 2 | Sales scraper | ✅ Done |
| 3 | Ads scraper | ✅ Done |
| 4 | PO / ASN / GRN + derived scorecard | ✅ Done |
| 5 | Migration onto shared `platform_auth` | ✅ Done |
| 6 | Dashboard integration | 🔶 Mostly done — 4 files uncommitted |
| 7 | **Ship to `main`** | ❌ **Not started — blocks Phase 8** |
| 8 | **Run unattended on the VM** | ❌ Not started |
| 9 | Hardening / known gaps | ❌ Open |

---

## Phase 0 — Recon ✅

Established that the Zepto brand console (`brands.zepto.co.in`) exposes sales, ads and
supply data behind one login, talking to `fcc.zepto.co.in`.

Key findings that shaped everything after:
- **One console covers ads *and* sales**, so Zepto needs a single auth slug where
  Blinkit needs two (`blinkit` + `blinkit_seller`).
- The JWT is a plain cookie value — **much simpler than Blinkit's Firebase/IndexedDB
  setup**, so nothing needs extracting from a browser profile.
- Zepto publishes **no scorecard page**. Any fill-rate view has to be derived.

---

## Phase 1 — Browser login ⚰️ Superseded

*2026-08-17 → 2026-08-19. Deleted 2026-09-01.*

The original approach: Zepto's login rejected headless browsers (401 on the sign-in
call across Chromium, Firefox and WebKit), so login ran **headful under Xvfb** and a
human typed the 4-digit OTP.

Shipped and worked. Then it was replaced wholesale by Phase 5.

**Deleted in `6bcfcfc`:** `seller/auth.py` (137 lines), `seller/session_health.py`
(53), `seller/selectors.py` (26), and the `cli auth zepto-seller` command.

> ⚠️ [`docs/zepto-auth.md`](../../../docs/zepto-auth.md) at the repo root still
> documents **this phase**. It tells you to install Xvfb and run a command that no
> longer exists. It should be rewritten or deleted — it is the single most misleading
> document about this system.

---

## Phase 2 — Sales ✅

*2026-08-19 → 2026-08-30*

`cli scrape zepto-sales` → `zepto_seller_sales_summary`, `zepto_seller_sales`,
`zepto_seller_product_city_daily`.

What it took beyond the obvious:
- **Dynamic id discovery** (`6148c6b`) — no hardcoded brand, city or category ids.
- **The per-city split needs one call per city** (`b08bb48`, `e745853`). Zepto exposes
  no city dimension inside a response, but `cityIds` filters it.
- **Snapshot columns pinned down** (`df2de65`) — `stock_on_hand` and the two growth
  columns describe the *call*, not the date. Re-scrapes were blanking real readings;
  `_KEEP_IF_NULL` now COALESCEs them.
- **A day Zepto has not computed yet** (`fe20250`) returns a structurally different
  response with no `headers` block. Now raises `NoDataYet` instead of
  `Scrape failed: 'headers'`.
- **Tables renamed to match Blinkit's convention** (`ef65141`), and a redundant
  `sales_city_daily` dropped (`4a2e97d`).

---

## Phase 3 — Ads ✅

*2026-08-20 → 2026-08-22*

`cli scrape zepto-ads` → four tables.

The hard parts were all semantic, not technical:
- **Two endpoints must be merged** — `/campaigns` has budgets/status/targeting but no
  revenue; `/metrics/tabular` has revenue but none of the operational fields.
- **`categoryType` is ignored** by `/campaigns` — all three tabs return the same 26
  campaigns. Only `/metrics/tabular` partitions, so `campaign_category` is overwritten
  from the tabular response.
- **`orders` is a LIFETIME figure** that ignores the date range. Summing it per day is
  what inflated the Units-sold tile to 5,845. `windowed_orders` is the day's.
- **`sov` and `ad_position` are trailing-7-day**, not windowed — Zepto's own column is
  literally titled "SOV - last 7 day".
- **`zepto_ad_breakdown_daily` stacks three views** of the same money. Summing it
  unfiltered returns ~3× real spend.

---

## Phase 4 — Supply chain + scorecard ✅

*2026-08-27 → 2026-09-02*

`cli scrape zepto-po` → `zepto_po`, `zepto_asn`, `zepto_grn`, `zepto_po_items`, plus
`app/services/zepto_scorecard.py`.

- Three tables, not one, because a PO, its shipment and its receipt are three grains
  and each can exist without the others.
- **`po_items` is a second pass** — the list endpoint returns `itemsCount` but not the
  lines.
- **The 5xx retry** (`2621828`) — the PO endpoints fail ~4 times in 18 attempts.
  Before this, one blip discarded an entire dataset silently.
- **The scorecard scrapes nothing** (`adbf505`, `5e4ed73`) — derived in SQL, no table,
  no migration. `manufacturer_rank` deliberately omitted rather than nulled.

### History backfilled to April, and what it settled

I claimed twice that split deliveries never happen — first from 82 POs, then from 283.
**Both wrong.** `P4739825` has two GRNs. That settled the "can we merge PO and GRN"
question in the negative.

Business findings from the backfill:
- 100% ship / **70% accept** across 356 deliveries
- **₹26.6 lakh** potential loss at cost
- Hoskote New = **59%** of all shortfall
- Breads 54–77% fill vs cheeses 98%+
- 13 of 16 expired POs are **Hyderabad — a city they do not service**

---

## Phase 5 — Onto shared `platform_auth` ✅

*2026-09-01*

Colleague's auth framework replaced the Phase-1 browser login wholesale, on his
instruction to *"take reference from zepto's budget automations… so that each
individual system is using the full capabilities of the automated auth system."*

| Before | After |
|---|---|
| headful Chromium + Xvfb | browserless REST login |
| human types the OTP | IMAP reads it from the shared inbox |
| `cli auth zepto-seller` | `cli auth login zepto` |
| session = Playwright cookies | JWT in `platform_sessions.raw` |
| per-run health check | **per-call** recovery in `ZeptoClient` |

**Verified live**: the session was evicted three times in ten minutes and the run
self-recovered each time and completed.

Commits: `84fb645` (sales + PO), `05c3ce9` / `95a7c15` (ads), `6bcfcfc` (delete the
old auth).

---

## Phase 6 — Dashboard integration 🔶

Products, Reports, Analytics, Overview and Scorecard all read Zepto data.

Done: whole-rupee formatting on Overview for Zepto only; "Stock by facility" hidden for
Zepto; FE/BE split removed from the Products stock column for Zepto (Zepto has no
front-end/back-end concept — that is Blinkit's).

**Cross-checked against Zepto's own dashboard in both directions on 29-Aug — all
matched.** An apparent mismatch traced to an unapplied date filter on their side.

### Outstanding in this phase

- **4 files uncommitted**: `ProductsTable.jsx`, `ProductDetailPage.jsx`,
  `app/schemas/product.py`, `app/services/product_service.py`
- `CityBreakdown` full-width when `FacilityStock` is hidden — offered, undecided
- Rename the Overview tile "Active campaigns" → "Campaigns with spend" (it counts
  campaigns *with spend*, which is why it reads 7 when the dashboard shows 3 ACTIVE)

---

## Phase 7 — Ship to `main` ❌ **The gate**

**The VM runs `main`. It never runs `dev`.** Verified 2026-09-02:

```
origin/main ... origin/dev   →   0 behind, 23 ahead
```

`main` today still has the **old** Zepto:

| | `main` (what the VM runs) | `dev` |
|---|---|---|
| `zepto-sales` | ✅ | ✅ |
| `zepto-ads` | ✅ | ✅ |
| `zepto-po` | ❌ missing | ✅ |
| `zepto_scorecard.py` | ❌ missing | ✅ |
| Auth | old browser `auth.py` | `platform_auth` |
| `seller/auth.py` | still present | deleted |

So `main` would try to run a login command that `dev` deleted. **Nothing Zepto can go
on the VM until this lands.**

Also outstanding: 7 unpushed commits on
`feature/zepto-auth-integration-private-data`, and 17 stale staging files to discard.

---

## Phase 8 — Unattended on the VM ❌

The box (`foresight-vm`, GCP Mumbai, `e2-standard-2`) already runs a systemd job runner
draining a Postgres queue. Blinkit marketing and seller scrape there daily and have
succeeded 7/7.

**Zepto has never run there.** Verified against the live DB: no Zepto row in
`job_schedules`, and **no Zepto job has ever been queued.**

### Gap 1 — two of three scrapers have no job type

`jobs/types.py` registers only:

```python
"scrape.zepto_seller_sales": JobTypeSpec(
    Lane.dashboard, 10 * 60, _zepto_sales,
    param_keys=("date_from", "date_to"),
)
```

There is **no** `scrape.zepto_ads` and **no** `scrape.zepto_po`. The runner can only
execute registered types, so those two are unschedulable. The one that does exist is
also missing its `label` (logs show the raw type name) and does not expose
`--all-cities`.

### Gap 2 — the box needs Playwright

Every private run launches headless Chromium **once** (~10s) to mint the WAF token,
including sales and PO which do not otherwise need one. So:

```bash
playwright install chromium            # NOT with sudo — it lands in root's cache
sudo playwright install-deps chromium  # WITH sudo
```

RAM impact is small and transient (~1 GB for ten seconds) versus Blinkit's browser
scrapes, which peak at **920–956 MB for the whole run**. Zepto is the cheapest thing
that could go on that box — but it is **not** browser-free, which an earlier reading of
the code suggested and which is wrong.

### Gap 3 — the daily login is parked, for a good reason

Zepto cannot refresh (no endpoint; JWT dies at local midnight IST), so holding a
session means logging in again daily:

```bash
cli schedules add --name "Zepto daily login" --type auth.login \
    --cron "5 0 * * *" -t <tenant> --catchup --disabled platform=zepto
```

> ⚠️ **This must stay `--disabled` until Brik Oven provisions a service user.**
> Single-session eviction means a nightly login logs the client's own team out of
> their dashboard. That is a conversation to have with the client, not something to
> engineer around.

### The ordered path

1. Merge `dev` → `main` *(Phase 7 — the real gate)*
2. Register `scrape.zepto_ads` + `scrape.zepto_po`; add the missing `label`; fix the
   stale comment on the existing entry
3. Rewrite or delete `docs/zepto-auth.md`
4. On the VM: `git pull`, install Chromium, confirm `ENCRYPTION_KEY`, then
   `cli auth probe zepto -t <tenant>`
5. `--no-save` dry run of each of the three
6. Add schedules **`--disabled`**, enable once the service-user question is settled

Steps 1–5 are code and safe. Step 6 has a human cost and is the TL's call.

---

## Phase 9 — Known gaps ❌

Named honestly. None of these are blocking, all are real.

### Data / correctness
- **Multi-brand untested.** `discover_ids` takes `brandCategoryList[0]`; an account
  with several brands silently scrapes only the first.
- **Pagination truncates silently** past `PO_MAX_PAGES × PO_PAGE_SIZE` = 2,000 rows.
- **Partial-window writes.** The private path has no staging layer, unlike the public
  one — a chunk failure leaves earlier chunks committed. Re-running is the fix.
- **The two growth columns are unproven** — whether scrape-time or window-level cannot
  be settled from stored data, because the upsert overwrites in place. Needs a live
  experiment.
- **All four ad tables stop at 31-Aug** while sales and PO reach 1-Sep. The 1-Sep ads
  scrape has not been run.

### Display bugs
- `zepto_products.py:145` renders NULL stock as `0` → UI says **"Out of stock"**
- Cover **doubles** when the window includes an unscraped day
- "Active campaigns" tile actually counts campaigns *with spend*

### Debt
- **No automated tests.** Everything here was verified live, by hand.
- `transport.py` lives under `campaign_manager/` but is imported by the scraper —
  works, but the dependency is backwards.
- The UAT compatibility shim (`scripts/uat_zepto_compat.sql`) can be dropped once
  `main` carries the renamed tables.
- **Stale comments** in five places — listed in
  [architecture.md §11](architecture.md#11-known-stale-comments-in-the-code).

### To tell the team
- `seller/scraper.py` now imports from
  `campaign_manager/marketplaces/zepto/transport.py`
- `docs/CLI.md` and `docs/zepto-auth.md` are both behind the code
