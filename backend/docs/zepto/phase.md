# Zepto Private Scraping — Phases

Where this work has been, where it is, and what is left. Ticket **FST-10**.
Clients **Brik Oven** (`fa53082e-7e83-424d-aab9-086fe1b4c680`) and **Sereko**.
Owner: Deepansh (since 2026-10-03).

Status as of **2026-10-07**. Phases 0–5 below are history and keep the command names of
their time (`zepto-sales` / `zepto-ads` / `zepto-po`, since replaced by `scrape zepto`).

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
| 6 | Dashboard integration | ✅ Done |
| 7 | Ship to `main` | ✅ Done |
| 8 | Run unattended on the VM | ✅ Daily since 2026-09-10 |
| 9 | Hardening / known gaps | 🔶 Mostly folded into Phase 10 |
| 10 | **The refactor** (`PLAN-private-scrape.md`) | 🔶 Built on `fix/zepto-private-refactor`, **not deployed** |

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

> `docs/zepto-auth.md` at the repo root documented **this phase** (Xvfb, a command that
> no longer exists) long after it was gone; it has since been deleted.

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

## Phase 6 — Dashboard integration ✅

Products, Reports, Analytics, Overview, Ads and Scorecard all read Zepto data.

Whole-rupee formatting on Overview for Zepto only; "Stock by facility" hidden for Zepto;
FE/BE split removed from the Products stock column for Zepto (Zepto has no
front-end/back-end concept — that is Blinkit's).

**Cross-checked against Zepto's own dashboard in both directions on 29-Aug — all
matched.** An apparent mismatch traced to an unapplied date filter on their side.

Still open from this phase:
- The **"Active campaigns"** tile counts campaigns that **ran** in the window (spend or
  impressions) — the same rule for Blinkit, Zepto and Instamart, and the only one that has
  a previous window to compare against. The label reads like "status = active now"; a
  rename (e.g. "Campaigns that ran") is a cross-marketplace UI call, not yet made.
- `CityBreakdown` full-width when `FacilityStock` is hidden — offered, undecided.

---

## Phase 7 — Ship to `main` ✅

Done in September: `main` carries the `platform_auth` login, the PO scrape and the
scorecard; the old browser `auth.py` is gone. `docs/zepto-auth.md` (the Phase-1 browser
login doc) was deleted.

The rule that made this the gate still holds: **the VM runs `main`, never `dev`.** New
Zepto code reaches the VM only when it is merged to `main` and pulled.

---

## Phase 8 — Unattended on the VM ✅

`foresight-vm` (GCP Mumbai, `e2-standard-2`) runs Zepto daily since **2026-09-10**:

| Schedule | Job | Cron (IST) |
|---|---|---|
| Brik Oven — Zepto private daily | `scrape.zepto` | `30 10 * * *` |
| Sereko — Zepto private daily | `scrape.zepto` | `45 10 * * *` |

One job type, `scrape.zepto` (all three sections on one login), replaced the per-section
types. Live record to 2026-10-07: 35 successful runs, 12 failed — the failures were the
lost-data and silent-failure bugs Phase 10 fixes.

**Login.** There is no scheduled Zepto login. The JWT dies at midnight IST and Zepto has
no refresh, so the morning scrape logs in itself through `ensure()`; the 06:xx
`auth.refresh` jobs cannot extend a Zepto session. Each login logs the client's dashboard
user out — accepted since 2026-09-21 (a missed action costs more than a logout); a
dedicated service user is still the clean fix.

The box needs Playwright for the ~10 s WAF mint (`playwright install chromium` without
sudo, `sudo playwright install-deps chromium`).

---

## Phase 9 — Known gaps (as of 2026-09-02) → folded into Phase 10

The September list, and where each went:

| Gap | Now |
|---|---|
| Multi-brand untested (`brandCategoryList[0]`) | ⏸ parked — every client is single-brand (P5/P26) |
| PO pagination truncates silently past 2,000 rows | open, left as is (P4) — the 30-day window is far below it |
| Partial-window writes | each section's save is one transaction; sections save independently — documented ([errorhandling.md](errorhandling.md) §10) |
| Growth columns unproven | ✅ settled 2026-10-07: readings of the moment, like stock (P8) → `zepto_soh` |
| Ads stopped a day short of sales | ✅ ads re-scrape 3 days every run (P1) |
| NULL stock shown as "Out of stock" | ✅ fixed 2026-10-07 — "No stock data" (P11) |
| Cover doubled with an unscraped day in the window | ✅ fixed 2026-10-07 — divides by days with data (P11) |
| "Active campaigns" counts campaigns with spend | not a bug — a label question (Phase 6) |
| No automated tests | ✅ `seller/tests/` (parser, run, client) + campaign-manager Zepto tests |
| `transport.py` under `campaign_manager/` | ✅ moved to `seller/client.py` (P12) |
| UAT shim `scripts/uat_zepto_compat.sql` | open — its table + 2 views still exist on the shared DB, nothing reads them (P49, left as is) |
| Stale code comments | ✅ fixed (P13, P14) |

---

## Phase 10 — The refactor 🔶

*2026-10-03 → ongoing.* Plan, decisions and item ids (P1…P54):
`backend/zepto-cm-exp/plans/PLAN-private-scrape.md` (gitignored). Release notes:
`plans/RELEASE-NOTES-[6.10.26].md`. Branch `fix/zepto-private-refactor`, **not yet
deployed** — merged to `dev` last, after everyone else.

**Built:**
- **Stop the data loss.** Ads re-scrape 3 days each run (P1, P54); paused-brand days saved
  as zero (P28); the city split covers every tenant and finds new cities (P29, P21); lost
  fetches are re-checked once, then fail the run (P44, P15); `scrape_jobs` rows agree with
  the exit code (P35); an expired login exits 3 from every section (P46).
- **Restructure.** All loops moved out of the CLI into `seller/run.py` (one `scrape zepto`
  command, `SectionResult`); one 5xx retry helper; product paging (P47); dead code gone.
- **Clean logs** (Zepto and Blinkit dashboard scrapes): one line per step, tagged; no
  spinners or tables (P52).
- **Per-campaign keyword performance** → `zepto_ad_campaign_detail` + the automation
  wizard's Zepto keyword metrics (P38, P43). Migration `c3a9e5d7f2b1` applied.
- **Shared client** moved to `seller/client.py`; the four campaign reads to
  `seller/scraper.py` (P12). Zepto's own rate limit waited out, not mistaken for a WAF
  failure (P53).
- **Stock and growth** → `zepto_soh` (P41): step 1 (the table, written by the scrape) and
  step 2 (the Products page reads it, old column as fallback). Migration `e7b2c9d4a6f3`
  applied 2026-10-07 (after the merge revision `f1a8c3e5b7d2`).
- **Products page:** cover divides by days with data; unknown stock is "No stock data"
  (P11).

**Next, in order:** deploy → check the first scheduled run → one backfill pass (30 days of
keyword detail, Sereko 09-27 city day, Brik Oven 09-14 / 09-17 ad days) → P41 step 3
(drop the old columns and the fallback, once everything runs the new code).

**Left as is, on purpose:** P24 (settings columns on `zepto_ad_campaign_daily` — Display
campaigns still need them), the brand-level keyword table (covers campaign kinds the
detail does not), P4, P49.
