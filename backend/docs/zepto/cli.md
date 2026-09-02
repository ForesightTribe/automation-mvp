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

# ── the three scrapes ────────────────────────────────────────────────────────
cli scrape zepto-sales -t <tenant> --from 2026-09-01 --to 2026-09-01
cli scrape zepto-ads   -t <tenant> --from 2026-09-01 --to 2026-09-01
cli scrape zepto-po    -t <tenant> --from 2026-08-01 --to 2026-09-02

# ── dry run — touches nothing ────────────────────────────────────────────────
cli scrape zepto-sales -t <tenant> --no-save
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

## `scrape zepto-sales`

```
--tenant, -t   TEXT   required
--from         DATE   YYYY-MM-DD   default: 7 days ago
--to           DATE   YYYY-MM-DD   default: yesterday
--save-xlsx    PATH   also write results to this .xlsx
--all-cities          sweep every city, not just those known to sell
--save/--no-save      default: --save
```

Writes `zepto_seller_sales_summary`, `zepto_seller_sales`,
`zepto_seller_product_city_daily`.

```bash
# yesterday (the default)
cli scrape zepto-sales -t fa53082e-7e83-424d-aab9-086fe1b4c680

# one specific day
cli scrape zepto-sales -t fa53082e-… --from 2026-09-01 --to 2026-09-01

# dry run + Excel, nothing written to the DB
cli scrape zepto-sales -t fa53082e-… --no-save --save-xlsx out.xlsx
```

### On `--all-cities`

138 calls instead of a handful. Run it **occasionally** to pick up a new city, not
daily. Without it, only cities already known to sell are queried.

### On the date window

⚠️ `period_start`/`period_end` are **part of the grain** of `zepto_seller_sales`.
Scraping `--from 2026-08-01 --to 2026-08-31` writes **one 31-day row per SKU**, not 31
daily rows. For daily rows, scrape one day at a time.

---

## `scrape zepto-ads`

```
--tenant, -t   TEXT   required
--from         DATE   default: 7 days ago
--to           DATE   default: yesterday
--category     TEXT   sponsored_products | sponsored_display | sponsored_brands | all
                      default: all
--save/--no-save      default: --save
```

Writes `zepto_ad_campaign_daily`, `zepto_ad_keyword_daily`, `zepto_ad_product_daily`,
`zepto_ad_breakdown_daily`.

```bash
cli scrape zepto-ads -t fa53082e-… --from 2026-09-01 --to 2026-09-01
```

> ⚠️ **Leave `--category` at `all`.** The three tabs return **disjoint** campaigns, so
> anything narrower silently drops the other tabs' spend. The filter applies only to
> the Analytics tables; the campaign list ignores it and is fetched once regardless.

This is the slowest of the three — six tabular views × three categories, with a 1.5s
pause between metric calls.

---

## `scrape zepto-po`

```
--tenant, -t   TEXT   required
--from         DATE   default: 30 days ago
--to           DATE   default: TODAY
--save/--no-save      default: --save
```

Writes `zepto_po`, `zepto_asn`, `zepto_grn`, `zepto_po_items`.

```bash
# the default 30-day window
cli scrape zepto-po -t fa53082e-…

# backfill a month
cli scrape zepto-po -t fa53082e-… --from 2026-04-01 --to 2026-04-30
```

### Why this one includes today

Unlike sales, the window is **inclusive of today** by default. POs are
forward-looking — an order issued today expires in about three weeks — so stopping at
yesterday would miss exactly the ones that most need acting on.

### Two behaviours worth knowing

- **`po_items` is a second pass.** The list endpoint returns `itemsCount` but not the
  lines, so the scraper makes one extra call per PO. A wide window is therefore
  *much* slower than the row count suggests.
- **The PO endpoints are flaky and slow.** Measured 4.8s–21s for the same 31-day
  window, with roughly 4 failures in 18 attempts. Retries are automatic at 5/15/45s —
  a bad run is slow, not fatal. See [errorhandling.md](errorhandling.md).

---

## The scorecard — no scrape needed

There is **no `cli scrape zepto-scorecard`**, and there should not be. Zepto publishes
no scorecard page; `app/services/zepto_scorecard.py` derives everything in SQL from the
PO tables. Run `zepto-po` and the scorecard updates itself.

---

## Running as a job

The runner executes the exact command you would type, so anything above works as a
job — **once the job type exists**.

```bash
cli jobs types                                    # what can be run
cli jobs run scrape.zepto_seller_sales -t <tenant> date_from=2026-09-01 date_to=2026-09-01
cli jobs list
cli jobs logs <job-id-prefix> -f
```

### ⚠️ Only one of the three is registered

`jobs/types.py` has `scrape.zepto_seller_sales` and nothing else. There is **no**
`scrape.zepto_ads` and **no** `scrape.zepto_po`, so those two cannot be queued or
scheduled at all today.

The registered one also does not expose `--all-cities`, and its `label` is missing, so
logs and alerts show the raw type name instead of a readable one.

| Command | Job type | Params exposed |
|---|---|---|
| `zepto-sales` | `scrape.zepto_seller_sales` | `date_from`, `date_to` |
| `zepto-ads` | — **not registered** | — |
| `zepto-po` | — **not registered** | — |

### Scheduling

```bash
cli schedules add -n "Brik Oven Zepto sales" --type scrape.zepto_seller_sales \
    -t fa53082e-… --cron "30 2 * * *" --catchup

cli schedules list
cli schedules show <id>
cli schedules disable <id>
```

Cron is five fields, **always Asia/Kolkata**. Use `--catchup` on daily scrapes whose
default window is only yesterday — a missed run is otherwise a permanent gap.

**No Zepto schedule exists today.** Verified against `job_schedules` on 2026-09-02: no
Zepto row, and no Zepto job has ever been queued.

### The daily login schedule

```bash
cli schedules add --name "Zepto daily login" --type auth.login \
    --cron "5 0 * * *" -t <tenant> --catchup --disabled platform=zepto
```

00:05, just **after** midnight — a login at 23:50 would buy a ten-minute session, and
midnight is when the eviction costs a human least.

> ⚠️ Create it `--disabled`. Enabling it logs the client's own team out of their
> dashboard nightly. It should stay off until Brik Oven provisions a service user.
> This is a business decision, not a technical one.

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
| `429` on an ads call | missing `waf-enabled: false`, **not** rate limiting | check headers before theorising |
| bare `text/plain` 404 | missing `x-proxy-target` on a `/brand-analytics-web/*` call | — |
| `Zepto session carries no brandIds` | account may lack ads access | re-login, check `auth status` |
| `Zepto session has no jwt` | legacy row from the retired `zepto_seller` path | `cli auth login zepto` |
| session dies every few minutes | someone is on the dashboard on the same account | expected; recovery is automatic |
| PO scrape wrote 0 ASNs | a 500 exhausted the retries | re-run; previously stored rows survive |
