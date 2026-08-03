# Zepto — Platform Build Plan (Public Data first)

Zepto is the **second marketplace**. Blinkit took ~2 months of discovery to reach
its current shape; Zepto should take a fraction of that, because the expensive
parts — the worker pool, staging, the loader, resume, the config workbook, the job
queue, the read services — are already built and are **not Blinkit-specific**.

> **Status: Phase 1 SHIPPED (2026-08-03) — the public path is de-hardcoded and
> marketplace-parameterised, with Blinkit verified unchanged. Phases 0 and 2–6 are
> planned.** A Zepto build now starts at Phase 0 (recon) and only ever adds files
> under `scraper/platforms/zepto/public_data/` plus one registry entry.
>
> Everything under
> `scraper/platforms/zepto/` today is dead 2026-06 stub code (one-shot `httpx` +
> DOM-scrape guesswork against the retired `zepto.now` domain). **Phase 2 deletes
> it wholesale.** Treat that directory as empty.

**Scope of this doc:** Public Data, specified to build level. The rest of the Zepto
surface (auth, the private dashboard, campaign automations) is mapped in
[After Public](#after-public--the-rest-of-the-zepto-surface) so the public work
doesn't paint it into a corner, but is deliberately not designed here.

**Read first:** [ARCHITECTURE.md](ARCHITECTURE.md) ·
[code-standards.md](code-standards.md) ·
[public-glossary.md](public-glossary.md) ·
[darkstores.md](darkstores.md) · [staging.md](staging.md) ·
[jobs.md](jobs.md) · [vm.md](vm.md)

---

## TL;DR

The public scrape is already ~85% marketplace-agnostic. The real work is:

1. **A pure refactor of the Blinkit path** to run on a provider abstraction that
   *already exists and works* (`scraper/public/explorer/providers.py`, shipped and
   proven by the Explorer). Blinkit is the regression oracle: byte-identical output
   before and after.
2. **One new engine** — `scraper/platforms/zepto/public_data/` — implementing three
   functions: `open_context_session` / `search` / `close_session`.
3. **Zepto's own store catalog.** Blinkit's 2059 express stores came from an
   external darkstore export; Zepto gets the **equivalent for Zepto** — its own
   stores, its own coordinates, sourced independently. Blinkit's coordinates are
   **not** reused. Sourcing that catalog is a real, non-code dependency and is the
   long pole of Phase 3.

Everything else (orchestrators, staging, loader, CLI, jobs, schedules, VM,
read services) is parameterisation, not new code.

**The one thing that can invalidate this plan** is how Zepto binds a request to a
store. Blinkit's whole cost model rests on *one* browser session serving all 2059
stores by swapping two headers. If Zepto requires a per-store session, or a
location-set round trip per store, runtime goes from ~1.5 h to a number that may
not fit the box. **Phase 0 answers this before any code is written.**

---

## Locked decisions

| # | Fork | Decision | Why |
|---|---|---|---|
| **D1** | Code reuse | **Parameterise the existing public path on `mp_slug`** — do NOT fork `orchestrator.py`/`targeted.py` per platform | The worker pool, queue, resume, staging, stats and logging are already platform-neutral; only three imports and the literal `"blinkit"` are not. Forking doubles ~600 lines of the most-debugged code we own |
| **D2** | Abstraction | **Graduate `explorer/providers.py` → `scraper/public/providers.py`** and adopt it in `orchestrator.py` + `targeted.py` | The abstraction is already designed, shipped, and its own docstring says it should graduate if the per-tenant orchestrators adopt it. No new concept invented |
| **D3** | Schema | **Reuse `search_snapshots` / `search_listings` / `sku_snapshots` with `mp_slug='zepto'`.** No `zepto_*` public tables | All three are already marketplace-keyed with an FK to `marketplaces`, and every read service already accepts a `marketplace` filter. New tables would fork `competition_service`, `inventory_service`, `product_service`, `reports_service` and `analytics_service` |
| **D4** | Store catalog | **Zepto gets its OWN catalog. Blinkit's locations are never reused as Zepto probe points** — source a Zepto store list the same way Blinkit's was, and sync it as `marketplace_locations` rows with `mp_slug='zepto'` | Blinkit's coordinates are *Blinkit's* catchments, not Zepto's. Probing Zepto at them would (a) mis-state coverage — the footprints differ, so we'd measure Zepto only where Blinkit happens to be, and (b) make `merchant_id` a Blinkit-derived accident rather than a Zepto fact. The two catalogs are independent datasets that happen to share a schema |
| **D5** | CLI shape | **A `--marketplace/-m` flag on the existing `public-run` / `public-skus`**, default `blinkit` | Matches the "views, not platforms" rule the dashboard already follows. Zero new command surface, zero new docs to keep in sync |
| **D6** | Jobs | **One `marketplace` param on the existing job types**, not new job types | Lane and timeout are identical (`batch`, 12 h). Both marketplaces sharing the `batch` lane is *correct*: two concurrent Chromium scrapes would thrash a 2-vCPU box. Schedules are DB rows, so per-marketplace cadence is still fully independent |
| **D7** | Pack parsing | **Extend `scraper/utils/pack.py`, never fork it** | The UOM table and grammar are already generic. If Zepto writes units differently, that is new tokens in `_UOM`, not a second parser. Any change must be re-validated against the Blinkit corpus too |
| **D8** | Store grain | **`merchant_id`/`merchant_type` semantics are per-platform and must be re-derived, not assumed** | Blinkit stamps every product with its fulfilling store and tier. Whether Zepto does is unknown (Phase 0 Q4). If it doesn't, `merchant_id` comes from the *request* context and Zepto data is location-grain, not store-grain — a real semantic difference to record, not paper over |
| **D9** | Rollout | **Blinkit-unchanged refactor ships and is verified BEFORE any Zepto code merges** | Blinkit is live, scheduled, and feeding a client dashboard. It is also the only regression oracle we have for the refactor. Mixing the two changes makes a break unattributable |
| **D10** | Volume | **A disk sizing gate blocks all-India Zepto** — one city first, measure, then decide | Supabase free tier is a **500 MB hard quota**; one day of Blinkit public scrape is ~92 MB. A second marketplace at full scale is not obviously affordable. See [Capacity gate](#capacity--the-disk-gate) |
| **D11** | Auth | **Public Zepto needs no login** | Public search is unauthenticated on both platforms. `platform_sessions`, Fernet and the headless-re-auth machinery are irrelevant to this phase — they arrive with the private dashboard |

---

## What we don't know yet — Phase 0 recon

Everything below is an **open question, not a fact**. The Blinkit answer is given as
the contrast, because the *shape* of the difference is what drives the design. Do
not write engine code until this table is filled in.

| # | Question | Blinkit's answer | Why it matters |
|---|---|---|---|
| **Q1** | What is the search endpoint, method, and body? | `POST blinkit.com/v1/layout/search`, body `{applied_filters, sort}` | Determines `endpoints.py` in full |
| **Q2** | **How is a request bound to a store?** Headers? A location-set call? A store id in the path? | Two headers, `lat` + `lon`, swappable per request on a shared session | **The cost model.** Header swap = ~0.4 s/store. A per-store session or a location-set round trip could be 10–50× that |
| **Q3** | Does direct `httpx` work, or is there a Cloudflare-class TLS/fingerprint block? | Blocked (403 on http/1.1 **and** h2, even with valid cookies) → in-page `page.evaluate(fetch(...))` | If httpx works, Zepto is dramatically cheaper (no browser) and the provider interface still fits — `open_session` just returns an httpx client instead of a Playwright context |
| **Q4** | Does each product carry the **fulfilling store id and tier**? | Yes — `cart_item.merchant_id` + `merchant_type` (`express`/`longtail`/`super_longtail`/`dummy`), per product | Decides whether Zepto data is store-grain (like Blinkit) or only location-grain. Drives D8 and every Reach/Distribution denominator |
| **Q5** | Is there an explicit **brand** field per product? | Yes — `cart_item.brand`, so own-vs-competitor is exact, not name-guessed | Without it, `classify_products` falls back to name matching, which is materially worse and needs alias tuning per tenant |
| **Q6** | How does pagination work, and is there a `basic` → `similarity` relevance switch? | `pagination.next_url`, 12/page, `search_method` flips `basic`→`similarity` | Drives `search()`'s stop condition and whether the brand scrape needs a `follow_similarity` equivalent to recover the full catalog |
| **Q7** | What is the price/MRP/inventory/rating field set, and are the values typed or display strings? | Typed numerics on `cart_item`; rank/category on `tracking.common_attributes` | Decides how much `parser.py` has to do vs. how much is straight extraction |
| **Q8** | What does the `unit`/pack string look like? | `"225 ml"`, `"12 x 250 ml"`, `"225 ml + 225 ml + 225 ml"` — 100% parseable by `pack.py` | Per-unit price (₹/100 ml · 100 g · piece) is a shipped dashboard feature. If Zepto's format differs, `_UOM`/`_TERM` need extending (D7) |
| **Q9** | **Where does the Zepto store catalog come from?** A store-list / serviceability endpoint, a published dataset, or an export like Blinkit's? | An external darkstore export → 2059 express stores with precise coordinates. The in-app `?pincode=` lookup was too weak to build a catalog from | **Blocking for Phase 3 (D4).** No catalog, no scrape — there is nothing to probe. This is the one open question that may need a non-engineering answer |
| **Q10** | What are the rate limits / block thresholds at 5–6 concurrent workers? | 5–6 workers sustained, ~0.4 s/fetch, transient 403/429 self-resolve on backoff | Sets `--workers` default and the `_RETRY_DELAYS` / `_REFRESH_AFTER` tuning |
| **Q11** | How many Zepto stores are there, in how many cities? | 2059 express stores, 238 cities observed | Sets the scrape's runtime, the row volume, and therefore the D10 disk gate. Answered by Q9's catalog, not by probing |
| **Q12** | Does the response differ between a datacenter IP (the Mumbai VM) and a residential one? | No — validated 2026-07-13, headless + datacenter IP works | If Zepto is stricter, the whole VM hosting model needs revisiting for this platform |

### How to run Phase 0

A **throwaway** script, not merged code. Put it in the scratchpad or
`backend/scripts/` and delete it after:

1. Open a real (headed) browser to Zepto, set a location, run a search, and capture
   the network trace — request URL, method, headers, body, and one full response.
2. Save the response verbatim as `scraper/platforms/zepto/public_data/api.txt`.
   This mirrors Blinkit's `api.txt` (a 3.8 MB captured response), which is the
   single most useful artefact in that package — it is why field extraction was
   readable rather than guessed.
3. Replay the captured request from `httpx` (Q3) and from `page.evaluate(fetch)`.
4. Change only the store-binding input (Q2) and confirm the catalog actually
   changes — a request that *accepts* a coordinate but ignores it is the failure
   mode that silently produces 2059 copies of one store's data.
5. Probe a handful of **hand-picked Zepto-serviced coordinates** (pick them from the
   Zepto app in cities you know it operates in) and record whether the catalog
   actually differs between them (Q2) and whether store ids appear per product (Q4).
   These are throwaway probe points for protocol discovery — **not** the beginnings
   of a catalog, and **not** Blinkit's coordinates (D4).
6. Chase Q9 in parallel: it is the one question that may not have an engineering
   answer, and Phase 3 cannot start without it.

**Exit criterion:** the table above has no blank cells, and `api.txt` is committed.
Phase 0 output amends *this document* — the answers become the "Zepto API facts"
section that replaces this one.

---

## How Zepto fits the existing architecture

Nothing about the flow changes. The marketplace becomes a parameter of it:

```
[CLI  |  jobs/ runner → subprocess]        python -m cli scrape public-run -m zepto -t <uuid>
     │
     ├── keyword scrape ──► scraper/public/orchestrator.py        (mp_slug-parameterised)
     │                        │  provider = get_provider("zepto")
     │                        │  locations = marketplace_locations WHERE mp_slug='zepto'
     │                        │  zepto/public_data: scraper.py → parser.py (classify own+competitors)
     │                   staging.py ──► staging/public_search_zepto_<tenant8>_<ts>.sqlite3
     │
     ├── own-SKU scrape ──► scraper/public/targeted.py            (same, brand query)
     │                   staging.py ──► staging/public_skus_zepto_<tenant8>_<ts>.sqlite3
     │
     └── explorer ──► scraper/public/explorer/  (already marketplace-abstracted; -m zepto
                        starts working the moment the provider is registered as wired)
                                │
                        cli scrape load  ──► ONE transaction ──► [PostgreSQL]
                                │            ensure_refs(slug, 'zepto')
                                │            search_snapshots / search_listings / sku_snapshots
                                ▼                              (mp_slug='zepto')
                        FastAPI  ?marketplace=zepto  ──►  React dashboard
```

### Where the VM comes in

Unchanged, and it matters for the same reason: **Zepto is India-geo**, so it runs
from the GCP Mumbai box, not Render and not a laptop. See [vm.md](vm.md).

- **The VM runs `main`.** Nothing on a feature branch exists on the box. The Zepto
  work merges to `main` before it can be scheduled.
- **No session transfer needed** — public Zepto is unauthenticated (D11). No
  `ENCRYPTION_KEY` failure mode here.
- **Shared `batch` lane** (D6): Zepto queues *behind* Blinkit rather than beside it.
  Sequential is deliberate — a 2-vCPU box running two headless Chromium worker pools
  would slow both and raise the block risk on both.
- **⚠️ Never run a runner locally.** Laptop and VM share one database; a local
  runner will claim the VM's Zepto job and scrape from a home IP.
- **`playwright install chromium` must NOT be run as root** (it lands in root's
  cache); `playwright install-deps` must be. Already provisioned on the box — Zepto
  adds no new browser dependency.

### What is already marketplace-agnostic (touch nothing)

| Component | Evidence |
|---|---|
| `scraper/public/staging.py` | Schema mirrors the public tables field-for-field; only two INSERTs hardcode `"blinkit"` |
| `scraper/public/loader.py` | COPY-based, all-or-nothing; only `ensure_refs(..., "blinkit")` and `ScrapeJob(platform=...)` hardcode it |
| `scraper/utils/search_result.py` | `classify_products` already prefers an explicit `brand` field and falls back to name — no platform logic, and its own docstring forbids adding any |
| `scraper/utils/pack.py` | Generic UOM table + grammar (D7) |
| `app/models/search.py` | `MarketplaceLocation` is unique on **(mp_slug, merchant_id)**; `TenantLocation` carries `mp_slug`; all three fact tables FK to `marketplaces.slug` |
| `jobs/` (queue, runner, scheduler, monitor) | Dispatches `python -m cli …` as a subprocess — it does not know what a marketplace is |
| Read services | Already take a `marketplace` filter (`competition_service`, `inventory_service`, `analytics_service`, `reports_service`) |
| Explorer | Already provider-abstracted and `--marketplace`-driven end to end |

### What is Blinkit-hardcoded (the exhaustive list)

Grep target: `MP = "blinkit"` and the string literal `"blinkit"`.

| File | What | Phase 1 change |
|---|---|---|
| `scraper/public/orchestrator.py` | `MP = "blinkit"`; direct imports of `bl_scraper` / `bl_parser` / `ep` | `mp_slug` parameter; resolve via `get_provider(mp_slug)` |
| `scraper/public/targeted.py` | same | same |
| `scraper/public/staging.py` | `"blinkit"` literal in both INSERTs | `mp_slug` column on `run`, carried into rows |
| `scraper/public/loader.py` | `ensure_refs(db, slug, "blinkit")`, `ScrapeJob(platform="blinkit")` | read `mp_slug` from staging meta, default `"blinkit"` when absent |
| `cli/commands/sync.py` | `MP = "blinkit"` | `mp` column on the workbook sheets, default `blinkit` |
| `cli/commands/locations.py` | `MP = "blinkit"` | `--marketplace/-m` option, default `blinkit` |
| `cli/commands/scrape.py` | `public-run` / `public-skus` assume Blinkit | `--marketplace/-m` option, default `blinkit` |
| `jobs/types.py` | `_public_keyword` / `_public_skus` builders | add `marketplace` to `param_keys` + one `_opt` line each |
| `app/services/inventory_service.py:252`, `reference_service.py:62` | `MarketplaceLocation.mp_slug == "blinkit"` | take the caller's marketplace filter |
| `scraper/public/explorer/providers.py` | the registry itself | moves to `scraper/public/providers.py`; explorer re-exports for compatibility |

---

## File-by-file build spec

### New — `scraper/public/providers.py`

Moved from `scraper/public/explorer/providers.py` (unchanged content + the Zepto
entry flipped to `wired=True` in Phase 4). `explorer/providers.py` becomes a
two-line re-export so the Explorer's imports keep working.

```python
"""Marketplace provider registry for the public scrapes.

A provider wraps one marketplace's public-search engine behind a common interface
so orchestrator.py / targeted.py / explorer/ stay marketplace-agnostic:

    open_session(browser, lat, lon)                      -> session | None
    search(session, keyword, cap, *, lat, lon, follow_similarity)
                             -> {products, total_results, merchant_id, ok, error}
    close_session(session)                               -> None
"""
```

The `Provider` dataclass is a **pure data record** (frozen, callables only, no
behaviour) — that is why it does not violate functions-not-classes.

**Contract note for Zepto:** `search()` MUST return the Blinkit-shaped dict
`{products, total_results, merchant_id, ok, error}`, and each product MUST use the
Blinkit key names (`product_id`, `name`, `brand`, `price`, `mrp`, `unit`,
`inventory`, `in_stock`, `rating`, `position`, `merchant_id`, `merchant_type`).
The translation from Zepto's vocabulary happens **inside** the Zepto engine,
nowhere else. Anything Zepto-only rides in `extra`.

### New — `scraper/platforms/zepto/public_data/endpoints.py`

Every URL, header key, request body and tunable. **Nothing here may appear inline
in `scraper.py`** — the same house rule that `selectors.py` enforces for the DOM.

```python
BASE_URL         = ...
SEARCH_PATH      = ...
HOMEPAGE_URL     = ...          # establishes location context, if Zepto needs it
WARMUP_SEARCH_URL= ...          # makes the browser fire its own search so we can
                                # capture the session-bound headers
SEARCH_BODY      = {...}
SEARCH_HEADER_KEYS = (...)      # the session-bound headers to replay
BASIC_SEARCH_METHOD = ...       # only if Q6 says there is a relevance switch
RESULT_CAP       = 48           # floor only — tenant keyword_cap wins
BRAND_RESULT_CAP = 60

def first_search_url(keyword: str) -> str: ...
```

`RESULT_CAP` must stay **well above one page**. Blinkit learned this the hard way:
a cap of 12 made an unconfigured tenant structurally blind to every non-express
tier, because deeper tiers surface at rank 24–29. Set Zepto's floor from real
Phase 0 data, not by copying 48.

### New — `scraper/platforms/zepto/public_data/scraper.py`

The engine. Mirror Blinkit's section layout so the two read as siblings:

```
── Extraction ─────────  _extract_product(snippet) -> dict | None
                         _extract_products(body)   -> list[dict]
                         _pagination(body)         -> (next_url, method, count)
── Fetch ──────────────  _FETCH_JS, _RETRY_DELAYS, _FETCH_TIMEOUT_S
                         _in_page_fetch(page, url, headers, body)
── Session lifecycle ──  _make_session / open_session / open_context_session
                         close_session
── Search ─────────────  search(session, keyword, cap, *, lat, lon,
                                follow_similarity=False) -> dict
── Public entrypoint ──  scrape(keyword, brand_slug, ...) -> dict   (ad-hoc CLI)
```

Non-negotiables carried over from Blinkit, each earned by a real incident:

- **`open_context_session(browser, lat, lon)`** creates an isolated context on a
  *shared* browser and does **not** own it. `open_session(pw, …)` launches its own
  browser for ad-hoc single use. `close_session` closes the browser only if the
  session owns it. The worker pool depends on this distinction.
- **A hard per-attempt fetch timeout, enforced twice** — an `AbortController`
  in-browser plus an `asyncio.wait_for` around the `evaluate`. One guards a stalled
  connection, the other a wedged page process. A worker must always unblock.
- **A 200 with a non-JSON body is not a result.** It is almost always a bot
  challenge. Keep retrying; never accept it as an empty page.
- **Dedupe on `product_id`, keeping the FIRST sighting** — the first carries the
  true (best) rank. Blinkit's similarity tail re-lists `basic` items, and without
  this the brand scrape wrote 2–3 duplicate rows per store.
- **Fall back to running order** where the API gives no explicit position.
- **Raw in, parsed out** — `scraper.py` returns raw extracted fields; typing and
  classification happen in `parser.py`.

If Q3 says direct `httpx` works, `_in_page_fetch` becomes an httpx call and the
session dict holds a client instead of a page. **The provider interface does not
change** — that is the point of D2.

### New — `scraper/platforms/zepto/public_data/parser.py`

Thin, like Blinkit's (26 lines). Calls the shared `classify_products` and returns
the snapshot summary + `listings`. Set `"provider": "zepto"`.

**Do not add platform-specific logic to `classify_products`** — its docstring says
so, and it is shared by all three marketplaces. If Zepto needs different matching
(Q5 says no explicit brand field), handle it in `parser.py` by normalising the
product dict *before* the call.

### New — `scraper/platforms/zepto/public_data/api.txt`

The Phase 0 captured response, verbatim. Committed. This is documentation, not
code — it is how the next person understands the payload without re-capturing it.

### Deleted — the existing Zepto stubs

`scraper/platforms/zepto/public_data/{scraper,parser,storage,store_locator}.py` all
go. They target `zepto.now` (retired), use one-shot `httpx` with a `dig_list`
guess-the-key-name strategy, fall back to CSS class-name prefixes, and have no
session, no pagination, no store binding, and no caller. Keeping any of it as
"reference" is a trap: it encodes assumptions we are about to disprove.

The ad-hoc `cli scrape public --platform zepto` path imports those modules and must
be repointed at the new engine in the same commit.

**`storage.py` is not recreated.** The public path writes through
`scraper/public/staging.py`, not per-platform storage modules. (Blinkit's
`storage.py`/`sku_storage.py` survive only for the ad-hoc `--save` path.)

### Changed — `scraper/public/orchestrator.py` and `targeted.py`

The single largest edit, and it is mechanical:

```python
# before
from scraper.platforms.blinkit.public_data import scraper as bl_scraper
MP = "blinkit"
res = await bl_scraper.search(session, keyword, cap, lat=loc.lat, lon=loc.lon)

# after
from scraper.public.providers import get_provider
async def run_tenant(db, tenant_id, *, mp_slug: str = "blinkit", ...):
    provider = get_provider(mp_slug)
res = await provider.search(session, keyword, cap, lat=loc.lat, lon=loc.lon)
```

`mp_slug` threads through `run_tenant` → `_worker` → `staging.new_run` and into
`_locations()`'s `MarketplaceLocation.mp_slug ==` filter. The parser is resolved the
same way (add a `parse` callable to `Provider`, or dispatch on `provider.slug`).

**Preserve exactly, do not "improve" while refactoring:**

- `_STORE_SKIP_AFTER = 2`, `_REFRESH_AFTER = 8`, `_PACING = 0.05`
- the `await db.close()` before the scrape loop — held open across a ~1.5 h scrape
  the pooled connection goes idle, gets dropped by the pooler/NAT, and raises a
  spurious error at the end of an otherwise-clean run
- the catalog-vs-observed `merchant_id` mismatch warning — it is the *only* way we
  learn a store moved or closed
- `--resume` semantics: `(keyword, lat, lon)` pairs for the keyword scrape,
  `(lat, lon)` stores for the targeted scrape
- `on_tenant_done` auto-load: each tenant loads the moment its scrape ends, so
  tenant 7 failing cannot strand the six already scraped

These tunables are per-platform in principle. **Keep them shared until Zepto data
says otherwise** (Q10) — a second set of magic numbers with no evidence behind it is
worse than one shared set.

### Changed — `scraper/public/staging.py`

- `run` table gains `mp_slug TEXT`, added via the existing `_add_missing()`
  forward-compat top-up. Files staged before this change read back `NULL`.
- `new_run(tenant_id, kind, mp_slug=...)`; `save_search`/`save_skus` write
  `stg["mp_slug"]` instead of the `"blinkit"` literal.
- Filename becomes `{kind}_{mp}_{tenant8}_{timestamp}.sqlite3`. `ref()` splits on
  the **last** `-`, so the extra segment is safe — but add a test.
- `resumable(kind, tenant_id)` gains an `mp_slug` filter, or a Blinkit run becomes
  resumable as a Zepto one.

### Changed — `scraper/public/loader.py`

- `mp = m["mp_slug"] or "blinkit"` — the NULL default is what makes pre-existing
  staged files load correctly.
- `ensure_refs(db, slug, mp)` and `ScrapeJob(platform=mp)`.
- **Nothing else.** The COPY path, chunking, id pre-allocation, and the
  all-or-nothing transaction boundary are untouched. Public data is append-only with
  no unique constraint, so a partial load silently duplicates — atomicity is the
  entire retry-safety story. Do not "optimise" it.

### Changed — `cli/commands/sync.py` (the config workbook)

The workbook is the source of truth for the catalog, watchlists and coverage. It
needs a marketplace dimension:

| Sheet | Change | Back-compat |
|---|---|---|
| `locations` | new **`mp`** column | blank → `blinkit`. Existing 2059 rows unaffected |
| `coverage` | new **`mp`** column | blank → `blinkit` |
| `brands` | none — `keywords`/`aliases`/`keyword_cap`/`brand_cap` are per (tenant, brand) and shared across marketplaces | — |

`_sync_locations` / `_sync_coverage` key on `(mp, merchant_id)` and `(tenant, mp,
city)` respectively. `_sync_brands` sets `marketplaces=[…]` from the union of the
tenant's coverage rows instead of the hardcoded `[MP]`.

`--template` gains Zepto example rows. Update the docstring's sheet/column list.

> ⚠️ **`--prune` becomes dangerous during the transition.** A workbook where
> Zepto rows exist but the `mp` column hasn't been filled in will read every Zepto
> row as Blinkit and prune 2059 real stores. **Always `--dry-run` first**, and treat
> a non-zero `deleted` count on `locations` as a stop-and-check.

### Changed — `cli/commands/locations.py`

`--marketplace/-m` on `list` (default `blinkit`). Drop `MP = "blinkit"`; the panel
title names the marketplace. Editing is still `cli sync` only — this command stays
read-only.

### The Zepto store catalog (D4) — sourced, not derived

**No new code.** Blinkit's catalog arrived as a spreadsheet and went into the DB
through `cli sync`; Zepto's takes the identical path. The work here is *obtaining*
the data (Q9), not writing a program.

```
Zepto store list (Q9)  ──►  config.xlsx `locations` sheet, mp=zepto  ──►  cli sync
                             merchant_id, city, state, region, pincode,
                             lat, lon, active, location_name, address
```

Requirements the catalog must satisfy, all learned from Blinkit:

- **`merchant_id` is Zepto's own store id** — the row's natural key, the label
  source, and the validation assertion. A scrape returning a *different* store id
  for a coordinate is how we learn a store moved, closed, or opened. That signal
  only exists if the id is genuinely Zepto's.
- **`lat`/`lon` is the probe point** — the coordinate we knock at to reach that
  store. It must be a Zepto-serviced point, precise enough to resolve to the
  intended store.
- **One row per store**, not per coordinate. `marketplace_locations` is unique on
  `(mp_slug, merchant_id)`.
- `pincode`/`location_name`/`address` are metadata for the UI and reports; the
  scrape does not use them.

> **Do not reuse Blinkit's 2059 coordinates as Zepto probe points (D4).** It is the
> tempting shortcut — the rows are right there, already validated, and `mp_slug` is
> just a column. It produces a dataset that silently answers a different question:
> "how does the brand do on Zepto *in the places Blinkit operates*". Coverage,
> Reach and Distribution all inherit Blinkit's footprint as their denominator, and
> `merchant_id` becomes whichever Zepto store happened to answer a Blinkit
> catchment. Two platforms, two catalogs.

**If Q9 has no clean answer**, discovery-by-probing becomes the fallback rather than
the plan — but it needs its own Zepto-native coordinate source (a city grid, a
serviceability sweep), not Blinkit's rows. Design it then, with the evidence.

### Changed — `cli/commands/scrape.py`

```bash
python -m cli scrape public-run  -m zepto -t <uuid> [--city …] [--keyword …] [--cap N] [--workers N] [--resume] [--no-load]
python -m cli scrape public-skus -m zepto -t <uuid> [--city …] [--brand-cap N] [--workers N] [--resume] [--no-load]
python -m cli scrape staged                       # now shows an MP column
python -m cli scrape load [--all] [--file <ref>] [--dry-run]
python -m cli scrape discard --file <ref>
python -m cli scrape public --keyword "cola" --brand "dobra" --platform zepto [-t <uuid> --save]
```

`-m/--marketplace` defaults to `blinkit`, so **every existing command line and
every existing schedule keeps working verbatim.** Validate the value against
`providers.supported_marketplaces()` and fail fast with the list — a typo'd
marketplace must not silently scrape Blinkit.

Add a **Marketplace** column to `scrape staged`. With two platforms staging into
one directory, a `ref` timestamp alone stops being self-explanatory.

### Changed — `jobs/types.py` (D6)

Two `_opt` lines and two `param_keys` entries:

```python
def _public_keyword(tenant_id, p):
    a = ["scrape", "public-run", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace"))
    ...

"scrape.public_keyword": JobTypeSpec(
    Lane.batch, 12 * 60 * 60, _public_keyword,
    param_keys=("marketplace", "city", "keyword", "cap", "workers", "resume"),
),
```

Then a Zepto schedule is just another `job_schedules` row — no code, no restart:

```bash
python -m cli schedules add --type scrape.public_keyword --tenant <uuid> \
    --cron "0 3 * * 1" --params "marketplace=zepto workers=5" --catchup
```

> **`--catchup` matters here.** It does not mean "survives restarts" (everything
> does — schedules are DB rows). It decides whether a fire *missed while the runner
> was down* runs once on recovery. A weekly public scrape that misses its slot is a
> permanent hole in the series, so **public scrapes need `--catchup`.**

### Changed — read services

`inventory_service.py:252` and `reference_service.py:62` hardcode
`MarketplaceLocation.mp_slug == "blinkit"`. Everything else already threads a
`marketplace` filter through. Phase 6 audits each public-reading service end to end
and adds a marketplace selector to the dashboard.

**Do not surface Reach or Distribution for Zepto until the D8 question is settled.**
Those metrics are store-count ratios; if Zepto data is location-grain, the
denominators are meaningless and the numbers will be confidently wrong. (This is
the same FMCG trap already recorded for Blinkit.)

---

## Database & migrations

**Fact tables: no migration.** D3 means Zepto rows land in the existing tables with
`mp_slug='zepto'`. `ensure_refs()` auto-upserts the `marketplaces` row on first
write; `_MP_NAMES` in `scraper/utils/storage.py` already maps `zepto → "Zepto"`.

One optional migration, and only if Phase 0 justifies it:

| Change | Trigger | Note |
|---|---|---|
| `sku_snapshots.extra` (JSON, nullable) | Zepto returns per-SKU fields with no home in the current columns | `search_listings` already has `extra`; `sku_snapshots` does not. Adding a nullable JSON column is cheap, but adds ~bytes/row to the largest public table — weigh against D10 |

> Per [ways of working](../CLAUDE.md): **do not run any migration without showing
> the exact command and getting a go-ahead first.** When the time comes:
> ```bash
> alembic revision --autogenerate -m "add extra to sku_snapshots"
> alembic upgrade head
> ```
> Check `alembic current` first — the shared DB has drifted before (three
> divergent branches, resolved by a merge migration + `stamp`).

**Indexes.** The existing public indexes lead with `tenant_id`, not `mp_slug`:
`idx_snap_tenant_kw (tenant_id, mp_slug, keyword, scraped_at)` does cover
marketplace-filtered reads, but `idx_sku_tenant_product (tenant_id,
platform_product_id, scraped_at)` and `idx_sku_tenant_store` do not mention
`mp_slug` at all. With two marketplaces in one table these become less selective.
**Measure with `EXPLAIN ANALYZE` on real two-platform data before adding anything**
— an index is permanent disk against a 500 MB quota, and post-vacuum cold reads lie
about wall-clock timing.

---

## Capacity — the disk gate

This is the constraint most likely to stop the project, and it is not a code
problem.

| Fact | Value |
|---|---|
| Supabase quota | **500 MB, hard** |
| One day of Blinkit public scrape | ~92 MB (refills the tier in 3–5 days) |
| `DELETE` reclaims | **nothing** — rows are marked dead, the file never shrinks |
| Only reclaim path | `VACUUM FULL` (`python -m scripts.reclaim_space --apply`) |

**Gate (D10):** Zepto does **not** get an all-India schedule until:

1. A single-city Zepto run has completed and loaded (Phase 5).
2. Its actual bytes/row and row count are measured — not estimated from Blinkit's.
3. `python -m scripts.reclaim_space` shows the headroom to absorb the projected
   weekly volume **plus** Blinkit's.
4. If it doesn't fit, the decision is made **before** scaling, not after the tier
   goes read-only. The levers, in order of preference:
   - **narrower coverage** — top N cities rather than all-India for Zepto
   - **lower cadence** — fortnightly rather than weekly
   - **a retention policy** — the never-built lever that would help both platforms
   - **slim `extra`** — 284 bytes/row, over half of each listing row, mostly
     `image_url`
   - **a paid tier**

Rules that apply the moment there are two platforms in one table:

- `VACUUM FULL` **smallest table first** — it writes the new copy before dropping
  the old, so near the quota it fails or tips the project read-only.
- **Never from the Supabase SQL editor** (its HTTP gateway times out at ~1 min
  while Postgres keeps working) and **never during a scrape or `scrape load`**
  (ACCESS EXCLUSIVE lock).

Runtime capacity on the VM: Blinkit is ~1.5 h for 2059 stores at 5 workers. The
Zepto figure is Q2 × Q11 and cannot be estimated before Phase 0. Both share the
`batch` lane, so the weekly window is the **sum**, and the 12 h job timeout is a
safety ceiling that a healthy run should never approach.

---

## Build phases

Each phase is independently shippable and independently verifiable.

### Phase 0 — Recon ▢

- [ ] Capture a live Zepto search: request URL, method, headers, body, response
- [ ] Commit the response as `zepto/public_data/api.txt`
- [ ] Answer **Q1–Q12** and replace the open-questions table in this doc with a
      "Zepto API facts" section
- [ ] Confirm the store-binding mechanism actually changes the catalog (Q2) — a
      request that accepts a coordinate and ignores it is the silent failure
- [ ] Probe ~20 scattered Blinkit coordinates; record distinct Zepto store ids (Q11)
- [ ] Decide from Q3 whether the engine is browser-based or httpx-based
- [ ] Delete the throwaway probe script

**Gate:** no Zepto engine code until Q1–Q8 are answered.

### Phase 1 — Provider refactor (Blinkit only, zero behaviour change) ✅ 2026-08-03

- [x] `scraper/public/explorer/providers.py` → `scraper/public/providers.py`;
      the old path is a re-export. `Provider` gained `parse` + `result_cap`/`brand_cap`
      so the orchestrators need no platform import at all
- [x] `orchestrator.py` + `targeted.py`: `mp_slug` parameter, provider lookup,
      marketplace-filtered locations. **Zero platform imports remain in either**
- [x] `staging.py`: `mp_slug` column via `_add_missing`, filename segment,
      `resumable()` + `prune()` + `list_runs()`/`pending()` scoped by marketplace
- [x] `loader.py`: `mp_slug` from meta with a `"blinkit"` default → `ensure_refs`
      and `ScrapeJob.platform`
- [x] `sync.py`, `locations.py`, `scrape.py`, `jobs/types.py`: marketplace
      parameter, default `blinkit`
- [x] Config workbook: optional `mp` column on `locations` + `coverage`,
      blank → `blinkit`. **`--prune` now only deletes within the marketplaces the
      file mentions**
- [x] `inventory_service._store_names` and `reference_service.list_blinkit_zones`
      no longer hardcode the marketplace

**Verified:**

- [x] `cli sync --dry-run` on the live `config.xlsx` (2059 locations / 6 brands /
      242 coverage) → **0 added / 0 updated / 0 deleted**
- [x] Existing schedules' argv **byte-identical** — a spec with no `marketplace`
      param emits exactly the old command; a typo'd param name is rejected
- [x] All 7 pre-refactor staging files on disk read back as `blinkit`; a
      synthesised file with the `mp_slug` column *removed* still opens and reports
      `blinkit`
- [x] `--resume` isolation: two unfinished runs, one per marketplace, resolve to
      their own file
- [x] `ref()` / `resolve()` still work with the extra filename segment
- [x] Unwired (`zepto`) and unknown (`instacart`) marketplaces fail fast before any
      DB or browser work
- [x] `cli explore` imports clean (the re-export returns the same objects)
- [ ] **A one-city Blinkit `public-run` produces the same snapshot/listing counts
      and the same `brand_rank`/`brand_sov` as the previous run for that city** —
      not yet run; it is a live scrape and belongs on the VM, not a home IP

**Gate (D9):** merge and let one scheduled Blinkit run pass clean on the VM before
Phase 2 starts. The live-run check above is that gate.

### Phase 2 — Zepto engine ▢

- [ ] Delete the four stub modules; repoint `cli scrape public --platform zepto`
- [ ] `endpoints.py` — every URL/header/body/tunable, nothing inline elsewhere
- [ ] `scraper.py` — session lifecycle, in-page (or httpx) fetch with double
      timeout + retry/backoff, pagination, `product_id` dedupe keeping first
      sighting, position fallback
- [ ] `parser.py` — `classify_products`, `"provider": "zepto"`
- [ ] Register the provider `wired=True`
- [ ] Manual smoke: `cli scrape public --keyword "cola" --brand "<brand>"
      --platform zepto` returns plausible products at two different coordinates
      **with different catalogs**

### Phase 3 — Zepto store catalog ▢

**Blocked on Q9.** This phase is mostly *sourcing*, not coding — start chasing it
during Phase 0, not here.

- [ ] Obtain the Zepto store list (Q9): store id, coordinate, city, state, region,
      pincode, name, address
- [ ] Spot-check ~10 rows by probing the coordinate and confirming the returned
      store id matches — a catalog that doesn't resolve is worse than none
- [ ] Load into `config.xlsx` `locations` sheet with **`mp=zepto`**
- [ ] `cli sync --dry-run` — expect `locations added = <N zepto>`, and
      **`deleted = 0`**. Any Blinkit deletion means the `mp` column is wrong; stop
- [ ] `cli sync` (confirm before writing — shared-DB write)
- [ ] `cli locations list -m zepto` shows the catalog; count matches the source
- [ ] Record in this doc: store count, city count, and how the catalog was obtained
      (so it can be refreshed)
- [ ] Add Zepto `coverage` rows for the pilot tenant, one city; `--dry-run` then apply

### Phase 4 — First real run, one city ▢

- [ ] `cli scrape public-run -m zepto -t <uuid> --city <slug> --no-load`
- [ ] Inspect the staging file directly (SQLite) **before** loading — field
      coverage, nulls, `pack_*` parse rate, `merchant_id`/`merchant_type` fill rate
- [ ] Validate `pack.py` against real Zepto unit strings; extend `_UOM`/`_TERM` if
      needed and **re-validate against the Blinkit corpus** (D7)
- [ ] `cli scrape load --file <ref>` once the file looks right
- [ ] Same for `public-skus`
- [ ] Cross-check a handful of rows against the Zepto app by hand — price, stock,
      pack. This is the only real correctness test available

### Phase 5 — Scale-out & scheduling ▢

- [ ] Tune `--workers` from observed rate limiting (Q10)
- [ ] Set per-tenant `keyword_cap` / `brand_cap` for Zepto from the observed page
      size and tier depth
- [ ] Measure bytes/row and total rows; **run the D10 disk gate**
- [ ] Merge to `main`, pull on the VM
- [ ] `cli schedules add --type scrape.public_keyword --params "marketplace=zepto …"
      --catchup`, offset from the Blinkit slot
- [ ] Watch the first scheduled run: `cli jobs list`, `cli jobs logs <id> -f`,
      peak RSS, and that `scrape staged` ends empty (auto-load worked)

### Phase 6 — Read layer & dashboard ▢

- [ ] Audit every public-reading service for hardcoded `"blinkit"`
- [ ] Marketplace selector in the dashboard views that support it
- [ ] Decide per view: comparable across platforms, or platform-specific?
- [ ] **Withhold Reach/Distribution for Zepto** until D8 is settled
- [ ] Update [dashboard-views.md](dashboard-views.md),
      [public-glossary.md](public-glossary.md), [cli.md](cli.md),
      [ARCHITECTURE.md](ARCHITECTURE.md), and the CLAUDE.md quick-ref

---

## Code conventions — the checklist for this work

Straight from [code-standards.md](code-standards.md); these are the ones this build
will actually be tempted to break.

- [ ] **Functions, not classes.** Module-level async functions, state passed
      explicitly. The session is a plain `dict`, like Blinkit's and like the staging
      handle. Exceptions: SQLModel tables, Pydantic settings, and the frozen
      `Provider` data record.
- [ ] **All URLs / header keys / bodies in `endpoints.py`.** Nothing inline.
- [ ] **Raw in, parsed out.** `scraper.py` extracts, `parser.py` types and
      classifies.
- [ ] **Async everywhere.** No `threading.Thread`, no `time.sleep()`.
- [ ] **`from app.utils.logger import logger`. Never `print()`.** The CLI's `rich`
      console output is a separate, deliberate channel — logs are not.
- [ ] **`ensure_refs(session, brand_slug, mp_slug)` before every public write** —
      it is what satisfies the FKs to `brands` and `marketplaces`.
- [ ] **Public data is append-only.** No upsert, no unique constraint. Which is
      exactly why the loader must stay all-or-nothing.
- [ ] **Timestamps via `now_ist()`**, and `scraped_at` is stamped at *scrape* time
      and carried through the staging file untouched. Loading tomorrow must not
      backdate today's trend series.
- [ ] **Comments explain *why*, not *what*.** Match the density of the surrounding
      Blinkit modules — the incident-derived warnings are the most valuable text in
      that package.
- [ ] **One shared `pack.py`**, extended not forked (D7).
- [ ] **No platform logic in `search_result.py`.**

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Zepto binds store per-session, not per-request (Q2) | Medium | **High** — the cost model collapses | Phase 0 gates everything. Fallbacks: fewer stores, lower cadence, or session-per-store with a much smaller catalog |
| Disk quota can't absorb a second platform (D10) | **High** | High | The Phase 5 gate. Levers listed and pre-ranked so the decision isn't made under pressure |
| **No obtainable Zepto store catalog (Q9)** | Medium | **High** — Phase 3 cannot start | Chase it from Phase 0, in parallel with the protocol work. Fallback is discovery-by-probing off a *Zepto-native* coordinate source, designed then. **Not** Blinkit's rows (D4) |
| Someone reuses Blinkit's coordinates as Zepto probe points | Medium | High — silently wrong coverage/Reach denominators | D4 states it twice, and `cli sync --dry-run` makes a mis-`mp`'d workbook visible as a 2059-row deletion before it lands |
| No per-product store id (Q4) | Medium | Medium | Accept location-grain for Zepto; document the asymmetry; withhold Reach/Distribution rather than publishing wrong denominators |
| Phase 1 refactor silently changes Blinkit output | Low | **High** — live client data | Phase 1 ships alone with explicit before/after verification, and one clean scheduled VM run before Phase 2 (D9) |
| Zepto blocks the datacenter IP (Q12) | Low | High | Detected in Phase 0, before any investment |
| Aggressive rate limiting at 5 workers (Q10) | Medium | Medium | Reuse the tuned retry/backoff/session-refresh ladder; lower `--workers`; runtime is the only cost |
| `cli sync --prune` wipes the Blinkit catalog during the `mp` column transition | Medium | **High** | `--dry-run` mandatory; treat any `locations` deletion as stop-and-check |
| Zepto's DOM/API shifts (they rebranded domains once already) | Medium | Medium | Everything volatile confined to `endpoints.py`; `api.txt` records what we built against |

---

## After Public — the rest of the Zepto surface

Not designed here. Recorded so the public work doesn't foreclose it.

| Area | Blinkit today | Zepto shape | Notes |
|---|---|---|---|
| **Auth** | Magic link (marketing) + OTP (seller), three-layer capture (cookies + localStorage + **Firebase IndexedDB**), Fernet-encrypted into `platform_sessions` | `cli auth zepto --tenant <uuid>` | The session-restore **ordering is non-negotiable**: `storage_state` → IndexedDB init script → write blocker. Verify whether Zepto uses Firebase at all before assuming the same shape. Must work `--headless` for SSH re-auth on the VM |
| **Private data** | **Two** dashboards — marketing (`brands.blinkit.com`) and seller (`partnersbiz.com`) | **One** dashboard covering sales *and* marketing | This is the notable structural difference. It likely means one `dashboard_data/` subpackage, not two — but possibly two storage targets from one scrape |
| **Tables** | `blinkit_seller_*`, `blinkit_marketing_*` | `zepto_*`, mirroring the same split | Private data **is** platform-specific (unlike public) — separate tables, upsert on `upsert_key`, per [code-standards.md](code-standards.md) |
| **Campaign automations** | Campaign Manager v2 (`campaign_manager/`), marketplace-namespaced at `campaign_manager/marketplaces/blinkit/` | `campaign_manager/marketplaces/zepto/` | v2 was **already built with this in mind** — the marketplace directory exists precisely so a second platform slots in. Blocked on Zepto auth + private data |
| **CLI** | `auth blinkit`, `scrape blinkit`, `scrape blinkit-seller`, `scrape blinkit-scorecard` | `auth zepto`, `scrape zepto` | Private commands are per-platform (the dashboards differ); public commands are marketplace-*parameterised* (D5). That asymmetry is intentional |
| **Jobs** | `scrape.blinkit_marketing` / `_seller` / `_scorecard` in `Lane.dashboard` | `scrape.zepto_dashboard` | New job types (unlike public, D6) because the argv and timeouts genuinely differ |

**Ordering constraint:** campaign automations depend on private data, which depends
on auth. Public data depends on none of them, which is why it goes first.
