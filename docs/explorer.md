# Explorer — On-Demand Custom Scrape → Excel

The Explorer is an **agency-facing, on-demand custom scrape** tool. It reuses the
public scrape engine but is driven by **ad-hoc inputs** (any marketplace / brand /
competitors / keywords / cities) instead of a tenant's watchlist, and emits a
**multi-sheet Excel workbook** instead of the per-tenant fact tables.

Its job: profile a **prospect** (not yet a client) or run a one-off deep-dive in
minutes, with **nothing persisted into client data**.

> Status: **CLI shipped (Phases 0–3).** Runnable via `cli explore` — see
> [cli.md](cli.md). The admin API + React page (Phase 4) are still to build; this
> doc remains the design + decisions log.

---

## Locked decisions

| Fork | Decision | Why |
|---|---|---|
| Interface | **CLI now, admin UI later** — one service layer both call | The engine is the reusable core; the CLI is a thin wrapper, a future API is another |
| Persistence | **Ephemeral + job log** | Scrape → Excel; NO rows in `search_snapshots`/`sku_snapshots`. A `explorer_runs` row is the audit/progress record |
| Target | **Standalone / any brand** — no tenant required | The value is profiling non-clients (prospects). Optional `--tenant` only seeds defaults |
| Locations | **Reuse catalog by city** — `marketplace_locations`, ignore `tenant_locations` | Zero new discovery code. Limitation: only cities already in the catalog are reachable |
| Capture | **Full raw field set** (superset of what the tables keep) | Ephemeral, so no reason to trim — capture everything the engine extracts |
| Marketplace | **`--marketplace` selector, provider-abstracted** | Blinkit works today; Instamart/Zepto plug in behind a common provider interface |

---

## Frontend-ready architecture (build accordingly)

The Explorer **will be wired into the frontend** (admin-only page: submit a run →
watch progress → download the workbook / browse insights). So it is built as a
**service layer**, not a CLI script. Layering:

```
ExplorerSpec (Pydantic)            ← app/schemas/explorer.py; doubles as the future API body
        │
run_explorer(db, spec, on_progress=…)   ← scraper/public/explorer/orchestrator.py
        │   orchestrates the scrape (worker pool, catalog-by-city + sampling),
        │   accumulates results IN MEMORY (no fact-table writes),
        │   drives explorer_runs status + progress, returns an ExplorerResult
        ▼
build_insights(result) → ExplorerInsights   ← scraper/public/explorer/insights.py (PURE)
        │   all aggregations (scorecards, landscape, pricing, geography).
        │   Reused by BOTH the Excel writer AND a future JSON insights endpoint.
        ├────────────────────────────┐
        ▼                            ▼
write_workbook(insights, result)   (future) GET /explorer/{id}/insights → JSON
  → scraper/public/explorer/export.py   (future) GET /explorer/{id}/download → .xlsx
```

Actual package layout (Phases 1–3): `scraper/public/explorer/` holds `providers.py`
(marketplace registry), `orchestrator.py` (`run_explorer`), `insights.py`
(`build_insights`), `export.py` (`write_workbook`); schemas in
`app/schemas/explorer.py`; the command in `cli/commands/explore.py`.

Key consequences of "frontend later":

- **`ExplorerSpec` is Pydantic** — the CLI parses argv into it; a future
  `POST /explorer` validates the request body into the same model.
- **`build_insights` is a pure function** returning a typed `ExplorerInsights` — the
  frontend can render the exact same insights as charts/JSON without Excel. The
  Excel writer is just one consumer of it.
- **`explorer_runs` is a pollable job record** — status lifecycle
  (`pending → running → success/failed`) + progress counters (`processed`/`total`)
  + the full `params` (JSON) + the artifact path + creator attribution. A UI
  progress bar and run-history list read straight off it.
- **`run_explorer` is async + background-runnable** with an `on_progress` callback
  — a future endpoint launches it as a background task and returns the run id
  immediately; the CLI just `await`s it and prints a summary. The callback updates
  `explorer_runs.processed`/`total` so the UI can poll.
- **The provider registry exposes capabilities** — a future
  `GET /explorer/marketplaces` returns which marketplaces are supported so the
  frontend selector only offers wired ones.

---

## Marketplace abstraction (the selector)

A **provider** is a module implementing a common interface (functions, per the
house rules — no classes):

```
open_session(browser, lat, lon)                       → session | None
search(session, keyword, cap, lat, lon, follow_similarity) → {products, total_results, merchant_id, ok, error}
close_session(session)
extract(...)  → maps the platform payload to the COMMON product schema
```

Registry in `scraper/public/explorer/providers.py`:

| Marketplace | Status | Notes |
|---|---|---|
| `blinkit` | **functional** | `open_context_session`/`search` already match this interface |
| `instamart` | planned | module exists on the old one-shot interface; needs a refactor onto this one |
| `zepto` | planned | same |

`--marketplace blinkit` is the default. Selecting an unwired marketplace fails
fast: *"instamart is not yet supported by Explorer."* Insight sheets use only the
**common core fields**, so they render identically for any future marketplace;
provider-specific extras ride in the raw sheets.

**Common product schema** (every provider maps to this): `product_id, name, brand,
price, mrp, unit, inventory, in_stock, rating, product_state, position, group_id,
merchant_id, merchant_type, image_url, ptype, category{l0,l1,l2}, match_reason`
(+ computed `discount_pct`, `is_brand`, `is_combo`). This is the full set the
Blinkit engine already extracts — a superset of what `search_listings` persists.

---

## Run model

- **Focus brand** (free-text slug) + **aliases** + optional **competitor
  whitelist** (default: keep-all, so the competitive landscape is *discovered*).
- **Keywords** (comma list) × **cities** (comma list, from the catalog).
- **Two modes, both in the first cut:**
  - *keyword mode* (default) — SoV / rank / competitors / pricing per keyword.
  - *catalog mode* (`--catalog`) — searches the brand name, paginates its catalog
    per location → own-SKU distribution / pricing / rating.
- **Location sampling** — `--sample N` (default ~50, spread across a city's
  distinct `(lat,lon)`) keeps a pitch run to minutes; `--full` runs the census.
- **Standalone** — no tenant required. Optional `--tenant` only *seeds* defaults
  (aliases/competitors) from a client's watchlist.

Grain = `keyword × location`, exactly like the keyword orchestrator, so the worker
pool and session-reuse carry over unchanged.

---

## The workbook (insights first, raw last)

**Insight / analysis sheets**

1. **Run Overview** — all params + headline KPIs: overall SoV%, avg rank,
   in-stock%, #keywords in top-3, strongest/weakest keyword & city, coverage,
   error count.
2. **Keyword Scorecard** — per keyword: avg rank, best rank, SoV%, presence%
   (locations where the brand appears), in-stock%, #competitors, top competitor.
3. **Geography** — per city: SoV%, avg rank, in-stock%, coverage.
4. **Competitor Landscape** — run-wide leaderboard: competitor, #locations seen,
   avg position, share-of-shelf%, avg price.
5. **Price & Discount** — own vs competitor price band (min/median/max) + discount
   depth, per keyword.
6. **Availability** — in-stock% per keyword × city; OOS hotspots.
7. **Own Catalog** *(catalog mode)* — per SKU: distribution%, reach%, price band,
   discount, rating.

Insight sheets get frozen headers, ₹/% number formats, conditional-format colour
scales (SoV / rank / in-stock), and a couple of native `openpyxl` bar charts on
the Scorecard / Landscape sheets.

**Raw sheets (end)**

8. **Raw — Snapshots** — one row per (keyword × location): rank, SoV,
   total_results, brand product count, merchant_id, lat/lon, city.
9. **Raw — Listings** — every product row with the **full field set**.
10. **Raw — Catalog SKUs** *(catalog mode)* — every own-SKU probe row.
11. **Raw — Locations** — the sampled locations used.

All aggregation lives in `build_insights`; the workbook writer only formats the
typed `ExplorerInsights` it returns (so the same numbers feed a future JSON endpoint).

---

## Persistence — `explorer_runs`

A dedicated additive table (chosen over nullabling the `NOT NULL` FK on the hot
`scrape_jobs` table — safer, and it keeps Explorer cleanly outside client data).
It is the **job/audit/progress record** the frontend polls:

- `status` (`pending → running → success/failed`), `processed`/`total` (progress),
  `started_at`/`completed_at`.
- `params` (JSON) — the full `ExplorerSpec`, so a run is reproducible / re-runnable
  from the UI.
- Result counters: `keywords`, `locations`, `snapshots`, `rows`, `errors`.
- `output_path` / `output_filename` — the workbook artifact (local disk now;
  object storage + a download endpoint in the frontend phase).
- `account_id` / `tenant_id` — nullable creator attribution (CLI runs have neither).

The scrape itself writes **nothing** to `search_snapshots` / `search_listings` /
`sku_snapshots`.

---

## Build phases

- **Phase 0 ✅** — `app/models/explorer.py` (`ExplorerRun`) + migration `a3e8d1f6c2b9`.
- **Phase 1 ✅** — `explorer/providers.py` (registry) + `app/schemas/explorer.py`
  (`ExplorerSpec`) + `explorer/orchestrator.py` (`run_explorer` — catalog-by-city
  resolver + even-sampling, in-memory accumulation, `explorer_runs` status/progress).
- **Phase 2 ✅** — `explorer/insights.py` (`build_insights` → `ExplorerInsights`) +
  `explorer/export.py` (`write_workbook`, the multi-sheet workbook).
- **Phase 3 ✅** — `cli/commands/explore.py` (`cli explore`, registered in `cli/main.py`).
- **Phase 4 (later)** — async job runner + admin `/explorer` endpoints (submit /
  status / insights / download / marketplaces) + React `features/explorer/` page.
  The engine is already frontend-ready, so this is wiring, not redesign.

```bash
python -m cli explore \
  --marketplace blinkit \
  --brand "dobra" --aliases "dobra,dobra cola" \
  --competitors "coca-cola,paper boat" \
  --keyword "cola,soda,lemonade" \
  --city bengaluru,mumbai \
  --sample 50 --workers 5 --catalog \
  -o dobra_explore.xlsx
```

See also [public-scraper-refactor.md](public-scraper-refactor.md) (the engine this
reuses) and [public-glossary.md](public-glossary.md) (Reach / Distribution / SoV).
