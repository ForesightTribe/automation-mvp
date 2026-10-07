# Zepto Private Scraping — Architecture

> **Scope: the private plane only.** This is Foresight logging into Zepto's brand
> console as the seller and pulling data only that account can see — sales, ads,
> purchase orders. The *public* plane (consumer app, no login, shared
> `search_snapshots` / `search_listings` / `sku_snapshots` keyed by `mp_slug`) is a
> different system with different tables and is not covered here.
>
> Companion docs in this folder: [database.md](database.md) ·
> [cli.md](cli.md) · [security.md](security.md) ·
> [errorhandling.md](errorhandling.md) · [phase.md](phase.md) ·
> [prompts.md](prompts.md). The refactor plan and decision log (item ids P1…P54) is
> `backend/zepto-cm-exp/plans/PLAN-private-scrape.md` (gitignored).

---

## 1. The one-paragraph version

**One command, `cli scrape zepto`, one login, three sections** — sales, PO, ads — run in
turn on **one shared authenticated client**. Each section makes plain `httpx` calls
against `fcc.zepto.co.in`, parses the JSON into row dicts and upserts them into the
`zepto_*` tables (fifteen; see [database.md](database.md)). The ads section also refreshes
the **campaign catalogue** the campaign manager reads. A further surface, the
**scorecard**, scrapes nothing at all — it is derived in SQL from the PO tables.
Authentication is the shared `platform_auth` package (email + password → emailed OTP →
JWT), and a **headless Chromium is launched once per run purely to mint an AWS WAF
token**. On the VM it runs as the `scrape.zepto` job, once a day per tenant.

---

## 2. Two credentials, not one

This is the single most important idea in the system, and conflating the two is the
source of most confusion.

| | `jwt` | `aws-waf-token` |
|---|---|---|
| **What it proves** | *who* we are | *that a browser exists* |
| **Where it comes from** | `platform_auth` login (email+password+OTP) | headless Chromium loading the **public** console page |
| **Anonymous?** | No — it is the identity | **Yes** — no login involved |
| **Lifetime** | dies at **local midnight IST**, or the instant another login evicts it | **~5 minutes** (alive at 4, dead at 6) |
| **Refreshable?** | **No.** No endpoint exists | n/a — re-minted on demand |
| **Stored?** | Yes, encrypted in `platform_sessions` | **Never.** Every job interval outlives it |
| **Failure signal** | `401` | `202` (challenge) or CloudFront's `429` (empty body) |
| **Recovery** | re-login, bounded | re-mint, unbounded |

> Burning an OTP on a problem a missing header would have fixed is the concrete cost
> of mixing these up. `401` and `429` are **not** the same class of failure here.
>
> A third failure looks like the WAF one and is not: Zepto's **own** rate limit, a `429`
> with a JSON body `{"error":"rate limit exceeded"}`. A fresh token does nothing for it;
> the client waits (5 s, 15 s, 30 s) and resends with the same token (P53, 2026-10-06).

---

## 3. Where the browser actually is

`scraper/platforms/zepto/dashboard_data/seller/client.py::mint_waf_token`

```
headless Chromium loads brands.zepto.co.in  →  aws-waf-token cookie  →  browser closed
every real API call then runs over plain httpx, carrying that token
```

The browser is a **token faucet, not the transport.** That is the important difference
from Blinkit, where Cloudflare rejects `httpx` outright and every fetch must happen
inside a live page.

Two consequences worth internalising:

- **Every Zepto private run launches Chromium once**, even `--sales` or `--po` alone,
  which do not otherwise need a WAF token. `setup()` mints unconditionally. Budget ~1 GB
  resident for ~10 seconds, not for the run.
- Re-minting **relaunches**; it never holds a browser open. Holding Chromium for a
  whole run costs ~1 GB for the run instead of ~1 GB for ten seconds.

Nothing else under `scraper/platforms/zepto/dashboard_data/` imports Playwright.

---

## 4. Module map

```
backend/
├── platform_auth/                          ← WHO we are
│   ├── registry.py                         slug "zepto" → Authenticator
│   ├── service.py                          ensure() / login() / probe() / breaker
│   ├── store.py                            encrypted read+write of platform_sessions
│   ├── mail_rules.py                       how to find Zepto's OTP email
│   ├── inbox/imap.py                       reads the shared auth mailbox
│   └── marketplaces/zepto/
│       ├── console.py                      start_login / complete_login / probe
│       └── endpoints.py                    login URLs, app ids, header rules
│
├── scraper/platforms/zepto/dashboard_data/seller/     ← everything the scrape does
│   ├── client.py                           ★ ZeptoClient, mint_waf_token, setup()
│   ├── endpoints.py                        every data URL, API host, WAF header constants
│   ├── scraper.py                          fetch_* — HTTP only, raw JSON out; also the
│   │                                       campaign reads the CM shares (get_campaigns …)
│   ├── parser.py                           parse_* — raw JSON → row dicts + upsert_key
│   ├── storage.py                          save_* — chunked ON CONFLICT upserts
│   ├── run.py                              the loops: run(), run_sales/po/ads → SectionResult
│   └── tests/                              test_parser · test_run · test_client
│
├── scraper/utils/
│   ├── retry.py                            retry_call — the one 5xx retry helper
│   ├── run_log.py                          tagged step logging (zepto·<tenant>·<section>)
│   └── jobs.py                             scrape_jobs rows (create / complete / fail)
│
├── campaign_manager/marketplaces/zepto/
│   ├── client.py                           writes (PUT / pause / activate); re-exports the reads
│   └── endpoints.py                        CM-only paths + platform bounds
│
├── app/models/zepto_seller.py              all fifteen SQLModel tables
├── app/services/zepto_*.py                 dashboard reads (ads, products, reports, scorecard …)
├── cli/commands/scrape.py                  `scrape zepto` — flags + exit code only
└── jobs/types.py                           `scrape.zepto` job type
```

Same four files as Blinkit's seller scrape, plus `run.py` and `client.py`. Zepto has **one**
console behind one login, so it is one folder, one command and one job — not Blinkit's
split into two dashboards.

The client used to live in `campaign_manager/marketplaces/zepto/transport.py`, so the
scrape imported the campaign manager to get it. Moved 2026-10-06 (P12): the client and the
four campaign reads now sit with the scrape, and the campaign manager imports them — the
same direction Blinkit's campaign manager imports from `platform_auth`. Not under
`platform_auth/` because the WAF token is not identity (§2).

---

## 5. The call chain

```
cli scrape zepto -t <tenant> [--sales] [--po] [--ads]      (none = all three)
│
└─ run.run(tenant, …)
     ├─ setup(tenant)                          seller/client.py
     │    ├─ auth_service.ensure(db, tenant, "zepto")
     │    │    ├─ load encrypted session ────────────── platform_sessions
     │    │    ├─ probe it (GET get-user-by-token)
     │    │    ├─ refresh?  →  NO. Zepto has none
     │    │    └─ dead? → login():
     │    │         POST /api/v1/auth/sign-in {email, password}  → mfaId, OTP emailed
     │    │         IMAP reads the 4-digit OTP from the shared inbox
     │    │         POST /vendor/api/v1/auth/validate-mfa-otp/    → JWT + brandIds
     │    └─ mint_waf_token()                  headless Chromium, ~10s
     │
     ├─ run_sales   overview (8 days) · products one day per call · city split ·
     │              stock readings (zepto_soh)
     ├─ run_po      po / grn / asn filters (30 days back, through today) · lines per PO
     ├─ run_ads     per day (3 days): campaign list + 6 analytics views per category +
     │              keyword detail per active keyword campaign · then the catalogue
     │
     │   each section:  fetch_*  →  parse_*  →  re-check what was lost  →  save_*
     │                  and returns a SectionResult (written · lost · recovered · not_ready)
     │
     └─ an AuthError stops the run (exit 3); any other section failure is isolated
```

The `fetch → parse → save` split is the house rule from
[docs/code-standards.md](../../../docs/code-standards.md): **fetchers never parse and
parsers never do I/O.** It is what makes a scrape replayable from a captured payload.

**One SectionResult drives everything after:** the `scrape_jobs` row (success, or failed
"partial: N fetch(es) lost — …" with the rows that did land), the closing log line, and the
exit code (anything lost → 1, session gone → 3). See [errorhandling.md](errorhandling.md).

---

## 6. The one request path

Everything goes through `ZeptoClient.request()`. It recovers from exactly the three
recoverable failures, and nothing else:

```python
r = await send()        # every send waits out Zepto's own JSON 429: 5 s, 15 s, 30 s

if r.status_code in (202, 429) and not brand_analytics and not is_rate_limited(r):
    await self._remint()                      # browser proof gone
    r = await send()

if r.status_code == 401:                      # writes too: a 401 applied nothing
    if await self._reauth():                  # identity gone, bounded
        r = await send()
```

The counters `remint_count`, `reauth_count` and `ratelimit_count` show up on each scrape
section's closing line ("2 WAF renewal(s) · 1 rate-limit wait(s)").

**Recovery is per-call, not per-run.** That matters more than it sounds: on the shared
`varun@brikoven.com` account the session was evicted **three times in ten minutes** on
2026-09-01 and the run still completed. A per-run check would have died halfway.

`MAX_REAUTH_PER_RUN = 2` is a deliberate ceiling, not timidity — see
[errorhandling.md](errorhandling.md#the-bounded-reauth).

---

## 7. Three endpoint families, three header recipes

All on `https://fcc.zepto.co.in`. **Which family you are on decides the headers**, and
getting it wrong produces errors that look like something else entirely.

| Family | Used by | Needs | Gets wrong → |
|---|---|---|---|
| `/brand-analytics-web/*` | sales | `x-proxy-target: brand-analytics` | bare `text/plain` **404** that reads like a bad URL |
| `/ads-bff/*` | ads, catalogue, campaign manager | `x-aws-waf-token` **AND** `waf-enabled: false` | **429** — reads exactly like rate limiting |
| `/api/v1/*`, `/vendor/*` | PO, ASN, GRN, id discovery | neither | — |

In code this is the single `brand_analytics=` flag on `client.request()`:

- `brand_analytics=True` → sends `x-proxy-target`, **no** WAF token. Used by sales, PO
  and id discovery. These paths were **measured** returning 200 without a token.
- `brand_analytics=False` (the default) → sends the WAF pair. Used by every `ads-bff`
  call: the campaign list (`ADS_CAMPAIGNS_API`), the analytics tables
  (`ADS_TABULAR_API`), per-campaign keyword detail (`ADS_CAMPAIGN_TABULAR_API`), and the
  catalogue reads (campaign detail, `keyword/config`, targeting options).

And one rule that spans all three: **`authorization` carries the raw JWT with no
`Bearer ` prefix**, despite the login response advertising `tokenType: "Bearer"`.
Prefixing it returns a base64 decode error.

---

## 8. What each section produces

| Section | Window (default) | Endpoints | Tables written |
|---|---|---|---|
| `--sales` | 8 days to yesterday | `sales-overview`, `product-performance` (per day; per city for the split) | `zepto_seller_sales_summary`, `zepto_seller_sales`, `zepto_seller_product_city_daily`, `zepto_soh` |
| `--po` | 30 days back, through today | `po/filter`, `grn/filter`, `asn/filter`, `po/{id}/items` | `zepto_po`, `zepto_grn`, `zepto_asn`, `zepto_po_items` |
| `--ads` | 3 days to yesterday | `/ads-bff/campaigns`, `/metrics/tabular` × 6 views per category, campaign `metrics/tabular` (keyword detail), catalogue reads | `zepto_ad_campaign_daily`, `zepto_ad_keyword_daily`, `zepto_ad_product_daily`, `zepto_ad_breakdown_daily`, `zepto_ad_campaign_detail`, `zepto_ad_campaigns`, `zepto_ad_campaign_keywords` |

Windows are re-scraped every run on purpose: a failed or interrupted run heals on the
next one, and Zepto revises late figures (seen: a day's ad revenue ₹360 → ₹540 one day
later). See [cli.md](cli.md) for `--from` / `--to`.

### The scorecard is not a scraper

`app/services/zepto_scorecard.py` has no table, no migration and no endpoint. It
derives Blinkit's scorecard shape in SQL from `zepto_grn`, `zepto_po_items` and
`zepto_asn` — fill rate, potential loss at cost, ship/accept split, category fill.
Zepto publishes no scorecard page, so `grn_qty / po_qty` is the only route to one.

`manufacturer_rank` is **deliberately absent** rather than null — Zepto exposes
nothing equivalent, and a null column invites someone to try to fill it.

---

## 9. Grain: why there are fifteen tables and not three

Zepto returns the same rupees at several different resolutions, and each resolution
is a genuinely different grain. Merging them would need nullable-everything and make
`sum(gmv)` silently wrong.

```
sales      summary (brand × day)  →  sales (SKU × day)  →  city daily (SKU × city × day)
           soh (SKU × scrape day)  — readings of the moment, not of a sales day
ads        campaign × day  ·  campaign × keyword × day  ·  keyword × day (brand)  ·
           product × day  ·  breakdown × day
catalogue  campaign (current)  ·  campaign × keyword (current)
supply     PO (header)  →  ASN (shipped)  →  GRN (received)  ·  PO items (per SKU)
```

Traps that follow directly, all documented in [database.md](database.md):

- **`zepto_ad_breakdown_daily` stacks three dimensions** (category, city, page) in one
  table. `sum(spend)` over it returns **~3× the real spend**. Always filter `dimension`.
- **Never sum `zepto_seller_sales` together with `zepto_seller_product_city_daily`.**
  Same money, two resolutions.
- **Stock and growth describe the moment of the call**, not the sales day — hence
  `zepto_soh`.

---

## 10. Deliberate non-goals

- **No hardcoded ids.** `discover_ids()` re-fetches brand, city and category ids every
  run. Multi-brand accounts are parked (clients are single-brand) — it takes the first
  brand.
- **No `sku_map` bridge.** Zepto's `pvId` is the same id in `zepto_seller_sales`,
  `zepto_soh` and `zepto_po_items`, so they join to the Products page directly.
- **No writes to Zepto.** The scrape is read-only (the analytics POSTs are queries). The
  write path (budgets, bids, status) is the Campaign Manager — a separate system that
  shares the client and the four campaign reads.
- **`http2` is off deliberately.** The VM's venv has no `h2`, so `http2=True` would
  work locally and raise in production. Zepto does not require it.
- **No spinners, no printed tables.** One INFO line per step; per-request detail at
  DEBUG (`LOG_LEVEL=DEBUG`).
