# Zepto Seller Auth — handover

> **Not** app-user auth. This is Foresight logging into Zepto's Vendor Portal.
> Companion docs: [platform-auth.md](platform-auth.md) (the Blinkit HTTP flows),
> [zepto.md](zepto.md) (public-scrape build plan), [vm.md](vm.md) (the scraper box).

**Status (19-Aug-2026):** login, session health, data fetch and DB storage all
work, verified end to end on **foresight-vm**. Branch
`feature/zepto-public-scrape`. Not yet scheduled; frontend reads the data via
the existing Analytics endpoints.

---

## TL;DR

1. **Zepto's login rejects headless browsers.** Proven across Chromium, Firefox
   and WebKit — all three get `401` on the sign-in call, before the OTP screen
   ever renders. This is why Zepto is not in `platform_auth/`.
2. **The fix is Xvfb, not a workaround.** A virtual display lets a *genuinely
   normal* (non-headless) Chromium run on a box with no monitor. Nothing is
   spoofed or disguised.
3. **Only the login needs a browser.** Health check, ID discovery and every data
   call are plain `httpx` — no Chromium at all, which is lighter than Blinkit's
   seller scrape (that one still opens a headless browser per run to harvest
   headers).
4. **A human still types the OTP.** Xvfb solved "no screen", not "no human".

---

## Why Zepto sits outside `platform_auth/`

`platform_auth/` models logins as HTTP flows, which is correct for both Blinkit
dashboards — they're ordinary REST calls (see
[platform-auth.md](platform-auth.md)). Zepto's is not: its sign-in is a browser
flow that a plain HTTP client cannot complete.

The registry lists Zepto as `wired=False` deliberately, so selecting it fails
loudly rather than silently doing the wrong thing.

**Consequence:** Zepto does not get the registry's auto-OTP-from-inbox or
token-refresh behaviour. It has its own small equivalents instead — see
[Session health](#session-health).

If Zepto's login is ever reimplemented over HTTP, porting it into
`platform_auth/` and flipping `wired=True` is the right move.

---

## The headless finding

The evidence, since this is the decision everything else hangs off:

| Browser | Self-identifies as headless? | Sign-in result |
|---|---|---|
| Chromium headless | yes — `sec-ch-ua: "HeadlessChrome"` | **401** |
| Firefox headless | no such header exists | **401** |
| WebKit headless | no such header exists | **401** |
| Chromium headful (laptop) | n/a | **200** |
| Chromium headful under Xvfb | n/a | **200** |

Two engines that never send the `HeadlessChrome` marker still fail, so this is
**not** a single-header check — Zepto is detecting headless mode structurally,
most likely via the AWS WAF challenge script (`awswaf.com/challenge.js`,
`mp_verify`) that runs on the login page.

Also ruled out: **timing**. Waiting for network idle plus a 5s settle before
submitting made no difference — same 401.

**Not attempted, on purpose:** overriding `sec-ch-ua` or otherwise disguising the
browser. That is deliberate detection evasion, and it is not a route this
codebase should take. Xvfb needs no such trick because the browser genuinely
isn't headless.

### Failure signatures, so the two get told apart

```
# headless block — fails BEFORE the OTP screen
Credentials submitted, awaiting OTP screen
ERROR  Stuck waiting for OTP screen
ERROR  waiting for locator("input#otp")

# a stale/expired OTP — fails AFTER the OTP screen
OTP screen visible
OTP submitted
ERROR  Stuck on: https://brands.zepto.co.in/login
ERROR  waiting for navigation to "**/vendor/dashboard/**"
```

Both write a screenshot (`zepto_login_stuck_pre_otp.png` / `zepto_login_stuck.png`)
next to the working directory. Read it before theorising.

---

## Running the login on a display-less box (Xvfb)

Xvfb is a virtual framebuffer: an in-memory screen. Chromium starts in its
ordinary headful mode and draws to it. Standard tooling, used widely in CI.

One-time setup on the VM:

```bash
sudo apt update && sudo apt install -y xvfb
playwright install chromium            # NOT with sudo — see vm.md
sudo playwright install-deps chromium  # WITH sudo
```

Sanity check before spending an OTP — look for `Chromium` with **no**
`HeadlessChrome`:

```bash
xvfb-run -a python -c "
import asyncio
from playwright.async_api import async_playwright
async def m():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await (await b.new_context()).new_page()
        await pg.goto('https://example.com')
        print(await pg.evaluate('JSON.stringify(navigator.userAgentData.brands)'))
        await b.close()
asyncio.run(m())
"
```

Then the real login (the OTP prompt appears in the terminal, so SSH is fine):

```bash
xvfb-run -a python -m cli auth zepto-seller --tenant <tenant-id>
```

**Login does not have to happen on the VM.** Sessions live encrypted in
`platform_sessions`, so logging in from a laptop and letting the VM read the
session works too — that is the fallback if Xvfb ever misbehaves.

---

## The login flow

`scraper/platforms/zepto/dashboard_data/seller/auth.py`

1. Open `https://brands.zepto.co.in/login` (headful, always).
2. Fill `input#email`, fill `input#password`, click `button:has-text("Log In")`.
3. Wait for `input#otp` — **one** 4-digit field, unlike Blinkit's six per-digit boxes.
4. Prompt the operator at the terminal, fill it, click `button:has-text("Confirm")`.
5. Optional account-selection screen (untested — Brik Oven skips it; the selector
   is copied from Blinkit's Ant Design markup and is very likely wrong for Zepto's MUI).
6. Wait for `**/vendor/dashboard/**`, then capture cookies + localStorage.

Selectors live in `selectors.py`, all verified against the live page.

**Credentials are never stored.** Email and password are terminal prompts, used
once to fill the form, then discarded. Only the resulting session is persisted
(encrypted, via `platform_auth.store`).

### The session

A plain cookie holding a JWT — **much simpler than Blinkit's Firebase/IndexedDB
setup**, so no special extraction is needed. Two cookies matter:

| Cookie | Used as header |
|---|---|
| `<uuid>_AUTH_TOKEN` | `authorization` |
| `aws-waf-token` | `x-aws-waf-token` |

The header values are the cookie values **verbatim** — confirmed by comparing a
live request against the stored cookies. That is the whole reason the data layer
needs no browser: there is nothing to harvest that isn't already saved.

### Session lifetime — shorter than the JWT suggests

The JWT's own `exp` is ~9-10 hours, but **observed lifetime is often far
shorter**, and the failure reads `"Invalid Token"` rather than
`"Token expired"` — i.e. active invalidation, not the clock running out.

Observed 19-Aug-2026:

| Login | Dead by | Lifetime |
|---|---|---|
| 17:27 | 20:21 | ~3 h |
| 20:24 | 21:12 | ~48 min |

Both windows coincided with a human using the Zepto dashboard in a browser on
the same account. The likely explanation is **one active session per account**:
a browser login displaces the scraper's.

Two consequences:

* When a scrape session matters, keep the Zepto dashboard closed.
* This weakens the case for scheduling as things stand — an unattended job can
  be killed simply by someone opening the portal, not just by expiry. Treat
  ~9-10 hours as a ceiling, not an expectation.

---

## Session health

Zepto can't use `auth probe` (not in the registry), so it has a small equivalent:

* `scraper/platforms/zepto/dashboard_data/seller/scraper.py::validate` — one
  cheap authenticated GET, no browser.
* `.../session_health.py::ensure_healthy_session` — pre-flight used by the
  scrape command. Raises `SessionUnhealthy` rather than returning `None`, so a
  dead session stops the run immediately with "re-login required" instead of
  failing somewhere deeper.

Storage and health bookkeeping are **not** reimplemented — it calls
`platform_auth.store.mark_validated` / `mark_failed`, which own
`platform_sessions`.

> ⚠️ `mark_failed` is called with `login_attempt=False`. A probe finding an
> expired session is normal, not a broken login; counting it would make the
> circuit breaker measure session lifetime instead. See `store.mark_failed`.

```bash
python -m cli auth validate --tenant <id> --platform zepto_seller
python -m cli auth status   --tenant <id>     # generic, shows every platform
```

---

## Data fetch — no browser

`scraper/platforms/zepto/dashboard_data/seller/scraper.py`, all plain `httpx`:

| Purpose | Endpoint (host `fcc.zepto.co.in`) |
|---|---|
| Health probe | `/brand-analytics-web/api/v1/access-management/user` |
| Cities | `/api/v1/filter/city-list` |
| Brand + subcategories | `/api/v1/commons/brand-category-mapping` |
| Daily GMV / units | `/brand-analytics-web/api/v1/sales-analytics/sales-overview` |
| Per-SKU breakdown | `/brand-analytics-web/api/v1/sales-analytics/product-performance` |

**IDs are discovered every run, never cached.** Zepto's sales API rejects calls
without `cityIds` ("At least one City id is required") and needs brand +
subcategory ids/names too. A cached mapping was considered and rejected: the API
returns a clean `200` for a partial filter set, so a stale mapping would
silently under-report when a tenant gains a city or category. Same no-cache
choice Blinkit's scorecard scraper makes for `manufacturer_id`.

**Error routing.** Only `401/403` triggers the one-shot browser header
re-capture; `400`/`429`/`5xx`/timeouts surface as-is, because a browser can't fix
a bad parameter, a rate limit or a server error. *(The fallback path is written
but has never been exercised by a real failure.)*

---

## Storage

Separate tables — **nothing is written into any `blinkit_*` table**. Migration
`960b16030b12`.

| Table | Grain |
|---|---|
| `zepto_seller_sales_daily` | one row per tenant per **day** — authoritative GMV/units |
| `zepto_seller_product_perf` | one row per **SKU per day** |

Product rows are fetched one day at a time (like Blinkit's `_date_range` loop),
which is what makes a per-day SKU/category trend possible. A daily production
run is a single call; only backfills loop, paced by `_ZEPTO_DAY_GAP_S`.

**The two tables reconcile exactly** — verified 19-Aug-2026 for 17 Jul–16 Aug:
summing the SKU rows gives ₹18,31,040 / 16,882 units, identical to the daily
totals. If they ever diverge, something is truncating the product response
(see the `viewType` note below).

`sales_agg` still reads revenue/units from the **daily** table rather than
summing SKUs: the daily figures are Zepto's own authoritative totals, so they
are the right source even though both now agree.

### ⚠️ `viewType` — the trap

Zepto's Product Performance card has four tabs — Top Selling / Bottom Selling /
New Products / **All Products** — and the browser sends the active one as
`viewType`. Copying the captured request verbatim meant sending
`viewType=top_selling`, which the API **caps at 5 products**, silently
undercounting every SKU-level figure by ~3%.

| `viewType` | Result |
|---|---|
| `top_selling` | 5 rows (the trap) |
| `bottom_selling` | 5 rows |
| `all_products`, `new_products` | HTTP 400 — not the real param names |
| **omitted** | **full catalog** — what "All Products" sends |

**Omit the parameter.** `fetch_product_performance` does, and drops rows whose
`gmv` is null (catalog products with no sales in the window) so they don't
inflate the Active SKUs count.

**No city dimension anywhere.** Zepto's API exposes none at this grain. Per-city
filtering *is* accepted (`cityIds` with one id returns 200), but that would be
138 calls per day — rejected on WAF-exposure grounds. Sales-by-City and the
city/category heatmap stay Blinkit-only.

---

## Frontend

No new endpoints. `app/services/zepto_analytics.py` returns the same dict shapes
as `analytics_service.py`, which merges both marketplaces so the existing
`marketplaces=` filter just works.

Zepto shows as `connected=true, data_scope=full` automatically — that flag is
derived from real `scrape_jobs` rows, not a hardcoded list, so a successful
`zepto_seller_sales` job is what promotes it.

Categories group by **subcategory**, not category: Zepto's `categoryName` is one
broad bucket ("Dairy, Bread & Eggs") covering every SKU for this account.

---

## Commands

```bash
# login (add xvfb-run on a display-less box)
python -m cli auth zepto-seller --tenant <id>

# is the session still good?
python -m cli auth validate --tenant <id> --platform zepto_seller

# fetch + store (default window: last 7 days to yesterday)
python -m cli scrape zepto-sales --tenant <id> --from 2026-08-10 --to 2026-08-16
python -m cli scrape zepto-sales --tenant <id> --no-save          # dry run
python -m cli scrape zepto-sales --tenant <id> --save-xlsx out.xlsx
```

Job type `scrape.zepto_seller_sales` is registered in `jobs/types.py` and can be
scheduled like the Blinkit scrapes — **no schedule exists yet**.

---

## Open / next

* **No schedule registered.** The job type exists; nothing fires it.
* **OTP still needs a human**, roughly daily. Automating it means an inbox
  reader — `platform_auth` already has one for Blinkit; wiring Zepto in would
  require porting its login to that framework.
* **Multi-brand untested.** `discover_ids` takes `brandCategoryList[0]`. Fine for
  Brik Oven (one brand); an account with several would silently use only the first.
* **Account-selection screen untested** — selector is a Blinkit copy, likely wrong.
* **Browser fallback untested** — never triggered by a real 401.
* **Stock View is paywalled** ("Zepto Atom"). `stockOnHand` comes back null on
  every row. Not fixable in code.
* **Unexplored portal sections:** Fulfilment, Market Share — possible PO /
  scorecard equivalents, never investigated.
* **No automated tests.** Everything so far is manual, live verification.
