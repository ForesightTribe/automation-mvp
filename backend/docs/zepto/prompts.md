# Zepto Private Scraping — Prompts

Three kinds of "prompt", in one place:

1. **[Interactive prompts](#1-interactive-prompts)** — what the CLI asks a human at the
   keyboard, and which of them block an unattended VM run
2. **[API request payloads](#2-api-request-payloads)** — the exact bodies and params we
   send Zepto
3. **[Reusable AI prompts](#3-reusable-ai-prompts)** — ready-to-paste briefs for
   working on this system with an agent

---

# 1. Interactive prompts

## What blocks an unattended run

| Prompt | Command | Blocks the VM? |
|---|---|---|
| Password entry | `auth credentials set zepto --password` | **One-time only.** Stored encrypted; never asked again |
| Email | `auth credentials set zepto --email <e>` | No — passed as a flag |
| 4-digit OTP | `auth login zepto` | **No.** Read from the inbox over IMAP |
| Confirmations | the three scrapes | None — they prompt for nothing |

> **Nothing in the Zepto private path blocks on a human, once credentials are stored.**
> This is the whole reason it can be scheduled. The old browser login (`cli auth
> zepto-seller`, deleted) *did* block on a typed OTP and needed Xvfb; that is gone.

## The one prompt that exists

```
$ python -m cli auth credentials set zepto -t fa53082e-… --email ops@brikoven.com --password
Password: ********
Stored credentials for zepto (tenant fa53082e-…)
```

`--password` deliberately takes **no value**. It prompts, so the secret never reaches
shell history or the process table. See [security.md](security.md).

## What a healthy unattended login looks like

```
Zepto Brand Console (brands.zepto.co.in): starting login (ops@brikoven.com) — attempt 1/2
Waiting for OTP email…
OTP received (4 digits)
Zepto Brand Console (brands.zepto.co.in): session saved.
```

No keyboard input at any point.

## Manual OTP fallback

`platform_auth/inbox/manual.py` exists for when the inbox reader cannot be used —
it prompts at the terminal instead. **Never use it on the VM**: it will hang a
scheduled job until the timeout.

---

# 2. API request payloads

Host for everything: `https://fcc.zepto.co.in`
Origin/Referer: `https://brands.zepto.co.in` — **not decoration**, the API checks them.

## Header recipes

Pick by endpoint family. Getting this wrong produces errors that look like something
else entirely — see [errorhandling.md](errorhandling.md).

```http
# COMMON — every call
accept: application/json, text/plain, */*
content-type: application/json
origin: https://brands.zepto.co.in
referer: https://brands.zepto.co.in/
user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 …
authorization: <RAW JWT>          ← NO "Bearer " prefix. Prefixing = base64 decode error
```

```http
# + for /brand-analytics-web/*        (sales)          client.request(brand_analytics=True)
x-proxy-target: brand-analytics
#   missing → bare text/plain 404 that reads like a wrong URL

# + for /ads-bff/*                    (ads)            client.request(brand_analytics=False)
x-aws-waf-token: <token>
waf-enabled: false
#   missing EITHER → 429, which reads exactly like rate limiting

# + for /api/v1/* and /vendor/*       (PO, discovery)  brand_analytics=True
#   neither header needed
```

## Auth

```http
POST /api/v1/auth/sign-in
{"email": "<email>", "password": "<password>"}
→ 200, every field null EXCEPT mfaEnabled / mfaId. Emails a 4-digit OTP.

POST /vendor/api/v1/auth/validate-mfa-otp/        ← trailing slash REQUIRED
{"mfaId": "<mfaId>", "otp": "1234"}
→ JWT + brandIds

GET  /vendor/api/v1/auth/get-user-by-token        ← the probe. Cheapest authed read
```

Two application ids, both constants of the app, both load-bearing — sending the wrong
one fails the call:

```
APP_ID        d0cd4873-7cb3-4c7c-9a25-3b109a0d2301   sign-in and MFA
PARENT_APP_ID 1bddc95b-3201-4c15-b19a-ed03bd579f97   get-user-by-token
```

OTP: **4 digits**, valid **300 seconds**.

## Discovery — run fresh every scrape, nothing hardcoded

```http
GET /api/v1/filter/city-list
GET /api/v1/commons/brand-category-mapping
```

⚠️ `discover_ids` takes `brandCategoryList[0]`. Multi-brand accounts silently use only
the first. Untested.

## Sales

```http
GET /brand-analytics-web/api/v1/sales-analytics/sales-overview
    ?brandIds=<id>
    &brandNames=<name>
    &subcategoryNames=<a>|<b>|<c>        ← pipe-separated
    &subcategoryIds=<a>,<b>,<c>          ← comma-separated
    &cityIds=<a>,<b>
    &startDate=2026-09-01
    &endDate=2026-09-01
    &viewType=BRAND
    &aggregationLevel=DAY
```

⚠️ **Note the two different separators in one query string.** `subcategoryNames` uses
`|`, everything else uses `,`.

```http
GET /brand-analytics-web/api/v1/sales-analytics/product-performance
    (same params; add cityIds=<one city> for the per-city split)
```

### The "not computed yet" response

Zepto refreshes once each morning. Ask for a day it has not processed and the response
is **structurally different** — the `headers` block carrying the totals is **absent**
and every point in `metrics` is null:

```
2026-08-28   headers present   gmv ₹64,280
2026-08-29   headers present   gmv ₹54,275
2026-08-30   headers ABSENT    gmv null      ← still not ready the next morning
```

This raises `NoDataYet`, not a generic failure. It means *try later*, not *broken*.
Reading `data["headers"]` blind used to surface as `Scrape failed: 'headers'` with no
hint that the only problem was asking too early. This is why `--to` defaults to
yesterday.

## Ads

```http
GET /ads-bff/api/v1/campaigns
    ?selectedBrand=<brand_id>&brand_id=<brand_id>
    &from_date=2026-09-01&to_date=2026-09-01
    &categoryType=sponsored_products&page=0
```

⚠️ **`categoryType` is ignored by this endpoint.** Asking for any of the three returns
the same 26 campaigns (verified 20-Aug-2026). Only `/metrics/tabular` actually
partitions.

```http
POST /ads-bff/api/v1/brands/analytics/metrics/tabular
{
  "from": "2026-09-01 00:00:00",        ← note: datetime strings, not dates
  "to":   "2026-09-01 23:59:59",
  "view": "campaign_table",
  "size": 50,
  "page": 0,
  "campaign_category": "sponsored_products",
  "brand_id": "<brand_id>"
}
```

Six views, all through this one endpoint:
`campaign_table` · `product_table` · `keyword_table` · `category_table` · `city_table`
· `page_table`

```http
POST /ads-bff/api/v1/brands/analytics/metrics
{"breakdown": true, "brand_id": "<brand_id>", …}
```

Metrics: `spends`, `ctr`, `impressions_per_thousand`, `clicks`, `ecpm`.
A 1.5s pause sits between metric calls.

## PO / ASN / GRN

All three POST to `/api/v1/{po,grn,asn}/filter`, share the shape
`{list_key, total, hasNext}`, and page at 100 (max 20 pages = **2,000 rows, then
silent truncation**).

```http
POST /api/v1/po/filter
{
  "vendorCodes": [], "locationCodes": [],
  "poStartDate": "2026-08-31T18:30:00.000Z",     ← see the timezone note below
  "poEndDate":   "2026-09-02T18:29:59.999Z",
  "statusList": [],                               ← empty = every status
  "ids": [],
  "scheduledStartDate": null, "scheduledEndDate": null,
  "expiryStartDate": null, "expiryEndDate": null,
  "offset": 0, "limit": 100
}
→ {"poList": [...], "total": n, "hasNext": bool}
```

```http
POST /api/v1/grn/filter
{..., "grnStartDate": …, "grnEndDate": …, "grnNos": [], "poIds": []}   → grnList

POST /api/v1/asn/filter
{..., "asnStartDate": …, "asnEndDate": …, "asnNos": [], "extAsnNos": [],
      "poIds": [], "trackingId": ""}                                    → asnList

GET  /api/v1/po/{po_id}/items      ← one call PER PO. The second pass.
```

### ⚠️ The timezone trap

PO filters take **IST day boundaries expressed in UTC**:

```
start = (date_from - 1 day) + "T18:30:00.000Z"
end   =  date_to            + "T18:29:59.999Z"
```

Sending plain dates returns a window shifted by 5h30m, quietly dropping the first and
last few hours of orders. **No error — just fewer rows.**

### `statusList: []`

Empty means *every status*. The browser sends one value because its UI is on a tab;
copying that from a capture silently filters the result.

## Empty results are 200, not 404

```json
{"success": true, "data": null}
```

Verified 2026-08-31 on `grn/filter`. A filter matching nothing returns this, so callers
coerce with `or {}` to avoid `AttributeError` on `None`.

---

# 3. Reusable AI prompts

Paste-ready briefs. Each assumes the agent can read this folder.

## Onboarding a fresh session

```
Read backend/docs/zepto/architecture.md and database.md before touching anything.

Key context you will otherwise get wrong:
- Two independent credentials: the JWT (identity, from platform_auth, dies at
  midnight IST, NOT refreshable) and the aws-waf-token (anonymous proof-of-browser,
  ~5 min, minted by a headless Chromium in transport.py). 401 = re-login,
  202/429 = re-mint. Never confuse them.
- 429 here usually means a MISSING `waf-enabled: false` header, not rate limiting.
- Three endpoint families need three different header sets. See prompts.md §2.
- Client is Brik Oven, tenant fa53082e-7e83-424d-aab9-086fe1b4c680.
- One shared Supabase DB behind every branch. A migration affects every branch.

Confirm you have read them by telling me which of the eleven tables triple-counts
if you sum it without a filter.
```

## Add a new Zepto private endpoint

```
Add <endpoint> to the Zepto private scraper. Follow the existing shape exactly:

1. URL constant in scraper/platforms/zepto/dashboard_data/seller/endpoints.py
2. fetch_* in scraper.py — raw JSON out, NO parsing, NO I/O beyond the call.
   Route it through client.request(..., retry_writes=False). Set
   brand_analytics=True for /brand-analytics-web/* and /vendor/*; leave it
   False for /ads-bff/*.
3. parse_* in parser.py — pure function, raw JSON -> list[dict], each with an
   upsert_key from make_upsert_key(tenant, "zepto", "<kind>", <identity parts>).
4. save_* in storage.py if a new table is needed.
5. Model in app/models/zepto_seller.py with the five bookkeeping columns
   (tenant_id, platform, upsert_key, scrape_job_id, scraped_at).

Do NOT add a browser. Do NOT hardcode brand/city/category ids — use discover_ids.
Before proposing a migration, prove the grain: scrape the SAME rows for two
different windows and show whether each column moves. Columns that do not move
are scrape-time snapshots and must not go in a date-keyed table.
```

## Debug an auth or WAF failure

```
A Zepto scrape is failing with <status/message>. Diagnose before changing code.

Decision tree:
  401       identity gone       -> bounded re-login (MAX_REAUTH_PER_RUN=2)
  202/429   browser proof gone  -> re-mint the WAF token
  429       ALSO the symptom of a missing `waf-enabled: false` header. CHECK THE
            HEADERS FIRST — this misreading cost an afternoon once already.
  404 bare text/plain -> missing `x-proxy-target: brand-analytics`
  500 on /vendor/*    -> Zepto's upstream timing out. Retried at 5/15/45s.
  200 + data:null     -> genuinely no rows. Not an error.

Reproduce with:
  LOG_LEVEL=DEBUG python -m cli scrape zepto-sales -t <tenant> --no-save

Test the hypothesis with a real request before recommending a fix. Do not rely on
what a comment says the behaviour is — comments in this area have gone stale.
```

## Backfill a date range

```
Backfill Zepto <sales|ads|po> for <range> for tenant <uuid>.

Before running:
- Sales: period_start/period_end are PART OF THE GRAIN. A 31-day window writes ONE
  31-day row per SKU, not 31 daily rows. Loop one day at a time for daily rows.
- Ads: leave --category at `all`. The three tabs return DISJOINT campaigns.
- PO: keys have no date, so re-scraping updates a PO in place. There is no history
  of how a PO evolved. Windows over ~2,000 rows truncate silently at PO_MAX_PAGES.
- Every login evicts whoever is on the client's dashboard. Do not loop logins.

All writes are idempotent (ON CONFLICT upsert_key), so re-running is safe.
Show me the command list first; do not run it.
```

## Move the private scrapers onto the VM

```
Goal: run the Zepto private scrapers on foresight-vm as scheduled jobs.

Read backend/docs/zepto/phase.md — Phase 5 is exactly this and lists the gaps.
Known blockers, do not rediscover them:
  1. The VM runs `main`. `main` has no zepto-po, no scorecard, and still carries
     the OLD browser auth. dev is 23 commits ahead. This is the real gate.
  2. jobs/types.py registers only scrape.zepto_seller_sales. zepto-ads and
     zepto-po have NO job type and cannot be queued at all.
  3. No Zepto schedule has ever existed; no Zepto job has ever been queued.
  4. auth.login for Zepto must stay --disabled until Brik Oven provisions a
     service user. Enabling it logs their own staff out nightly.
  5. ENCRYPTION_KEY must match exactly or sessions fail SILENTLY.

Every private run launches headless Chromium once (~1 GB, ~10s) to mint the WAF
token, so Playwright must be installed on the box: `playwright install chromium`
WITHOUT sudo, `playwright install-deps chromium` WITH sudo.
```

## Review a change before it ships

```
Review this Zepto private-scraper change against backend/docs/zepto/.

Check specifically:
- Does any summable column actually vary by date, or is it a scrape-time snapshot?
- Does a new sum cross two grains (e.g. zepto_seller_sales + the city table, or
  zepto_ad_breakdown_daily without a dimension filter)?
- Is upsert_key unique at the true grain?
- Are new failure paths logged at ERROR? Below that the alert never fires.
- Does it hardcode a brand/city/category id?
- Does it add a browser to the data path? (Only transport.py may launch one.)
- Does it print a JWT, password or OTP anywhere?

Cite file:line for each finding.
```

## Update these docs

```
Update backend/docs/zepto/*.md to match the code as it is NOW.

Rules:
- Verify every claim against the code or a live query. Do not carry a claim
  forward because the doc already said it — docs/zepto-auth.md at the repo root
  is stale in exactly that way and is the cautionary example.
- Where something is unproven, say "unproven" rather than guessing.
- Keep the live row counts in database.md dated, and re-measure rather than
  editing the numbers by hand.
- architecture.md §11 lists known-stale CODE comments. If you fix one in code,
  remove it from that table.
```
