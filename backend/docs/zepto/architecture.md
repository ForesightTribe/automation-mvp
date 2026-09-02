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
> [prompts.md](prompts.md)

---

## 1. The one-paragraph version

Three CLI commands (`zepto-sales`, `zepto-ads`, `zepto-po`) each build **one shared
authenticated client**, make plain `httpx` calls against `fcc.zepto.co.in`, parse the
JSON into row dicts, and upsert them into eleven `zepto_*` tables. A fourth surface,
the **scorecard**, scrapes nothing at all — it is derived in SQL from the PO tables.
Authentication is handled by the shared `platform_auth` package (email + password →
emailed OTP → JWT), and a **headless Chromium is launched once per run purely to mint
an AWS WAF token**.

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
| **Failure signal** | `401` | `202` (challenge) or `429` |
| **Recovery** | re-login, bounded | re-mint, unbounded |

> Burning an OTP on a problem a missing header would have fixed is the concrete cost
> of mixing these up. `401` and `429` are **not** the same class of failure here.

---

## 3. Where the browser actually is

`campaign_manager/marketplaces/zepto/transport.py::mint_waf_token`

```
headless Chromium loads brands.zepto.co.in  →  aws-waf-token cookie  →  browser closed
every real API call then runs over plain httpx, carrying that token
```

The browser is a **token faucet, not the transport.** That is the important difference
from Blinkit, where Cloudflare rejects `httpx` outright and every fetch must happen
inside a live page.

Two consequences worth internalising:

- **Every Zepto private run launches Chromium once**, including `zepto-sales` and
  `zepto-po`, which do not otherwise need a WAF token. `setup()` mints
  unconditionally. Budget ~1 GB resident for ~10 seconds, not for the run.
- Re-minting **relaunches**; it never holds a browser open. Holding Chromium for a
  whole run costs ~1 GB for the run instead of ~1 GB for ten seconds.

Nothing under `scraper/platforms/zepto/dashboard_data/` imports Playwright. The browser
is entirely inside the transport layer.

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
├── campaign_manager/marketplaces/zepto/
│   ├── transport.py                        ★ ZeptoClient, mint_waf_token, setup()
│   └── endpoints.py                        API host, ads paths, WAF header constants
│
├── scraper/platforms/zepto/dashboard_data/seller/
│   ├── endpoints.py                        every data URL + page sizes + view names
│   ├── scraper.py                          fetch_* — raw JSON out, no parsing
│   ├── parser.py                           parse_* — raw JSON → row dicts + upsert_key
│   └── storage.py                          save_* — chunked ON CONFLICT upserts
│
├── app/models/zepto_seller.py              all 11 SQLModel tables
├── app/services/zepto_scorecard.py         derived scorecard — NO scraping
└── cli/commands/scrape.py                  zepto-sales · zepto-ads · zepto-po
```

`transport.py` living under `campaign_manager/` is a wart, not a design: the seller
scraper imports its client from the campaign-manager tree. It works, but it means the
scraper depends on a package it otherwise has nothing to do with. Worth a move if
anyone touches both.

---

## 5. The call chain

```
cli scrape zepto-sales -t <tenant>
│
├─ zepto_setup(tenant)                       transport.py::setup
│    ├─ auth_service.ensure(db, tenant, "zepto")
│    │    ├─ load encrypted session ────────────── platform_sessions
│    │    ├─ probe it (GET get-user-by-token)
│    │    ├─ refresh?  →  NO. Zepto has none
│    │    └─ dead? → login():
│    │         POST /api/v1/auth/sign-in {email, password}  → mfaId, OTP emailed
│    │         IMAP reads the 4-digit OTP from the shared inbox
│    │         POST /vendor/api/v1/auth/validate-mfa-otp/    → JWT + brandIds
│    └─ mint_waf_token()                     headless Chromium, ~10s
│
├─ discover_ids(client)                      city list + brand/category mapping
│    (fresh every run — no hardcoded ids anywhere)
│
├─ fetch_*(client, ...)                      scraper.py — raw JSON only
│    └─ client.request(...)                  per-call recovery, see §6
│
├─ parse_*(raw, tenant, job)                 parser.py — row dicts + upsert_key
│
└─ save_*(db, rows)                          storage.py — ON CONFLICT (upsert_key)
```

The `fetch → parse → save` split is the house rule from
[docs/code-standards.md](../../../docs/code-standards.md): **fetchers never parse and
parsers never do I/O.** It is what makes a scrape replayable from a captured payload.

---

## 6. The one request path

Everything goes through `ZeptoClient.request()`. It recovers from exactly the two
recoverable failures, and nothing else:

```python
r = await http.request(method, url, headers=self.headers(...))

if r.status_code in (202, 429) and not brand_analytics:
    await self._remint()                      # browser proof gone
    r = await http.request(...)

if r.status_code == 401 and (retry_writes or method == "GET"):
    if await self._reauth():                  # identity gone, bounded
        r = await http.request(...)
```

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
| `/ads-bff/*` | ads | `x-aws-waf-token` **AND** `waf-enabled: false` | **429** — reads exactly like rate limiting |
| `/api/v1/*`, `/vendor/*` | PO, ASN, GRN, id discovery | neither | — |

In code this is the single `brand_analytics=` flag on `client.request()`:

- `brand_analytics=True` → sends `x-proxy-target`, **no** WAF token. Used by sales, PO
  and id discovery. These paths were **measured** returning 200 without a token.
- `brand_analytics=False` (the default) → sends the WAF pair. Used by all three ads
  calls (`ADS_CAMPAIGNS_API`, `ADS_METRICS_API`, `ADS_TABULAR_API`).

And one rule that spans all three: **`authorization` carries the raw JWT with no
`Bearer ` prefix**, despite the login response advertising `tokenType: "Bearer"`.
Prefixing it returns a base64 decode error.

---

## 8. What each command produces

| Command | Endpoints | Tables written |
|---|---|---|
| `zepto-sales` | `sales-overview`, `product-performance` (± per city) | `zepto_seller_sales_summary`, `zepto_seller_sales`, `zepto_seller_product_city_daily` |
| `zepto-ads` | `/ads-bff/campaigns`, `/metrics`, `/metrics/tabular` × 6 views | `zepto_ad_campaign_daily`, `zepto_ad_keyword_daily`, `zepto_ad_product_daily`, `zepto_ad_breakdown_daily` |
| `zepto-po` | `po/filter`, `grn/filter`, `asn/filter`, `po/{id}/items` | `zepto_po`, `zepto_grn`, `zepto_asn`, `zepto_po_items` |

### The scorecard is not a scraper

`app/services/zepto_scorecard.py` has no table, no migration and no endpoint. It
derives Blinkit's scorecard shape in SQL from `zepto_grn`, `zepto_po_items` and
`zepto_asn` — fill rate, potential loss at cost, ship/accept split, category fill.
Zepto publishes no scorecard page, so `grn_qty / po_qty` is the only route to one.

`manufacturer_rank` is **deliberately absent** rather than null — Zepto exposes
nothing equivalent, and a null column invites someone to try to fill it.

---

## 9. Grain: why there are eleven tables and not three

Zepto returns the same rupees at several different resolutions, and each resolution
is a genuinely different grain. Merging them would need nullable-everything and make
`sum(gmv)` silently wrong.

```
sales      summary (brand × day)  →  sales (SKU × window)  →  city daily (SKU × city × day)
ads        campaign × day  ·  keyword × day  ·  product × day  ·  breakdown × day
supply     PO (header)  →  ASN (shipped)  →  GRN (received)  ·  PO items (per SKU)
```

Two traps that follow directly, both documented in [database.md](database.md):

- **`zepto_ad_breakdown_daily` stacks three dimensions** (category, city, page) in one
  table. `sum(spend)` over it returns **~3× the real spend**. Always filter `dimension`.
- **Never sum `zepto_seller_sales` together with `zepto_seller_product_city_daily`.**
  Same money, two resolutions.

---

## 10. Deliberate non-goals

- **No hardcoded ids.** `discover_ids()` re-fetches brand, city and category ids every
  run. Multi-brand is untested — it takes `brandCategoryList[0]`.
- **No `sku_map` bridge.** Zepto's `pvId` is the same id in `zepto_seller_sales` and
  `zepto_po_items`, so PO lines join to the Products page directly.
- **No writes.** These three commands are read-only. The write path (budgets, bids)
  is the Campaign Manager and is a separate system.
- **`http2` is off deliberately.** The VM's venv has no `h2`, so `http2=True` would
  work locally and raise in production. Zepto does not require it.

---

## 11. Known-stale comments in the code

Flagged rather than fixed, because changing them is not this document's job:

| Location | Says | Reality |
|---|---|---|
| `cli/commands/scrape.py` `zepto-sales` docstring | "Requires a session saved by `cli auth zepto-seller`" | that command was deleted; it is `cli auth login zepto` |
| `cli/commands/scrape.py` `zepto-ads` docstring | "this needs a browser … headers are harvested from one short page load" | the browser is now only the WAF faucet in `transport.py` |
| `jobs/types.py` `scrape.zepto_seller_sales` | "run separately, wherever there's a real display" | no display is needed anywhere |
| `app/models/zepto_seller.py` `ZeptoPO` | "per-PO detail call that has not been captured" | it was captured; `zepto_po_items` exists |
| `docs/zepto-auth.md` (repo root docs) | Xvfb, `selectors.py`, `auth.py`, Zepto outside `platform_auth` | all deleted / now false |
