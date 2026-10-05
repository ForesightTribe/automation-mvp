# Onboarding a new brand

The checklist for adding a brand (a "client", i.e. a `tenants` row) on Blinkit, Zepto or
both. Do the steps in order.

- Run commands from `automation-mvp/backend` with the venv's Python. This doc writes
  `python -m cli …`, and `<uuid>` for the tenant id.
- Every step writes to the **shared database** (VM, Render and laptops). No migrations needed.
- Scheduled jobs run on the VM, which runs `main`. Code a job needs must be on `main`.

| Step | Blinkit | Zepto |
|---|---|---|
| 1 Client | one client per brand | same client |
| 2 Forwarding | yes | yes |
| 3 Logins | `blinkit` + one seller login | `zepto` |
| 4 Config | caps + coverage rows, `mp=blinkit` | caps + coverage rows, `mp=zepto` |
| 5 Schedules | 2–4 | 1 |
| 6 First runs | private jobs + public scrapes | private job + public scrapes |
| 7 SKU map | one build covers both | |
| 8 Automations | budget, start/pause, bidding | budget, start/pause |

### Blinkit has two seller portals

Every brand is on exactly one. Ask which (step 0), then follow that column wherever this
doc says "Blinkit seller".

| | Old portal | New portal (seller-hub) |
|---|---|---|
| Address | `partnersbiz.com` | `seller.blinkit.com` |
| Model | PO | RO |
| Login | `blinkit_seller` | `blinkit_seller_new` |
| Scrape jobs | `scrape.blinkit_seller`, `scrape.blinkit_scorecard` | `scrape.blinkit_seller_hub` |
| Data | sales, POs, stock, scorecard | sales only (order level) |
| Example | Dobra, Brik Oven | Sereko |

---

## 0. Collect from the brand

| What | Notes |
|---|---|
| Marketplaces: Blinkit, Zepto or both | |
| Brand name as shown on the marketplace | Becomes the slug in `config.xlsx` |
| Blinkit ads login email | Brand Central |
| Which Blinkit seller portal | Old or new (table above) |
| Blinkit seller login email | Can be the same as ads |
| Zepto login email and password | |
| Category keywords | e.g. `goli soda, nimbu soda` |
| Competitor brands | Include alternate spellings |
| Cities, per marketplace | Must match catalog names |
| Automations wanted? | Step 8 |

- Each login email must be **unique to this brand**. The inbox tells tenants apart by it.
- **Zepto allows one session per user.** Our logins sign out anyone using that account in
  a browser, and theirs sign out ours. A dedicated Zepto user for us avoids this.

## 1. Create the client

```bash
# Only for a new org; brands under our agency use the existing account
python -m cli account create --name "Foresight" --admin-email you@foresight.com
python -m cli account list

python -m cli tenant create --name "BrandName" --account <account-id>   # prints the uuid

# Optional: more users on the account
python -m cli account add-user --account <account-id> --email teammate@x.com [--name "Name"] [--admin]
```

- `--name` must match the `tenant` column in `config.xlsx` **exactly**, including case.
- Don't give anyone at the brand a login yet: every user sees every client in the account.

## 2. Mail forwarding

We log in by reading the marketplace's OTP or magic-link email from our shared auth
mailbox. Give the brand that address yourself, and ask them to forward these senders
with a filter (not the whole mailbox):

| Platform | From | Subject |
|---|---|---|
| Blinkit ads | `brands@blinkit.com` | `Sign in to Blinkit Brand Central` |
| Blinkit seller, old portal | `noreply@partnersbiz.com` | `Your OTP for PartnersBiz login` |
| Blinkit seller, new portal | `no-reply@blinkit.com` | `<code> is your OTP from Blinkit Seller Hub` |
| Zepto | `mailer@zeptonow.com` | `Email Otp` |

- Gmail sends a confirmation code to **our** mailbox. Find it and pass it to the brand;
  forwarding doesn't start until they enter it.
- If a login times out, check the mail is arriving:
  `python -m scripts.inbox_scan --limit 25 --email <login address>`

## 3. Logins

Use the CLI below, or the Settings page (section 10).

```bash
# Blinkit ads
python -m cli auth credentials set blinkit -t <uuid> --email ads@brand.com
python -m cli auth login blinkit -t <uuid>

# Blinkit seller: ONE of these, for the brand's portal
python -m cli auth credentials set blinkit_seller     -t <uuid> --email seller@brand.com   # old
python -m cli auth login blinkit_seller     -t <uuid>
python -m cli auth credentials set blinkit_seller_new -t <uuid> --email seller@brand.com   # new
python -m cli auth login blinkit_seller_new -t <uuid>

# Zepto (--password prompts for it)
python -m cli auth credentials set zepto -t <uuid> --email ops@brand.com --password
python -m cli auth login zepto -t <uuid>
```

Then confirm each session is actually alive:

```bash
python -m cli auth probe <platform> -t <uuid>
python -m cli auth status --tenant <uuid>
```

- Trust `auth probe`, not the UI's "Connected" or `expires_at`.
- **Unsure of the portal?** Try the old one. If Blinkit treats the address as a new
  sign-up, or the OTP check errors, the account has moved. Remove the old credentials
  (`python -m cli auth credentials remove blinkit_seller -t <uuid>`) and use the new one.
- **The new portal runs a real browser** for login, checks and scrapes, so it's slower. It
  has no refresh: when the session dies, the next scrape logs in again by itself. If that
  re-login fails on the VM, log in once through the VM:
  `python -m cli jobs run auth.login -t <uuid> platform=blinkit_seller_new`
- Logins that keep failing are almost always forwarding. Repeated failures trip a
  breaker; clear it with `python -m cli auth reset <platform> -t <uuid>`.
- Never schedule `auth.login`.

## 4. Config (`config.xlsx`, then `sync`)

`backend/config.xlsx` drives public scraping. `sync` makes the DB match it, for **every**
tenant in the file, so work from the current copy: an old copy silently undoes other
people's changes. The dry run catches this.

### Sheets

**`brands`**: one `own` row and one row per competitor. Shared by all marketplaces.

| tenant | brand | relationship | keywords | aliases |
|---|---|---|---|---|
| BrandName | brandslug | own | goli soda, nimbu soda | brandslug, brand name |
| BrandName | rival-brand | competitor | | rival brand |

- `keywords` only on the `own` row, spelled exactly as shoppers search.
- **`aliases` in lowercase.** They're matched as substrings of the name the marketplace
  shows (`the derma co`, `dot & key`). `mCaffeine` never matches; `mcaffeine` does.
- The own row's **first alias** is the search term for the own-SKU scrape.

**`caps`**: one row per own brand per marketplace.

| tenant | brand | mp | keyword_cap | brand_cap |
|---|---|---|---|---|
| BrandName | brandslug | blinkit | 36 | 48 |
| BrandName | brandslug | zepto | 30 | 60 |

- `keyword_cap`: results read per keyword (rank, share of voice, competitors).
- `brand_cap`: results read per store for the brand's own products. Set it to at least the
  number of products the brand sells, or the rest go missing. Campaign stock checks use it too.
- Use whole pages: Blinkit 12 per page, Zepto 30. `sync` warns otherwise.
- No row = defaults (scrapes: Blinkit 48/60, Zepto 30/60, Instamart 32/60). Add a row per
  marketplace anyway.
- A CLI flag (`--cap`, `--brand-cap`) overrides the sheet for one run.

**`coverage`**: one row per marketplace and city.

| mp | tenant | city |
|---|---|---|
| blinkit | BrandName | bengaluru |
| zepto | BrandName | bengaluru |

- Always fill `mp`.
- Check the city exists first: `python -m cli locations list -m <mp> --city <city>`
- Row 1 must stay the header (`mp | tenant | city`). `sync` always reads row 1 as the header.

Leave `locations` and `city_map` alone unless a city is missing from the catalog.

### Sync

```bash
python -m cli sync --file config.xlsx --dry-run
```

A correct dry run shows **only additions for your new tenant**: brands, caps and coverage
`added`; everything `updated` and `deleted` at 0; no page warnings. Any `updated` or
`deleted` means your file differs from the DB. Stop and get the current file.

```bash
python -m cli sync --file config.xlsx
python -m cli watchlist list --tenant <uuid>
python -m cli locations list --tenant <uuid> -m <mp>
```

**Never use `--prune`.** The file doesn't hold the Instamart catalog or coverage, so prune
would delete them. Commit `config.xlsx` after every sync.

### Later changes

**Caps:** edit the `caps` sheet, dry run (only `caps updated`), sync.

**Add a competitor:** add the row, dry run (`brands added = 1`), sync.

**Remove a competitor:** remove the row from the sheet, then delete it in the DB (sync
won't, without `--prune`). Check with a `SELECT` first; expect one row.

```sql
DELETE FROM tenant_watchlist
WHERE tenant_id = '<uuid>' AND relationship = 'competitor' AND brand_slug = '<slug>';
```

Competitor changes apply from the next scrape; there's no backfill.

**Wrong tenant or brand name** (best fixed before the first scrape):

| Change | Workbook | DB |
|---|---|---|
| Tenant name | `tenant` on every row of `brands`, `caps`, `coverage` | `UPDATE tenants SET name = '<new>' WHERE id = '<uuid>';` |
| Own brand slug | `brand` on the own row and its `caps` rows | `UPDATE tenant_watchlist SET brand_slug = '<new>' WHERE tenant_id = '<uuid>' AND relationship = 'own';` |
| Old brand row | | `DELETE FROM brands WHERE slug = '<old>';` once nothing references it |

- If the new slug isn't in `brands` yet, insert it first:
  `INSERT INTO brands (slug, name, metadata) VALUES ('<new>', '<Name>', '{}');`
- Change the slug with the `UPDATE`, not with `sync`: sync treats a new slug as a new row
  and keeps the old one.
- In Excel's Find & Replace, tick **Match case** and **Match entire cell contents**, or the
  name inside `keywords`/`aliases` gets rewritten too.
- Finish with a dry run that shows all zeros.

## 5. Schedules

Times are IST. Name them `BRAND | …` and avoid other tenants' times (`schedules list`).

```bash
# Every tenant
python -m cli schedules add -n "BRAND | Auth refresh daily" --type auth.refresh -t <uuid> --cron "20 6 * * *"

# Blinkit ads (if they run ads)
python -m cli schedules add -n "BRAND | Blinkit marketing daily" --type scrape.blinkit_marketing -t <uuid> --cron "30 13 * * *"

# Blinkit seller, old portal
python -m cli schedules add -n "BRAND | Blinkit seller daily"     --type scrape.blinkit_seller    -t <uuid> --cron "45 11 * * *" --catchup
python -m cli schedules add -n "BRAND | Blinkit scorecard weekly" --type scrape.blinkit_scorecard -t <uuid> --cron "15 10 * * 1" --catchup

# Blinkit seller, new portal (instead of the two above)
python -m cli schedules add -n "BRAND | Blinkit seller-hub daily" --type scrape.blinkit_seller_hub -t <uuid> --cron "30 12 * * *"

# Zepto (sales, POs and ads in one job)
python -m cli schedules add -n "BRAND | Zepto private daily" --type scrape.zepto -t <uuid> --cron "45 10 * * *"
```

- `--catchup` only for old-portal seller and scorecard: they read one day or week, so a
  missed run is a permanent gap. The others re-read 7 or 30 days.
- New-portal brands have no scorecard.
- **Don't schedule public scrapes**; they run from the laptop (step 6).
- **Don't add `cm.*` schedules**; automations create their own (step 8).

**What `auth.refresh` does** to each login:

| Login | Result |
|---|---|
| `blinkit`, `blinkit_seller`, `instamart` | Refreshed without email |
| `blinkit_seller_new` | Not refreshable; the seller-hub scrape logs in again when needed |
| `zepto` | Not refreshable (dies at midnight IST); the Zepto scrape logs in again |

It skips entirely if another job of the tenant is running, and always reports success.
Check sessions with `auth status`, not the job status.

## 6. First runs

### Private scrapes (queue on the VM)

```bash
python -m cli jobs run scrape.blinkit_marketing  -t <uuid>
python -m cli jobs run scrape.blinkit_seller     -t <uuid>    # old portal
python -m cli jobs run scrape.blinkit_scorecard  -t <uuid>    # old portal
python -m cli jobs run scrape.blinkit_seller_hub -t <uuid>    # new portal
python -m cli jobs run scrape.zepto              -t <uuid>

python -m cli jobs list
python -m cli jobs logs <job-id> -f
```

- Backfill: add `date_from=YYYY-MM-DD date_to=YYYY-MM-DD` (marketing, old seller, Zepto)
  or `week=YYYY-MM-DD` (scorecard). `python -m cli jobs types` lists parameters.
- Seller-hub backfill beyond 30 days uses a named month, run directly:
  `python -m cli scrape blinkit-seller-hub -t <uuid> --window "August 2026"`

### Public scrapes (by hand, on the laptop)

From a `dev` checkout. Own-SKU first: the SKU map needs it, and it's much faster.

```bash
python -m cli scrape public-skus -t <uuid> -m blinkit    # own products: price, stock
python -m cli scrape public-skus -t <uuid> -m zepto
python -m cli scrape public-run  -t <uuid> -m blinkit    # keywords: rank, competitors
python -m cli scrape public-run  -t <uuid> -m zepto
```

- Always pass `-m`; these commands default to Blinkit.
- Pace: Blinkit ~2,000 stores takes 4.5–10 h for keywords. Zepto runs single-threaded:
  ~170 stores takes ~2 h for keywords and ~20 min for own-SKU.
- On long runs, use `--resume` after an interruption, or split with `--city "delhi ncr"`.
- Clean runs load into the DB by themselves. For a partial run:
  `python -m cli scrape staged --pending`, then `scrape load --file <ref>` or `scrape discard --file <ref>`

### Check the data landed

`scrape_jobs.records_written` is always 0 for Blinkit marketing and old-portal seller, so
check the tables:

```sql
-- replace <uuid>
SELECT 'blinkit ads' t, count(*), max(date)::text latest FROM blinkit_ad_campaign_daily WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'blinkit seller (old)',  count(*), max(date)::text       FROM blinkit_seller_sales              WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'blinkit stock (old)',   count(*), max(date)::text       FROM blinkit_soh                       WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'blinkit scorecard (old)', count(*), max(scraped_at)::text FROM blinkit_scorecard_weekly        WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'blinkit seller-hub (new)', count(*), max(order_date)::text FROM blinkit_seller_hub_sales_order_ro WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'zepto sales',           count(*), max(date)::text       FROM zepto_seller_sales_daily          WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'zepto POs',             count(*), max(scraped_at)::text FROM zepto_po                          WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'zepto ads',             count(*), max(date)::text       FROM zepto_ad_campaign_daily           WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'public keyword: ' || mp_slug, count(*), max(scraped_at)::text FROM search_snapshots WHERE tenant_id = '<uuid>' GROUP BY mp_slug
UNION ALL SELECT 'public own-SKU: ' || mp_slug, count(*), max(scraped_at)::text FROM sku_snapshots    WHERE tenant_id = '<uuid>' GROUP BY mp_slug;
```

Zeros can be genuine (no POs, no ads, all campaigns paused). Ask the brand before
assuming a bug.

## 7. SKU map

Links private item ids to public product ids; the Products page needs it. Run after the
own-SKU public scrape has landed for each marketplace. One build covers every marketplace,
and each is matched only against its own products.

```bash
python -m cli sku-map build -t <uuid> --file sku_map.xlsx
# review the workbook, fix wrong or missing matches
python -m cli sku-map apply -t <uuid> --file sku_map.xlsx
```

- Re-running is safe: your fixes are kept, auto matches are recomputed.
- A marketplace without own-SKU data comes back unmatched; re-run once it lands.
- Run it from `dev` until `main` has the marketplace-aware version.

## 8. Automations (optional)

Every `cm` command needs `-m blinkit` or `-m zepto`.

| | Blinkit | Zepto |
|---|---|---|
| Budget schedules | yes | yes (minimum ₹500/day) |
| Start / pause | yes | yes |
| Keyword bidding | yes | off (needs `CM_ZEPTO_KEYWORD_BIDDING=1` and the shopper proxy) |

Zepto ads are prepaid from a wallet; an empty wallet stops campaigns whatever the schedule.

### 8a. Advertiser id

This decides which ad account gets charged. Live writes are refused until it's stored.

```bash
python -m cli cm advertiser     -t <uuid> -m blinkit             # prints blinkit-derived = <n>
python -m cli cm set-advertiser -t <uuid> -m blinkit --id <n>
python -m cli cm advertiser     -t <uuid> -m blinkit             # stored must equal derived

python -m cli cm advertiser     -t <uuid> -m zepto               # prints the brand UUID
python -m cli cm set-advertiser -t <uuid> -m zepto --id <brand-uuid>
```

- **"This Blinkit login can see N advertisers"**: the login covers several brands. Pick
  this brand's id by name and confirm the company with someone who knows. The name is the
  legal entity, not the brand (Sereko's is SUSH ESSENTIALS PRIVATE LIMITED).
- **Any other "couldn't read" error**: in Brand Central as the brand, open DevTools →
  Network and read the id from the `advertisers` response.
- If stored and derived ever differ, stop.

### 8b. Load campaigns

```bash
python -m cli cm sync-campaigns -t <uuid> -m blinkit
python -m cli cm sync-campaigns -t <uuid> -m zepto
```

### 8c. Rules, run dry

Create rules at **Ads → Automation** (the navbar picks the marketplace). Their schedules are
created automatically. Nothing is written until you arm, so watch at least a day of the
activity log first.

Bid rules measure position at the global per-city store set. Only set a brand-specific
store if needed:

```bash
python -m cli cm stores show --city <city> -m blinkit
python -m cli cm stores set  --city <city> --store <merchant_id> --rank 1 -m blinkit -t <uuid>
```

### 8d. Arm

```bash
python -m cli cm arm    -t <uuid> -m <mp>      # live writes from now on
python -m cli cm disarm -t <uuid> -m <mp>      # back to dry run
```

Each marketplace is armed separately. `arm` refuses without an advertiser id.

## 9. Final check

```bash
python -m cli status
python -m cli auth status --tenant <uuid>
python -m cli schedules list
```

Then check Overview, Marketing, Reports and Competition for the client, per marketplace.

### Troubleshooting

| Symptom | Cause |
|---|---|
| `sync`: "Unknown tenant(s)" | Tenant name in the workbook doesn't match exactly (check spelling). Blocks the whole sync |
| Dry run shows `updated` or `deleted` | Your `config.xlsx` is out of date |
| Dry run adds no coverage for new rows | The header moved off row 1 |
| Competitor never shows up | Alias has capitals, or doesn't match the marketplace's spelling |
| Login times out | Forwarding missing or wrong (`scripts.inbox_scan`) |
| Zepto login fails now and then | OTP expired (5 min) behind a slow forward, or someone else logged in |
| `blinkit_seller` login fails as a sign-up | Account moved to the new portal (step 3) |
| Seller-hub: "Not on a dashboard route" | Session died: `auth probe` then `auth login blinkit_seller_new` |
| Old seller or scorecard has gaps | Schedule missing `--catchup` |
| New-portal brand: Products/Reports empty | Expected; only Overview reads seller-hub data |
| Products page has no public panel | SKU map not built (step 7) |
| `cm arm` refuses | No advertiser id (8a) |
| Automations run but change nothing | Not armed (8d) |
| `cm` command errors about `--marketplace` | Add `-m blinkit` or `-m zepto` |

---

## 10. Settings page

Logins (step 3) can also be done in the dashboard: select the client, open **Settings**
(admins only), click **Connect** on an account, and follow the modal (forwarding, then
login email, plus password for Zepto). Everything else is CLI-only.

- **Connected** only means a session row exists; confirm with `auth probe`.
- Both Blinkit seller portals are listed. Connect only the brand's one.
- A failed login only shows as a 4-minute timeout. See the reason with `jobs list` and `jobs logs <id>`.
- **Disconnect** deletes the session and saved credentials. It doesn't stop forwarding.

## 11. Known gaps

- New-portal brands get only Blinkit sales: no POs, stock or scorecard, and only the
  Overview page reads it (Products and Reports are empty).
- `sku_map.mp_slug` still defaults to `'blinkit'` in the DB; older code without the
  marketplace-aware SKU map files everything as Blinkit.
- Public scrapes have no VM home yet, so they run by hand from the laptop.
- `records_written` is never filled for Blinkit marketing and old-portal seller.
- The inbox matches a login email to a tenant by address, so a reused address leaks a
  session to the wrong tenant.
- Every user sees every client in the account, and members can write. Don't give brand
  staff logins yet.

See also: [platform-auth.md](platform-auth.md) · [jobs-runbook.md](jobs-runbook.md) ·
[campaign-manager.md](campaign-manager.md) · [staging.md](staging.md)
