# Onboarding a new brand

This is the full checklist for bringing a new brand (a "client", i.e. a `tenants` row)
onto Foresight. Do the steps in order: each one depends on the one before it.

Run every command from `automation-mvp/backend` with the venv's Python
(`venv/Scripts/python.exe` on Windows, `venv/bin/python` on the VM). This doc writes
`python -m cli …` for short.

> **Every step here writes to the shared database** that the VM, Render and every laptop
> use. Nothing needs a migration. The VM runs `main`, so anything a step relies on must
> be merged there before scheduled jobs can use it.

---

## 0. Collect from the brand first

| What | Used in | Notes |
|---|---|---|
| Brand name, and its name as it appears on Blinkit | Steps 1, 4 | The slug goes in `config.xlsx` |
| Blinkit **ads** dashboard login email | Step 3 | Brand Central (magic link) |
| Blinkit **seller** dashboard login email | Step 3 | PartnersBiz (OTP) |
| Zepto login email **and password** | Step 3 | Only if they are on Zepto |
| Category keywords to track | Step 4 | For example `goli soda, nimbu soda` |
| Competitor brands | Step 4 | Include any alternate spellings |
| Cities they sell in | Step 4 | Must match catalog city names |
| Do they want bid/budget automations? | Step 8 | If yes, you also need their Blinkit ad-account id |

Each login email must be **unique to this brand**. Our inbox tells tenants apart by the
login address, so two tenants sharing one would receive each other's sessions (see §11).

---

## 1. Create the client (and users)

```bash
# Only for a new org. A brand under our agency goes into the existing account.
python -m cli account create --name "Foresight" --admin-email you@foresight.com
python -m cli account list                          # note the account id

python -m cli tenant create --name "BrandName" --account <account-id>
python -m cli tenant list                           # note the tenant uuid (used everywhere below)

# Optional: more logins on the account (member by default)
python -m cli account add-user --account <account-id> --email teammate@x.com [--name "Name"] [--admin]
```

- ⚠️ The `--name` must match the `tenant` column in `config.xlsx` **exactly, including
  case**, because `cli sync` looks tenants up by name.
- ⚠️ **Don't give anyone at the brand a login yet.** Every user of an account sees every
  client in it, and members are not read-only (see §11).

## 2. Set up mail forwarding (in the brand's mailbox)

Marketplaces log in by emailing a magic link or OTP. We log in unattended by reading
that mail from our shared auth mailbox (`AUTH_INBOX_USER` in `.env`), so **the brand must
forward those emails to us before any login can work.**

Send the brand the auth mailbox address yourself (the UI deliberately doesn't show it).
Ask them to forward these senders:

| Platform | From | Subject |
|---|---|---|
| Blinkit ads | `brands@blinkit.com` | `Sign in to Blinkit Brand Central` |
| Blinkit seller | `noreply@partnersbiz.com` | `Your OTP for PartnersBiz login` |

Ask for a **filter on those senders** rather than forwarding the whole mailbox.

If a login later times out, check whether the mail is actually arriving:

```bash
python -m scripts.inbox_scan --limit 25 --email <brand login address>
```

## 3. Save credentials and log in (each platform they use)

```bash
python -m cli auth platforms                        # which platforms are wired

python -m cli auth credentials set blinkit        -t <uuid> --email ads@brand.com
python -m cli auth credentials set blinkit_seller -t <uuid> --email seller@brand.com
python -m cli auth credentials set zepto          -t <uuid> --email ops@brand.com --password   # prompts; Zepto needs one

python -m cli auth login blinkit        -t <uuid>
python -m cli auth login blinkit_seller -t <uuid>
python -m cli auth login zepto          -t <uuid>

python -m cli auth probe blinkit -t <uuid>          # is the session ACTUALLY alive? (repeat per platform)
python -m cli auth status --tenant <uuid>
```

- Trust `auth probe`, not `expires_at`.
- After this, sessions look after themselves. Scrapers call `ensure()`, and the daily
  `auth.refresh` job (step 5) keeps them extended.
- **Zepto allows one session per user.** Our login logs out anyone using that account in a
  browser, and their login kills ours. The client has accepted this, so jobs just log in
  again when they must. Don't schedule a Zepto `auth.login`.
- Stuck after repeated failures? Clear the circuit breaker with
  `python -m cli auth reset <platform> -t <uuid>`.

You can do this step from the UI instead (§10). The CLI is more reliable today.

## 4. Configure public data (`config.xlsx`, then `sync`)

`backend/config.xlsx` is the source of truth for public scraping. Edit it, then sync.

**`brands` sheet:** one `own` row plus one row per competitor.

| tenant | brand | relationship | keywords | aliases | keyword_cap | brand_cap |
|---|---|---|---|---|---|---|
| BrandName | brandslug | own | goli soda, nimbu soda, … | brandslug, brand name | 36 | 48 |
| BrandName | rival-brand | competitor | | rival-brand, rival | | |

- `keywords` go on the `own` row only.
- `keyword_cap` is how many results per keyword are read. `brand_cap` is how many of the
  brand's own SKUs the targeted scrape reads. Dobra uses 36 / 48.

**`coverage` sheet:** one row per city (`mp`, `tenant`, `city`). A blank `mp` means Blinkit.

**`locations` / `city_map` sheets:** leave these alone unless a city is missing from the
catalog (about 3,300 stores are already there).

```bash
python -m cli sync --file config.xlsx --dry-run     # read the plan first
python -m cli sync --file config.xlsx

python -m cli watchlist list --tenant <uuid>        # check it landed
python -m cli locations list --tenant <uuid>
```

⚠️ If the dry run proposes deleting any `locations`, **stop and check.** Only use
`--prune` when you mean to remove rows.

## 5. Add schedules

Times are IST. These mirror Dobra's setup. Swap `BRAND` for the tenant's name.

```bash
python -m cli schedules add -n "BRAND | Blinkit marketing daily"  --type scrape.blinkit_marketing -t <uuid> --cron "15 13 * * *"
python -m cli schedules add -n "BRAND | Blinkit seller daily"     --type scrape.blinkit_seller    -t <uuid> --cron "30 11 * * *" --catchup
python -m cli schedules add -n "BRAND | Blinkit scorecard weekly" --type scrape.blinkit_scorecard -t <uuid> --cron "0 10 * * 1"  --catchup
python -m cli schedules add -n "BRAND | Auth refresh daily"       --type auth.refresh             -t <uuid> --cron "10 6 * * *"

# Only if on Zepto
python -m cli schedules add -n "BRAND | Zepto private daily"      --type scrape.zepto             -t <uuid> --cron "30 10 * * *"

# Optional: public scrapes (no tenant has these scheduled today)
python -m cli schedules add -n "BRAND | Public keyword weekly"    --type scrape.public_keyword    -t <uuid> --cron "0 1 * * 0" workers=5
python -m cli schedules add -n "BRAND | Public own-SKU weekly"    --type scrape.public_skus       -t <uuid> --cron "0 5 * * 0" workers=5

python -m cli schedules list                        # check them
```

- **Seller and scorecard need `--catchup`.** They scrape only one day or week, so a run
  missed while the runner was down becomes a permanent gap. Marketing re-scrapes 7 days
  and fixes itself.
- **Don't hand-add `cm.*` schedules.** The campaign manager's reconciler creates them from
  the brand's rules (step 8).
- Spread new tenants' times out a little, so their runs don't all queue on the same lane at once.

## 6. Run everything once, now

Don't wait for cron to find out something's wrong. Queue each job once:

```bash
python -m cli jobs run scrape.blinkit_marketing -t <uuid>
python -m cli jobs run scrape.blinkit_seller    -t <uuid>
python -m cli jobs run scrape.blinkit_scorecard -t <uuid>
python -m cli jobs run scrape.public_keyword    -t <uuid> workers=5
python -m cli jobs run scrape.public_skus       -t <uuid> workers=5

python -m cli jobs list                             # status of each
python -m cli jobs logs <job-id> -f                 # live-tail one
```

Public scrapes stage to a local SQLite file and **load into Postgres automatically when
they finish cleanly.** A partial run is not loaded:

```bash
python -m cli scrape staged --pending               # anything waiting?
python -m cli scrape load --file <ref>              # push it
python -m cli scrape discard --file <ref>           # or bin it
```

## 7. Build the SKU map

This links the brand's private item ids to Blinkit's public product ids. Without it, the
public panel on the Products page stays empty. It needs **both** the seller scrape and
the own-SKU scrape from step 6 to have run.

```bash
python -m cli sku-map build --tenant <uuid> --file sku_map.xlsx   # auto-match + review workbook
# open sku_map.xlsx, fix any wrong or missing matches
python -m cli sku-map apply --tenant <uuid> --file sku_map.xlsx
```

## 8. Campaign Manager (only if they want automations)

Skip this whole step if the brand only wants dashboards.

### 8a. Set the advertiser id

**This is the one step that can spend real money on the wrong account, so do it carefully.**

The advertiser id is the ad account every live bid/budget write is sent to. Blinkit
doesn't let us check it against the campaign, so a wrong id sends writes to someone else's
account. Live writes are **refused** until one is stored, and `cm arm` won't run without it.

**Blinkit** (an integer):

1. Read what Blinkit reports for this session (read-only):
   ```bash
   python -m cli cm advertiser -t <uuid> -m blinkit
   ```
   It prints `blinkit-derived = <n>`, the id from the brand's own campaign list.
2. Cross-check it in the dashboard. Log in to Blinkit Brand Central as the brand, open
   DevTools → Network, and load the campaigns page. The `advertisers/campaigns` response
   contains `data.advertiser_id`. Both numbers must match.
3. Store it:
   ```bash
   python -m cli cm set-advertiser -t <uuid> -m blinkit --id <n>
   ```
4. Run `cm advertiser` again. `stored` and `blinkit-derived` should now be the same.
   If they ever differ, **stop**: live writes use the stored value.

**Zepto** (a brand UUID): the derived value comes from the login response and is
authoritative. We only use it to confirm the session belongs to the expected brand.

```bash
python -m cli cm advertiser     -t <uuid> -m zepto          # read the brand id
python -m cli cm set-advertiser -t <uuid> -m zepto --id <brand-uuid>
```

### 8b. Load their campaigns

```bash
python -m cli cm sync-campaigns -t <uuid> -m blinkit        # read-only; fills the pickers in the UI
```

### 8c. Create rules, and watch them run dry

Create bid and budget rules in the dashboard at **Ads → Automation**. The reconciler then
creates the `cm.*` schedules by itself.

Everything runs **dry-run** until the tenant is armed: it computes and logs, but writes
nothing. Watch at least a day of runs in the Automation page's activity log (or
`cm_run_log`) before arming.

Measurement stores: the global per-city store set applies automatically. Only set a
per-client one if this brand needs different stores (`cm stores set -t <uuid> --rank N …`,
see [campaign-manager.md §7.6c](campaign-manager.md)).

### 8d. Arm for live writes

```bash
python -m cli cm arm    -t <uuid> -m blinkit              # ⚡ writes to the marketplace from now on
python -m cli cm disarm -t <uuid> -m blinkit              # back to dry-run, any time
```

`arm` refuses if no advertiser id is stored. It reconciles immediately, so the tenant's
scheduled runs switch to live right away.

## 9. Final check

```bash
python -m cli status                                # runner alive, nothing overdue, no failures
python -m cli auth status --tenant <uuid>
```

Then open the dashboard, switch to the new client, and look at Overview, Marketing,
Reports and Competition. Private data usually appears within a few hours of the first runs.

### What usually goes wrong

| Symptom | Cause |
|---|---|
| `sync` doesn't see the tenant | The workbook's `tenant` doesn't match the tenant's name exactly |
| Login times out | Forwarding isn't set up, or points at the wrong address (`scripts.inbox_scan`) |
| Seller/scorecard data has holes | The schedule is missing `--catchup` |
| Products page has no public panel | SKU map not built or applied (step 7) |
| Automations compute but nothing changes | Tenant isn't armed (expected until 8d) |
| `cm arm` refuses | No advertiser id stored (8a) |

---

## 10. The Settings UI

Step 3 (credentials + login) can also be done in the dashboard. Everything else in this
doc is **CLI-only**: there is no UI yet for creating clients or users, the config
workbook, schedules, the SKU map or the advertiser id.

**Status: on `dev`, not yet on `main`.**

### Using it

1. Switch to the new client in the client switcher.
2. Open **Settings** (admins only; `/connections` and `/onboarding` redirect there).
   It lists every marketplace account with a status pill and its saved login email.
3. Click **Connect** on an account. A four-step modal opens:

| # | Step | What happens |
|---|---|---|
| 1 | Before you start | Explains the two stages |
| 2 | Forward emails | Gmail / Outlook / other steps for forwarding to "the address your Foresight contact gave you". The user ticks "I've set up forwarding" to continue |
| 3 | Connect account | Login email (+ password for Zepto). **Connect** saves the credentials and queues an `auth.login` job |
| 4 | Finish | Shows whether the account is now connected |

While a login runs, the modal shows "Signing in…" and re-reads the account list every
4 s. It flips to connected as soon as the session appears. If nothing appears within
4 minutes, it says no sign-in email reached us and suggests checking forwarding.

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

- **Tenant separation relies on the login email.** The inbox matches a sign-in mail to a
  tenant by the login address in To/Cc. A tenant that entered another tenant's login email
  would receive their session. Admin-gating narrows who can do this. The cheap fix: reject a
  login email another tenant already uses. The proper fix: match on the forwarding address
  instead (unverified whether Gmail keeps the `+tag` after a forward).
- **Login failures are only reported by timeout.** The UI polls the job through
  `…/campaign-manager/jobs/{id}`, which only serves `cm.*` jobs, so `auth.login` 404s there.
  Success still shows because the account list is re-read. A failure shows only after the
  4-minute wait. Fix: a job-status endpoint that isn't campaign-manager specific.
- **No rate limit** on logins beyond one at a time per platform. On Zepto, every login also
  logs out whoever is using that account in a browser.
- **The Gmail instructions forward the whole mailbox.** They should be a filter scoped to the
  senders in `platform_auth/mail_rules.py`.
- **No per-member client access.** Every user sees all of the account's clients, and members
  can use every write route except the four above. Scoping a user to one brand needs a
  `user_clients` table (a migration), deliberately deferred. **Until then, don't give a
  login to anyone outside the team.**
- **No UI** for anything outside step 3 (see §10).

See also: [platform-auth.md](platform-auth.md) (login machinery, mail rules) ·
[jobs-runbook.md](jobs-runbook.md) (schedules, jobs, logs) ·
[campaign-manager.md](campaign-manager.md) (automations, arming, stores) ·
[staging.md](staging.md) (public scrape staging/load).
