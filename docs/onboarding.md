# Onboarding a new brand

This is the full checklist for bringing a new brand (a "client", i.e. a `tenants` row)
onto Foresight, on Blinkit, Zepto or both. Do the steps in order: each one depends on
the one before it.

Run every command from `automation-mvp/backend` with the venv's Python
(`venv/Scripts/python.exe` on Windows, `venv/bin/python` on the VM). This doc writes
`python -m cli …` for short, and `<uuid>` for the new tenant's id.

> **Every step here writes to the shared database** that the VM, Render and every laptop
> use. Nothing needs a migration. The VM runs `main`, so anything a step relies on must
> be merged there before scheduled jobs can use it.

**Where each step applies**

| Step | Blinkit | Zepto |
|---|---|---|
| 1 Client + users | once per brand | (same client) |
| 2 Forwarding | ✅ | ✅ |
| 3 Credentials + login | `blinkit` + `blinkit_seller` | `zepto` |
| 4 Config (`config.xlsx`) | coverage rows `mp=blinkit` | coverage rows `mp=zepto` |
| 5 Schedules | 4 schedules | 1 schedule |
| 6 First runs | 3 jobs | 1 job |
| 7 SKU map | ⚠️ one marketplace only (see step 7) | ⚠️ same |
| 8 Automations | `-m blinkit` | `-m zepto` |

---

## 0. Collect from the brand first

| What | Used in | Notes |
|---|---|---|
| Which marketplaces: Blinkit, Zepto or both | all | |
| Brand name, as it appears on the marketplace | Steps 1, 4 | The slug goes in `config.xlsx` |
| Blinkit **ads** dashboard login email | Step 3 | Brand Central (magic link) |
| Blinkit **seller** dashboard login email | Step 3 | PartnersBiz (OTP). Can be the same address as ads |
| Zepto login email **and password** | Step 3 | Zepto sends an OTP as well as needing the password |
| Category keywords to track | Step 4 | For example `goli soda, nimbu soda` |
| Competitor brands | Step 4 | Include any alternate spellings |
| Cities they sell in, per marketplace | Step 4 | Must match catalog city names |
| Do they want bid/budget automations? | Step 8 | Needs their ad account id (step 8a) |

- Each login email must be **unique to this brand**. Our inbox tells tenants apart by the
  login address, so two tenants sharing one would receive each other's sessions (see §11).
- **Tell a Zepto brand this up front:** Zepto allows one session per user. Every time we
  log in, whoever is using that account in a browser gets signed out, and vice versa. A
  dedicated Zepto user for us avoids this. If they can't create one, they have to accept
  the sign-outs.

---

## 1. Create the client (and users)

```bash
# Only for a new org. A brand under our agency goes into the existing account.
python -m cli account create --name "Foresight" --admin-email you@foresight.com
python -m cli account list                          # note the account id

python -m cli tenant create --name "BrandName" --account <account-id>   # prints the tenant uuid
python -m cli tenant list                           # or read it from here

# Optional: more logins on the account (member by default)
python -m cli account add-user --account <account-id> --email teammate@x.com [--name "Name"] [--admin]
```

- ⚠️ The `--name` must match the `tenant` column in `config.xlsx` **exactly, including
  case**, because `cli sync` looks tenants up by name.
- **One client per brand, not per marketplace.** A brand on Blinkit and Zepto is one tenant.
- ⚠️ **Don't give anyone at the brand a login yet.** Every user of an account sees every
  client in it, and members are not read-only (see §11).

## 2. Set up mail forwarding (in the brand's mailbox)

Marketplaces log in by emailing a magic link or OTP. We log in unattended by reading
that mail from our shared auth mailbox (`AUTH_INBOX_USER` in `.env`), so **the brand must
forward those emails to us before any login can work.**

Send the brand the auth mailbox address yourself (the UI deliberately doesn't show it).
Ask them to forward these senders (only the ones for marketplaces they're on):

| Platform | From | Subject |
|---|---|---|
| Blinkit ads | `brands@blinkit.com` | `Sign in to Blinkit Brand Central` |
| Blinkit seller | `noreply@partnersbiz.com` | `Your OTP for PartnersBiz login` |
| Zepto | `mailer@zeptonow.com` | `Email Otp` |

- Ask for a **filter on those senders** rather than forwarding the whole mailbox.
- **Gmail sends a confirmation code to the forwarding address, which is our mailbox.**
  Find it in the auth inbox and pass it to the brand. Forwarding doesn't start until
  they enter it.
- Zepto's OTP expires in 5 minutes. A slow forward shows up as a failed Zepto login.

If a login later times out, check whether the mail is actually arriving:

```bash
python -m scripts.inbox_scan --limit 25 --email <brand login address>
```

## 3. Save credentials and log in (each platform they use)

Either use the Settings UI (§10), which does exactly this, or the CLI:

```bash
python -m cli auth platforms                        # which platforms are wired

# Blinkit
python -m cli auth credentials set blinkit        -t <uuid> --email ads@brand.com
python -m cli auth credentials set blinkit_seller -t <uuid> --email seller@brand.com
python -m cli auth login blinkit        -t <uuid>
python -m cli auth login blinkit_seller -t <uuid>

# Zepto (--password prompts for it, hidden)
python -m cli auth credentials set zepto -t <uuid> --email ops@brand.com --password
python -m cli auth login zepto -t <uuid>
```

**Check (always, even after the UI):**

```bash
python -m cli auth probe blinkit        -t <uuid>   # is the session ACTUALLY alive?
python -m cli auth probe blinkit_seller -t <uuid>
python -m cli auth probe zepto          -t <uuid>
python -m cli auth status --tenant <uuid>
```

- Trust `auth probe`, not `expires_at` and not the UI's "Connected" pill. Both only mean
  a session row exists.
- After this, sessions look after themselves. Scrapers call `ensure()`, which logs in again
  when needed. The daily `auth.refresh` job (step 5) extends the Blinkit sessions. Zepto
  can't be refreshed, and jobs just log in again. **Don't schedule a Zepto `auth.login`.**
- A login that keeps failing is almost always forwarding (step 2). Stuck after repeated
  failures? Clear the circuit breaker with `python -m cli auth reset <platform> -t <uuid>`.

## 4. Configure public data (`config.xlsx`, then `sync`)

`backend/config.xlsx` is the source of truth for public scraping. Edit it, then sync.

### ⚠️ First, make sure your copy of the file is current

`sync` **overwrites** the DB with whatever the file says, for every tenant in it. If your
copy is older than the DB (someone else synced since), you'll silently undo their change.
For example, a blank `brand_cap` in your file resets a tenant's cap to NULL. The dry run
below catches this. **It must only show changes for your new tenant.**

### The sheets

**`brands` sheet:** one `own` row plus one row per competitor.

| tenant | brand | relationship | keywords | aliases | keyword_cap | brand_cap |
|---|---|---|---|---|---|---|
| BrandName | brandslug | own | goli soda, nimbu soda, … | brandslug, brand name | 36 | 48 |
| BrandName | rival-brand | competitor | | rival-brand, rival | | |

- `keywords` go on the `own` row only.
- `keyword_cap` is how many results per keyword are read. `brand_cap` is how many of the
  brand's own SKUs the targeted scrape reads. Dobra uses 36 / 48, Brik Oven 30 / 60.
  **Fill both in.**
- ⚠️ **Write `aliases` in lowercase.** Matching lowercases the product name but not your
  alias, so an alias like `mCaffeine` never matches anything. Use `mcaffeine`. Aliases are
  substrings of the product or brand name as the marketplace shows it (`the derma co`,
  `dot & key`). The `brand` slug can be anything readable; it's normalised for you.
- The `own` row's **first alias is the search term** for the own-SKU scrape, so make it
  the brand name a shopper would type.
- Keywords are searched exactly as written, so check the spelling.
- **Keywords and competitors are per brand, not per marketplace.** A brand on Blinkit
  and Zepto has ONE set of rows, and both marketplaces use it. There is no `mp` column here.

**`coverage` sheet:** one row per marketplace + city (`mp`, `tenant`, `city`).

| mp | tenant | city |
|---|---|---|
| blinkit | BrandName | bengaluru |
| zepto | BrandName | bengaluru |

- Always fill `mp` in. A blank means `blinkit`.
- Add **every marketplace in the same sync.** A new brand's `marketplaces` label is taken
  from its coverage rows the first time it syncs.
- Check a city exists in that marketplace's catalog first:
  `python -m cli locations list -m zepto --city <slug>` (or `-m blinkit`).

**`locations` / `city_map` sheets:** leave these alone unless a city is missing from the
catalog (Blinkit ~2,060 stores, Zepto ~1,230).

### Sync

```bash
python -m cli sync --file config.xlsx --dry-run     # read the plan first
```

**What a correct dry run looks like:**
- `brands`: **added** = your own row + competitors, **updated = 0**.
- `coverage`: **added** = the new tenant's stores, **deleted = 0**.
- `locations`: **no changes**.

If you see **any `updated` or `deleted` count**, your file differs from the DB. Stop, get
the current file (or fix the difference), and dry-run again.

```bash
python -m cli sync --file config.xlsx

python -m cli watchlist list --tenant <uuid>                    # check it landed
python -m cli locations list --tenant <uuid> -m blinkit         # its Blinkit stores
python -m cli locations list --tenant <uuid> -m zepto           # its Zepto stores
```

⚠️ **Never use `--prune`** unless you're sure your file holds every row. Right now it
doesn't hold the Instamart catalog or coverage (they're synced from another branch), so a
prune would try to delete them.

## 5. Add schedules

Times are IST. Swap `BRAND` for the tenant's name in capitals. Pick times that don't
collide with other tenants' (`python -m cli schedules list`). Jobs in the same lane queue
behind each other.

**Every tenant (once, whatever its marketplaces):**

```bash
python -m cli schedules add -n "BRAND | Auth refresh daily" --type auth.refresh -t <uuid> --cron "20 6 * * *"
```

This one schedule refreshes **all** the tenant's refreshable sessions (both Blinkit ones).
It skips itself if another job of the tenant is running, and always reports success, so
check sessions with `auth status`, not the job's status.

**Blinkit:**

```bash
python -m cli schedules add -n "BRAND | Blinkit seller daily"     --type scrape.blinkit_seller    -t <uuid> --cron "45 11 * * *" --catchup
python -m cli schedules add -n "BRAND | Blinkit scorecard weekly" --type scrape.blinkit_scorecard -t <uuid> --cron "15 10 * * 1" --catchup
python -m cli schedules add -n "BRAND | Blinkit marketing daily"  --type scrape.blinkit_marketing -t <uuid> --cron "30 13 * * *"   # only if they run ads
```

**Zepto** (one job does sales, POs and ads together, on one login):

```bash
python -m cli schedules add -n "BRAND | Zepto private daily" --type scrape.zepto -t <uuid> --cron "45 10 * * *"
```

**Public scrapes (optional, per marketplace):**

```bash
python -m cli schedules add -n "BRAND | Public keyword weekly (Blinkit)" --type scrape.public_keyword -t <uuid> --cron "0 1 * * 0" marketplace=blinkit workers=5
python -m cli schedules add -n "BRAND | Public own-SKU weekly (Blinkit)" --type scrape.public_skus    -t <uuid> --cron "0 5 * * 0" marketplace=blinkit workers=5
python -m cli schedules add -n "BRAND | Public keyword weekly (Zepto)"   --type scrape.public_keyword -t <uuid> --cron "0 2 * * 0" marketplace=zepto
python -m cli schedules add -n "BRAND | Public own-SKU weekly (Zepto)"   --type scrape.public_skus    -t <uuid> --cron "0 6 * * 0" marketplace=zepto
```

Before scheduling a Zepto public scrape, check it fits in the 12-hour job limit (see
"Size public scrapes" in step 6). A brand with many Zepto cities needs one schedule per
city, or a group of cities, instead of a single run.

```bash
python -m cli schedules list                        # check them
```

- **Blinkit seller and scorecard need `--catchup`.** They scrape only one day or week, so a
  run missed while the runner was down becomes a permanent gap. Blinkit marketing and
  Zepto re-read the last 7 days and fix themselves.
- **Don't hand-add `cm.*` schedules.** The campaign manager's reconciler creates them from
  the brand's rules (step 8).
- **Don't add a Zepto `auth.login` schedule** (see step 3).

## 6. Run everything once, now

Don't wait for cron to find out something's wrong. Queue each job once:

```bash
# Blinkit
python -m cli jobs run scrape.blinkit_seller    -t <uuid>
python -m cli jobs run scrape.blinkit_scorecard -t <uuid>
python -m cli jobs run scrape.blinkit_marketing -t <uuid>     # if they run ads

# Zepto
python -m cli jobs run scrape.zepto -t <uuid>

# Public (optional)
python -m cli jobs run scrape.public_keyword -t <uuid> marketplace=blinkit workers=5
python -m cli jobs run scrape.public_skus    -t <uuid> marketplace=blinkit workers=5
python -m cli jobs run scrape.public_keyword -t <uuid> marketplace=zepto "city=bengaluru"
python -m cli jobs run scrape.public_skus    -t <uuid> marketplace=zepto "city=bengaluru"

python -m cli jobs list                             # status of each
python -m cli jobs logs <job-id> -f                 # live-tail one
```

**Size public scrapes before starting them.** Each one runs over every covered store:

| | Blinkit | Zepto |
|---|---|---|
| Workers | parallel (`workers=5`) | **always one**, so `workers` is ignored. Zepto's search is heavily rate-limited |
| Measured pace | 2,059 stores: keyword 4.5–10 h (Dobra, 2026-09) | 169 stores: keyword ≈ 2 h, own-SKU ≈ 20 min (Brik Oven, 2026-09-01) |
| Job timeout | 12 h | 12 h |

A Zepto brand covering many cities can outrun the 12-hour limit (about 1,200 stores ≈ 14 h
for keywords). Run the first scrape **one city at a time** (`"city=<name>"`, quote it if it
has a space, like `"city=delhi ncr"`). If a run stops part-way, add `resume=true` and it picks
up from the stores it hadn't done yet.

Run these through `jobs run`, not `python -m cli scrape …` on your laptop, so they run from
the VM's Indian IP. The same goes for a backfill: add `date_from=YYYY-MM-DD date_to=YYYY-MM-DD`
(seller, marketing, Zepto) or `week=…` (scorecard). `python -m cli jobs types` lists each
job's parameters.

### Check the data actually landed

⚠️ **Don't trust `records_written` in `scrape_jobs` for Blinkit.** Blinkit seller and
marketing scrapes never fill it in, so it reads 0 even when data arrived. Zepto's count
is real. Check the tables instead (read-only):

```sql
-- replace <uuid>
SELECT 'blinkit_seller_sales' t, count(*), max(date)::text latest FROM blinkit_seller_sales WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'blinkit_soh',               count(*), max(date)::text          FROM blinkit_soh               WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'blinkit_scorecard_weekly',  count(*), max(scraped_at)::text    FROM blinkit_scorecard_weekly  WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'blinkit_ad_campaign_daily', count(*), max(date)::text          FROM blinkit_ad_campaign_daily WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'zepto_seller_sales_daily',  count(*), max(date)::text          FROM zepto_seller_sales_daily  WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'zepto_po',                  count(*), max(scraped_at)::text    FROM zepto_po                  WHERE tenant_id = '<uuid>'
UNION ALL SELECT 'zepto_ad_campaign_daily',   count(*), max(date)::text          FROM zepto_ad_campaign_daily   WHERE tenant_id = '<uuid>';
```

Zero rows can be genuine: no POs yet, no ad campaigns, or (on Zepto) every campaign
paused. Ask the brand before assuming a bug.

Public scrapes stage to a local SQLite file and **load into Postgres automatically when
they finish cleanly.** A partial run is not loaded:

```bash
python -m cli scrape staged --pending [-m zepto]    # anything waiting? (-m filters by marketplace)
python -m cli scrape load --file <ref>              # push it
python -m cli scrape discard --file <ref>           # or bin it
```

## 7. Build the SKU map

This links the brand's private item ids to the marketplace's public product ids. Without
it, the public panel on the Products page stays empty. It needs **both** a private scrape
and the own-SKU public scrape to have run.

```bash
python -m cli sku-map build --tenant <uuid> --file sku_map.xlsx   # auto-match + review workbook
# open sku_map.xlsx, fix any wrong or missing matches
python -m cli sku-map apply --tenant <uuid> --file sku_map.xlsx
```

⚠️ **Only for a brand on ONE marketplace.** `sku_map` has no marketplace column, and
`build` matches every private item against every public product the tenant has, on any
marketplace. For a brand on Blinkit **and** Zepto, a product listed under the same name on
both gets two candidates and ends up unmatched, which can undo mappings that already work.
**Skip this step for two-marketplace brands** until `sku_map` gets an `mp_slug` column.

## 8. Campaign Manager (only if they want automations)

Skip this whole step if the brand only wants dashboards. Every `cm` command needs
`-m blinkit` or `-m zepto`. There's no default, on purpose.

### 8a. Set the advertiser id

**This is the one step that can spend real money on the wrong account, so do it carefully.**

The advertiser id is the ad account every live bid/budget write goes to. Live writes are
**refused** until one is stored, and `cm arm` won't run without it.

**Blinkit** (an integer):

1. Read what Blinkit reports (read-only; it opens the brand's session):
   ```bash
   python -m cli cm advertiser -t <uuid> -m blinkit
   ```
   It prints `blinkit-derived = <n>`, the id from the brand's own campaign list. You
   don't need DevTools for this.
2. **If it says "couldn't read the marketplace-derived id"**, the brand probably has no
   campaigns yet, so the list carries no id. Get it from the dashboard instead: log in to
   Blinkit Brand Central as the brand, open DevTools → Network, load the campaigns page,
   and read `data.advertiser_id` from the `advertisers/campaigns` response.
3. Store it:
   ```bash
   python -m cli cm set-advertiser -t <uuid> -m blinkit --id <n>
   ```
4. Run `cm advertiser` again. `stored` and `blinkit-derived` should now match. If they
   ever differ, **stop**: live writes use the stored value.

**Zepto** (a brand UUID): the derived value comes from the login response and is
authoritative. We only use it to confirm the session belongs to the expected brand.

```bash
python -m cli cm advertiser     -t <uuid> -m zepto          # read the brand id
python -m cli cm set-advertiser -t <uuid> -m zepto --id <brand-uuid>
```

### 8b. Load their campaigns

```bash
python -m cli cm sync-campaigns -t <uuid> -m blinkit        # read-only; fills the pickers in the UI
python -m cli cm sync-campaigns -t <uuid> -m zepto
```

### 8c. Create rules, and watch them run dry

Create bid and budget rules in the dashboard at **Ads → Automation**. The reconciler then
creates the `cm.*` schedules by itself.

Everything runs **dry-run** until the tenant is armed: it computes and logs, but writes
nothing. Watch at least a day of runs in the Automation page's activity log (or
`cm_run_log`) before arming.

Measurement stores: the global per-city store set applies automatically. Only set a
per-client one if this brand needs different stores:

```bash
python -m cli cm stores show --city <city> -m blinkit                              # candidate stores
python -m cli cm stores set  --city <city> --store <merchant_id> --rank 1 -m blinkit -t <uuid>
```

See [campaign-manager.md §7.6c](campaign-manager.md).

### 8d. Arm for live writes (per marketplace)

```bash
python -m cli cm arm    -t <uuid> -m blinkit              # ⚡ writes to the marketplace from now on
python -m cli cm disarm -t <uuid> -m blinkit              # back to dry-run, any time
```

`arm` refuses if no advertiser id is stored. It reconciles immediately, so the tenant's
scheduled runs switch to live right away. Arming Blinkit doesn't arm Zepto, or the other
way round.

## 9. Final check

```bash
python -m cli status                                # runner alive, nothing overdue, no failures
python -m cli auth status --tenant <uuid>
python -m cli schedules list
```

Then open the dashboard, switch to the new client, and look at Overview, Marketing,
Reports and Competition, on each marketplace. Private data usually appears within a few
hours of the first runs.

### What usually goes wrong

| Symptom | Cause |
|---|---|
| `sync` says "Unknown tenant(s)" | The workbook's `tenant` doesn't match the tenant's name exactly |
| `sync` dry run shows `updated` / `deleted` rows | Your `config.xlsx` is out of date. Don't sync; get the current file |
| A competitor never appears in Competition | Its alias has capitals (must be lowercase), or doesn't match how the marketplace writes the brand |
| Login times out | Forwarding isn't set up, or points at the wrong address (`scripts.inbox_scan`) |
| Zepto login fails intermittently | OTP expired (5 min) behind a slow forward, or someone else logged in to that Zepto user |
| `scrape_jobs.records_written = 0` on Blinkit | Normal; that field is never filled for Blinkit. Check the tables (step 6) |
| Seller/scorecard data has holes | The schedule is missing `--catchup` |
| Products page has no public panel | SKU map not built or applied (step 7) |
| Automations compute but nothing changes | Tenant isn't armed on that marketplace (expected until 8d) |
| `cm arm` refuses | No advertiser id stored for that marketplace (8a) |
| A `cm` command errors about `--marketplace` | Add `-m blinkit` or `-m zepto` |

---

## 10. The Settings UI

Step 3 (credentials + login) can also be done in the dashboard. That's all the UI covers
for now, by design. Everything else in this doc is **CLI-only**: creating clients or
users, forwarding, the config workbook, schedules, the SKU map and the advertiser id.

**Status: on `dev`, not yet on `main`.** Tested end to end on 2026-09-22 (Brik Oven:
Disconnect → Connect on both Blinkit accounts, both logins worked first time).

### Using it

1. Switch to the new client in the client switcher.
2. Open **Settings** (admins only; `/connections` and `/onboarding` redirect there).
   It lists every marketplace with a status pill and its saved login email:
   - **Not set up**: no login email saved.
   - **Not signed in**: email saved, no session.
   - **Connected**: a session exists (not proof it works; use `auth probe`).
   - **Coming soon**: we can't log in to this marketplace yet (Instamart).
3. Click **Connect** on an account. A four-step modal opens:

| # | Step | What happens |
|---|---|---|
| 1 | Before you start | Explains the two stages |
| 2 | Forward emails | Gmail / Outlook / other steps for forwarding to "the address your Foresight contact gave you". The user ticks "I've set up forwarding" to continue |
| 3 | Connect account | Login email (+ password for Zepto). **Connect** saves the credentials and queues an `auth.login` job, which the VM runs |
| 4 | Finish | Shows whether the account is now connected |

While a login runs, the modal shows "Signing in…" and re-reads the account list every
4 s. It flips to connected as soon as the session appears. If nothing appears within
4 minutes, it says no sign-in email reached us and suggests checking forwarding. A real
failure (wrong email, marketplace error) also shows only as that timeout. Find the reason
with `python -m cli jobs list` and `python -m cli jobs logs <id>`.

**Reconnect** re-runs the login for a connected account. **Disconnect** deletes the
session **and** the saved credentials, so data stops updating and automations stop
until someone connects again. It does not turn off forwarding, which lives in the brand's mailbox.

### How it works

- **A login is a job, not a request.** It waits on mail arriving through a forward, which
  takes seconds at best and sometimes never comes. So the route queues `auth.login` and
  returns a job id.
- **Forwarding comes before credentials** in the modal because a login can't succeed until
  the mail reaches us.
- **Step ticks:** Connect and Finish tick only when a live session exists, the one thing the
  server can verify. "Forward emails" ticks on the user's own claim, since we can't see
  their mail rules. A live session overrides and locks it.

API, mounted at `/clients/{client_id}/platforms` (`app/routes/platforms.py`):

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `` | any user | Per platform: `wired`, `needs_password`, `has_credentials`, `login_email`, `connected`, `connected_at` |
| PUT | `/{platform}/credentials` | admin | Write-only; nothing reads a password back |
| POST | `/{platform}/login` | admin | Queues `auth.login`; **409** if one is already running |
| DELETE | `/{platform}` | admin | Deletes the session **and** the credentials |

These are the first routes to use `require_admin`. Service: `app/services/platform_service.py`
(delegates to `platform_auth.store`).

| Area | Files |
|---|---|
| API | `app/routes/platforms.py` · `app/schemas/platform.py` · `app/services/platform_service.py` |
| UI | `frontend/src/features/settings/` — `SettingsPage.jsx`, `components/onboarding/OnboardingModal.jsx`, `components/onboarding/AccountRow.jsx`, `components/ForwardingInstructions.jsx`, `hooks.js`, `api.js` |

## 11. Known gaps

- **`sku_map` isn't per marketplace** (step 7). Blocks the SKU map for any brand on both
  Blinkit and Zepto.
- **Blinkit scrapes never fill `scrape_jobs.records_written`** (step 6).
- **Tenant separation relies on the login email.** The inbox matches a sign-in mail to a
  tenant by the login address in To/Cc. A tenant that entered another tenant's login email
  would receive their session. Admin-gating narrows who can do this. The cheap fix: reject a
  login email another tenant already uses. The proper fix: match on the forwarding address
  instead (unverified whether Gmail keeps the `+tag` after a forward).
- **Login failures are only reported by timeout in the UI.** The UI polls the job through
  `…/campaign-manager/jobs/{id}`, which only serves `cm.*` jobs, so `auth.login` 404s there.
  Fix: a job-status endpoint that isn't campaign-manager specific.
- **No rate limit** on logins beyond one at a time per platform. On Zepto, every login also
  logs out whoever is using that account in a browser.
- **The UI's Outlook and "other" forwarding instructions forward the whole mailbox.**
  Gmail's uses a filter but doesn't name the senders. All three should list the senders
  from `platform_auth/mail_rules.py` (the table in step 2).
- **No per-member client access.** Every user sees all of the account's clients, and members
  can use every write route except the four above. Scoping a user to one brand needs a
  `user_clients` table (a migration), deliberately deferred. **Until then, don't give a
  login to anyone outside the team.**

See also: [platform-auth.md](platform-auth.md) (login machinery, mail rules) ·
[jobs-runbook.md](jobs-runbook.md) (schedules, jobs, logs) ·
[campaign-manager.md](campaign-manager.md) (automations, arming, stores) ·
[staging.md](staging.md) (public scrape staging/load).
