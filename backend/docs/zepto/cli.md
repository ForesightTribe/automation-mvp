# Zepto Private Scraping — CLI Reference

> `cli` below is shorthand for `python -m cli` — there is no `cli` binary on PATH.
> Run everything from `backend/` with the venv active.
> On the VM: `echo "alias cli='python -m cli'" >> ~/.bashrc && source ~/.bashrc`

Tenant used in every example is **Brik Oven** =
`fa53082e-7e83-424d-aab9-086fe1b4c680`. Get yours with `cli tenant list`.

---

## Quick reference

```bash
# ── auth (once, then it self-heals) ──────────────────────────────────────────
cli auth credentials set zepto -t <tenant> --email <e> --password
cli auth login zepto -t <tenant>
cli auth probe zepto -t <tenant>
cli auth status -t <tenant>

# ── the scrape: ONE command, one login (sales + PO + ads) ─────────────────────
cli scrape zepto -t <tenant>                 # all three sections, default windows
cli scrape zepto -t <tenant> --sales         # or --po / --ads, any combination
cli scrape zepto -t <tenant> --ads --from 2026-09-19 --to 2026-09-28   # a backfill

# ── dry run — reads Zepto, writes no data (one empty scrape_jobs row per section) ─
cli scrape zepto -t <tenant> --no-save
```

---

## Authentication

### `auth credentials set` — one-time, per tenant

Zepto is the **only** platform that needs a stored password. Both Blinkit logins are
passwordless.

```bash
cli auth credentials set zepto -t <tenant> --email ops@brand.com --password
```

`--password` takes **no value** — it prompts, so the secret never reaches your shell
history. The password is encrypted with `ENCRYPTION_KEY` into
`platform_credentials.encrypted_password`.

```bash
cli auth credentials list                 # what is stored, no secrets shown
cli auth credentials remove zepto -t <tenant>
```

### `auth login` — burns one emailed OTP

```bash
cli auth login zepto -t <tenant>
```

Fully unattended. The 4-digit OTP is read from the shared auth inbox over IMAP — you
do **not** type it. Takes roughly 15–30 seconds, most of it waiting for the mail.

> ⚠️ **Every Zepto login evicts whoever is on the dashboard.** One session per account,
> server-enforced. Do not run this casually while a client is working.

### `auth probe` — is it actually alive?

```bash
cli auth probe zepto -t <tenant>
```

One cheap authenticated GET (`get-user-by-token`). This is the honest check —
`auth status` reads stored state, `probe` asks Zepto.

### `auth status`

```bash
cli auth status -t <tenant>
```

Health of every platform for that tenant.

### What does **not** exist for Zepto

```bash
cli auth refresh zepto -t <tenant>       # ✗ Zepto has no refresh endpoint
cli auth zepto-seller -t <tenant>        # ✗ DELETED — was the old browser login
```

`refreshToken` is null in every Zepto response and the JWT dies at local midnight IST.
The only way to hold a session is to log in again.

`cli auth refresh-all` still walks Zepto, but records **`not_refreshable`** rather than
refreshing it — so a green `refresh-all` does **not** mean the Zepto session is healthy.
Use `auth probe` for that.

---

## `scrape zepto` — the one Zepto scrape

```
--tenant, -t     TEXT   required
--sales / --po / --ads  pick sections; none = all three
--from           DATE   sales: default 4 days ago · ads: default the 3 days up to --to
--to             DATE   default: yesterday (sales + ads)
--po-days-back   INT    PO window, counted back from TODAY (default 30)
--category       TEXT   ads: sponsored_products | sponsored_display | sponsored_brands | all
                        default: all — LEAVE IT (the tabs return disjoint campaigns)
--all-cities            sales: per-city split for EVERY city on EVERY day (backfills only)
--save/--no-save        default: --save
```

Zepto has ONE console behind ONE login, so it is one command and one job
(`scrape.zepto`): every section runs on the same session, and each Zepto login logs the
client's own dashboard out. The old `zepto-sales` / `zepto-ads` / `zepto-po` commands
were removed on 2026-10-05 — the section flags cover them.

The work lives in `scraper/platforms/zepto/dashboard_data/seller/run.py`; the command
only sets the flags and the exit code — the run logs one line per step, tagged
`zepto·<tenant>·<section>` (no spinners, no tables; `LOG_LEVEL=DEBUG` for per-request
detail). Exit code: **0** everything landed · **1** a
section failed or lost fetches (what came back is still saved; re-run the same window)
· **3** the login is gone. A section that fails does not stop the others.

| Section | Writes | Window |
|---|---|---|
| sales | `zepto_seller_sales_summary`, `zepto_seller_sales`, `zepto_seller_product_city_daily`, `zepto_soh` (stock + growth as of the scrape, one row per product per scrape day) | 4 days to yesterday |
| po | `zepto_po`, `zepto_grn`, `zepto_asn`, `zepto_po_items` | `--po-days-back` through **today** |
| ads | `zepto_ad_campaign_daily`, `zepto_ad_keyword_daily`, `zepto_ad_product_daily`, `zepto_ad_breakdown_daily`, `zepto_ad_campaign_detail` (keyword performance per campaign per day — one call per campaign that had impressions that day, every kind) + the campaign catalogue (`zepto_ad_campaigns`, `zepto_ad_campaign_keywords`) | 3 days to yesterday |

### Sales — the per-city split

Zepto answers sales by city **one city per call** (~145 cities). Every run asks every
city for the newest day of the window (~2.5 min) and only the cities known to sell for
the older days, so a city that starts selling is caught on its first day. `--all-cities`
asks every city on every day — use it only for a backfill.

If Zepto has not computed the newest day yet, it is dropped from this run's window and
picked up by the next one.

### Ads — blank days

A day whose campaign list comes back with no spend, impressions or clicks on any
campaign (twice): **yesterday** is skipped as not computed yet; an **older** day is
saved as zero spend (every campaign was paused) — unless we already hold spend for it,
in which case the blank answer is treated as ads-bff's transient glitch and the stored
rows stay.

### PO — why the window includes today

POs are forward-looking — an order issued today expires in about three weeks — so
stopping at yesterday would miss exactly the ones that most need acting on.
`po_items` is a second pass (one call per PO), and the PO endpoints are slow and flaky
(retried automatically at 5/15/45 s on a 5xx). See [errorhandling.md](errorhandling.md).

### Failures

Every fetch that fails is retried once ~20 s later — a sales day, a city, an ad view, a
campaign's keyword detail, a PO's line items. Whatever still fails is named in the log
(one WARNING), the section's `scrape_jobs` row is marked **failed** (`partial: N fetch(es)
lost — …`, with the rows that did land) and the command exits 1, so the runner alerts.

---

## The scorecard — no scrape needed

There is **no scorecard scrape**, and there should not be. Zepto publishes no scorecard
page; `app/services/zepto_scorecard.py` derives everything in SQL from the PO tables.
`cli scrape zepto --po` and the scorecard updates itself.

---

## Running as a job

One job type, `scrape.zepto` (label "Zepto scrape", `dashboard` lane, 90-minute
ceiling). Its params map onto the flags above: `date_from`, `date_to`, `sales`, `po`,
`ads`, `po_days_back`, `category`, `all_cities`.

```bash
cli jobs run scrape.zepto -t <tenant>                       # all sections, now
cli jobs run scrape.zepto -t <tenant> ads=true date_from=2026-09-19 date_to=2026-09-28
cli jobs list
cli jobs logs <job-id-prefix> -f
```

Scheduled daily per tenant (2026-10-05): Brik Oven `30 10 * * *`, Sereko `45 10 * * *`,
`catchup=False` — fine, because a missed run is healed by the next one's 3-day ads /
4-day sales windows (a day missed 3 runs running needs a `--from` re-run). Cron is five
fields, **always Asia/Kolkata**.

There is no scheduled Zepto login: the morning `auth.refresh` jobs cannot refresh Zepto
(it reports `not_refreshable`), and the scrape logs itself in when it starts.

---

## Ad-hoc scripts

Not part of the CLI, kept in `backend/scripts/`:

| Script | Does |
|---|---|
| `zepto_export_private.py` | dumps private tables to Excel for a chosen day |
| `zepto_supply_report.py` | PO/ASN/GRN analysis workbook |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No zepto session for tenant …` | never logged in | `cli auth login zepto -t <tenant>` |
| exit code **3** | session dead and could not re-login | `cli auth probe zepto`, then `login` |
| `429` on an ads call, empty body | missing `waf-enabled: false`, **not** rate limiting | check headers before theorising |
| `429` `{"error":"rate limit exceeded"}` | Zepto's real rate limit | automatic: waited out (5/15/30 s), counted as "rate-limit wait(s)" |
| bare `text/plain` 404 | missing `x-proxy-target` on a `/brand-analytics-web/*` call | — |
| `Zepto session carries no brandIds` | account may lack ads access | re-login, check `auth status` |
| `Zepto session has no jwt` | legacy row from the retired `zepto_seller` path | `cli auth login zepto` |
| session dies every few minutes | someone is on the dashboard on the same account | expected; recovery is automatic |
| PO scrape wrote 0 ASNs | a 500 exhausted the retries | re-run; previously stored rows survive |
