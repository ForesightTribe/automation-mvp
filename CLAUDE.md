# Foresight — Automation MVP

## Documentation

| File | Contents |
|---|---|
| [docs/project-overview.md](docs/project-overview.md) | What the product is, stack, platform coverage, what data is collected |
| [docs/architecture.md](docs/architecture.md) | Directory layout, data flow, DB schema, public/private scraper internals, how to add a platform |
| [docs/code-standards.md](docs/code-standards.md) | Functions-not-classes, selectors.py, raw→parsed, async, logging, DB patterns, currency parsing |
| [docs/setup.md](docs/setup.md) | Env setup, Alembic, first run checklist |
| [docs/cli.md](docs/cli.md) | Full CLI reference — all commands with examples |
| [docs/api-reference.md](docs/api-reference.md) | REST API reference — every module (auth, clients, analytics, ads, competition, …), endpoints, scoping, conventions |
| [docs/dashboard-views.md](docs/dashboard-views.md) | Dashboard insight catalog — questions → page/section → tables+columns → API. Build reference for the frontend |
| [docs/frontend-architecture.md](docs/frontend-architecture.md) | Frontend stack, feature-first folder structure, state split (Context vs React Query), data flow, how to add a page |
| [docs/ui-rules.md](docs/ui-rules.md) | Frontend coding/styling conventions — arrow components, Tailwind v4 theme tokens, error layers, logging |
| [docs/public-scraper-refactor.md](docs/public-scraper-refactor.md) | Public scraper — decisions log, cost/volume sizing, and remaining open items (refactor shipped) |
| [docs/public-glossary.md](docs/public-glossary.md) | Public-data glossary & model — serviceable location unit, Reach vs Distribution, SoV/rank, Main-vs-Combo, sku_map, the two scrapes |
| [docs/darkstores.md](docs/darkstores.md) | **Dark-store-level public data** (designed, not built) — merchant_id/merchant_type from the atc block, the probe-vs-store model, evidence log, proposed DB changes, tier caveats |
| [docs/staging.md](docs/staging.md) | **Public scrapes stage to local SQLite**, then `cli scrape load` pushes to Postgres in one all-or-nothing transaction — why, commands, retention, failure modes |
| [docs/explorer.md](docs/explorer.md) | Explorer — on-demand custom scrape → Excel (agency-facing, ephemeral); design, decisions, architecture, build phases |
| [docs/exports.md](docs/exports.md) | **Exports — public report SHIPPED 2026-08-10** (Phases 1–3). `python -m cli export public -t <uuid>` builds a 13-sheet client workbook from stored data; **`export raw` dumps the underlying rows to CSV as a SEPARATE command** (~300k rows/79 MB per week — deliberately never bundled into the report, so the future download button stays small); `export sample` renders a fixture with no DB; `export sections` lists what's buildable. `backend/exports/` (top-level package, sibling of `jobs/`) = theme + workbook (**the one Excel writer — Explorer renders through it too**) + glossary (wording **guard**, raises at render on "reach"/"distribution"/"SoV", for every consumer) + registry + sections. Numbers come from the read services, never new SQL (one documented exception: Product Families projects `_latest_per_store` for family×store grain). Doc covers the design system, clarity rules, gotchas, phases. Artifacts land in `backend/out/` (gitignored). **Marketing/Ads + Sales/Ops reports are PLANNED** in the doc (two reports, Indian ₹ grouping, 28-day window, KPI deltas; Sales report will delete `export_to_excel.py`). Legacy `build_public_analysis.py`/`build_sku_analysis.py` deleted |
| [docs/per-unit-price.md](docs/per-unit-price.md) | **Per-unit price** (shipped 2026-07-24) — parse Blinkit's `unit` string into pack_size/uom/count, derive ₹/100 ml·100 g·piece; supersedes `grammage`; `is_combo` from `pack_count` |
| [docs/platform-auth.md](docs/platform-auth.md) | **Platform auth** — logging in to marketplace dashboards. Both Blinkit logins are browserless REST; session synthesis, the 7-day expiry gate, the `platform_auth/` layout, inbox reader, CLI |
| [docs/campaign-manager.md](docs/campaign-manager.md) | **Campaign Manager — the one CM doc.** What it is, the reconciler, the budget + bid engines (window floors, drift-down, unreachable-target fallback, bounds invariants), the gated write choke-point, the Blinkit contract (a bid write is a whole-campaign PUT; `DELETE` = stop, not delete; status vocabulary), **a full edge-case reference**, config + kill switches, how to roll it out, and the known gaps |
| [docs/jobs.md](docs/jobs.md) | Jobs, scheduler & observability — the VM job queue + runner, `job_schedules`, per-run logs → Cloud Logging, monitoring; design, decisions, build phases |
| [docs/jobs-runbook.md](docs/jobs-runbook.md) | Jobs & scheduler **runbook** — full CLI reference, how to run it local vs VM, where to view logs, edge cases, troubleshooting |
| [docs/vm.md](docs/vm.md) | The scraper VM (GCP Mumbai) — why an Indian IP, box spec, provisioning scripts, re-auth on the box, cost/capacity model, and the VM gotchas |
| [docs/zepto.md](docs/zepto.md) | **Zepto — platform build plan (Public Data first, PLANNED)** — decisions, the Phase 0 API recon questions, provider-abstraction refactor, Zepto's own store catalog, file-by-file spec, CLI/jobs/VM fit, the disk gate, and the post-public roadmap |

---

## Ways of Working — Explain & Confirm Crucial Decisions

Before anything hard to reverse or that changes shared/persistent state, **stop,
explain, and ask — do not just do it:**

- **DB migrations** (`alembic upgrade` / `downgrade` / `stamp` / `revision`):
  explain what the migration changes and **show the exact command**, then wait for
  the go-ahead before running it.
- **Data writes/deletes on the shared DB** (`TRUNCATE`, `DELETE`, `UPDATE`, bulk
  inserts, backfills, or a scrape run that persists rows): explain the effect and
  **show the exact command / SQL**, then confirm before running.
- **Any other crucial or irreversible call** — schema changes, dropping data,
  destructive git operations, anything touching production/shared state.

State the reasoning and the command up front, then wait. Read-only inspection
(`SELECT`, `information_schema`, `alembic current/history`) may be run directly. If
a decision is genuinely the user's (which approach, which data to clear), ask
rather than assume.

---

## Stack (quick ref)

- **Runtime**: Python **3.11** (3.11.9), fully async/await — local venv, Render and the scraper VM are all pinned to 3.11; keep them aligned
- **API**: FastAPI + Uvicorn
- **Database**: PostgreSQL via Supabase — SQLModel, asyncpg, Alembic
- **Browser**: Playwright (Chromium)
- **Encryption**: Fernet (`cryptography`)
- **Logging**: loguru — `from app.utils.logger import logger`, never `print()`
- **CLI**: typer + rich
- **Frontend**: Vite 8 + React 19, Tailwind v4, react-router v7, React Query v5 — see [docs/frontend-architecture.md](docs/frontend-architecture.md)

## Environment

`.env` requires three keys:

```env
DATABASE_URL=postgresql://...   # Supabase Session Pooler URL (NOT the direct/IPv6 URL)
ENCRYPTION_KEY=...              # Fernet key
SECRET_KEY=...                  # JWT secret
```

`database.py` normalises the URL to `postgresql+asyncpg://` — always write `postgresql://` in `.env`.

## Deployment (quick ref — see [docs/vm.md](docs/vm.md))

Frontend → **Vercel**. API → **Render**. **Scrapers → a GCP VM in Mumbai**, because
Blinkit is India-geo and a US/EU datacenter IP is a block risk. Validated
2026-07-13: headless Chromium + Cloudflare + DB write all work from that box.

The things that bite:

- **The VM runs `main`.** Nothing on `dev` exists on the box.
- **Sessions are not files** — they live encrypted in Supabase, so there is nothing
  to copy to the VM. Same `DATABASE_URL` + `ENCRYPTION_KEY` = it just works. A wrong
  `ENCRYPTION_KEY` fails quietly.
- **Logins need no browser and no human** — all three dashboards (2× Blinkit, Zepto)
  authenticate over plain HTTP, and the OTP/magic link is read from the auth inbox.
  `cli auth login <platform> -t <uuid>`. Scrapers call `ensure()` and get a working
  session, so an expired one self-heals. Every `cli auth` command is generic over the
  registry — adding Zepto needed no CLI change. See
  [docs/platform-auth.md](docs/platform-auth.md).
- **⚠️ Zepto breaks two assumptions the rest of auth is built on.** It **cannot refresh**
  (no endpoint exists; its JWT dies at **local midnight IST**), so it is the one platform
  whose *login* is scheduled — `auth.login`, 00:05 IST, and `refresh-all` correctly
  reports it `not_refreshable`. And it permits **one session per user**: a new login
  revokes the previous one, so our login evicts a human's dashboard and theirs kills our
  session mid-run. Trust `auth probe`, never `expires_at` alone. The Zepto schedule stays
  **disabled** until the client provisions a service user.
- **Anything scheduled needs the full interpreter path** and an explicit output
  redirect — cron/systemd never run `activate` and have no terminal, so a bare
  `python` fails with `ModuleNotFoundError` and unredirected output vanishes.
- **`playwright install-deps` needs sudo; `playwright install chromium` must not** —
  as root the browser lands in root's cache and the scraper can't find it.

## Jobs & Scheduler (quick ref — see [docs/jobs.md](docs/jobs.md) · [runbook](docs/jobs-runbook.md))

**Live on the VM since 2026-07-17.** Scrapes no longer get typed by hand: the
top-level **`jobs/`** package runs a `runner` daemon (systemd) that is both a
**producer** (cron → enqueue) and a **consumer** (claim → run). Every run is a row in
the `jobs` table; each job is executed as a **subprocess** — the exact
`python -m cli scrape …` you would otherwise type — with its output going to a
per-run log file.

```bash
python -m cli status [--days N]              # ONE SCREEN: runner alive? overdue schedules? failures? where compute went
python -m cli jobs types                     # job types, lanes, timeouts, valid params
python -m cli jobs run <type> -t <uuid> city=bengaluru workers=5   # queue now
python -m cli jobs list / logs <id> -f       # status+peak RAM / live-tail a run
python -m cli schedules add|list|show|update|enable|disable|remove  # cron CRUD (IST)
python -m cli runner start                   # the daemon (systemd does this on the VM)
```

- **`cli status` is the first thing to run when something feels wrong.** It reads the
  shared `jobs`/`job_schedules` tables, so it works **from a laptop with no VM access** —
  that is how the 2026-08-18 logging blackout was diagnosed. It reuses the same
  `check_deadman()` the hourly health check runs, so its verdict on "did scheduled work
  actually run?" is identical. It does NOT report disk (that would measure whichever
  machine you ran it on, not the VM — disk stays with `monitor.heartbeat`).
- **Job types carry a human `label`** (`jobs/types.py`) — `scrape.blinkit_marketing` is a
  registry key, `"Blinkit ads scrape"` is what it *is*. Logs, `cli status` and alerts read
  the label; add one with every new job type. `label_for()` never raises on an unknown
  type, because the case that produces one is deploy skew — exactly when a readable
  message matters most.
- **A failed job's log lines quote the child's own log.** The runner supervises
  subprocesses, so an exit code is genuinely all it sees; `jobs/runner.py::_tail_lines`
  seeks the END of the run's log file (never reads a multi-GB scrape log whole) and puts
  the last real line into the failure message and the `log_tail` structured field.
- ⚠️ **Two different things were once both called "heartbeat".** `monitor.heartbeat` is the
  hourly deadman JOB. The scheduler's 15-minute "still alive" line is an **idle notice**
  (`jobs/scheduler.py::_idle_notice`) — renamed 2026-08-18 after the collision sent a real
  investigation looking for an hourly job that didn't exist.

- **Lanes, not one queue.** `batch` (public scrapes) · `dashboard` (marketing/seller/
  scorecard) · `live` (bid optimizer, later) · `interactive` (explorer/heartbeat).
  Lanes run in parallel, sequential within themselves — so a 5-hour scrape can never
  starve a latency-critical loop. Lane comes from the **job type**, not the caller.
- **Params are trailing `key=value` pairs** and map 1:1 onto the real CLI flags (but
  the names differ sometimes: `date_from` → `--from`). Quote values with spaces:
  `"city=delhi ncr"`.
- **The registry is code** — [jobs/types.py](backend/jobs/types.py) is the single
  extension point (type → lane, timeout, argv builder). Adding a job type = one entry.
- **Config split:** job types/lanes/timeouts → code · `LANE_SLOTS`/`DB_POOL_SIZE`/
  `LOG_DIR` → env (all have defaults; **no new `.env` keys required**) · cron/params/
  catchup → the `job_schedules` **table**, editable live with no restart.
- **`--catchup` ≠ "survives restarts"** (everything does — schedules are DB rows). It
  only decides whether a fire **missed while the runner was down** runs once on
  recovery. Marketing re-scrapes 7 days so a miss self-heals; **seller/scorecard only
  scrape one day/week → a miss is a permanent gap → they need `--catchup`.**
- **⚠️ Never leave a runner running locally** — laptop and VM share one database, so a
  local runner will claim VM jobs and scrape from your home IP.
- **Alembic is single-head again** (`b6b4f0f7ee83`, merge of the darkstore +
  campaign lines, stamped 2026-07-21) — `alembic upgrade head` works normally.
- **Campaign automation is `campaign_manager/`, owned by Deepansh.** Runs in the
  `cm_bid` / `cm_ops` / `interactive` lanes; **dry-run by default**, live writes armed
  per tenant (`live_armed` on `cm_platform_accounts`). `ad_campaigns/` is **dead code** —
  disabled 2026-07-30 (VM schedules 24 + 25 `enabled=false`, Playwright routes removed
  from `app/routes/ads.py` so Render can't spawn Chromium), its `client.py` +
  `live_position.py` vendored into `campaign_manager/marketplaces/blinkit/`. Kept on disk,
  imported by nothing. See [docs/campaign-manager.md](docs/campaign-manager.md).

## Database Patterns

**Session**
```python
async with AsyncSessionLocal() as session:
    result = await session.execute(select(Model).where(...))
```

**Upsert (private data)**
```python
from sqlalchemy.dialects.postgresql import insert
stmt = insert(Model).values(rows).on_conflict_do_update(
    index_elements=["upsert_key"], set_={...}
)
await session.execute(stmt)
await session.commit()
```

**Public data** — append-only, no upsert:
```python
session.add(SearchResult(...))
await session.commit()
```

**ensure_refs()** — call before every public data save:
```python
await ensure_refs(session, brand_slug, mp_slug)  # auto-upserts brands + marketplaces
```

**Migrations** — after editing any SQLModel table class:
```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

**⚠️ Disk is the binding constraint** — Supabase free tier, **500 MB hard quota**, and one
day of public scrape is ~92 MB (refills the tier in 3–5 days). `DELETE` frees **nothing**
(rows are only marked dead; the file never shrinks) and every `UPDATE` leaves a dead row
version, so a bulk backfill costs **~2× the table** until vacuumed. Only `VACUUM FULL`
reclaims. Before any bulk `UPDATE`/`DELETE`, check free space and plan the reclaim as part
of the job:
```bash
python -m scripts.reclaim_space                  # report sizes
python -m scripts.reclaim_space --apply          # REINDEX each index, then VACUUM FULL
```
- **Smallest table first** — `VACUUM FULL` writes the new copy before dropping the old, so
  near the quota it fails (or tips the project read-only). Each table frees headroom for
  the next; that's why the script reindexes before vacuuming.
- **Never from the Supabase SQL editor** — its HTTP gateway times out ~1 min ("upstream
  timeout") while Postgres keeps working, and `SET statement_timeout` can't fix a *proxy*
  timeout. Never during a scrape/`scrape load` either (ACCESS EXCLUSIVE lock).
- **Don't benchmark right after a vacuum** — it rewrites into a new file, so every read is
  cold (we saw 18–28 s settle to 0.5 s). Trust `EXPLAIN ANALYZE` over wall-clock.

Script docstring has the full rationale. Growth levers not yet built: slim `extra`
(284 bytes/row, >half of each listing row, mostly `image_url`) and a retention policy.

## Accounts, Clients, Users

The API is multi-tenant: **Account** (subscriber org, logs in & pays) → **Client**
(the `tenants` table / `tenant_id`, the data unit) → **User** (login). A Client
belongs to an Account; a User belongs to an Account and can act on any of its
Clients. The JWT carries `account_id` + `role`; the active client is chosen
per-request (`/api/clients/{client_id}/...`) and access-checked against the account.

**Users** are provisioned via the CLI only — no public signup. `account create`
makes the account + its first `admin` user; `account add-user` adds more users to
an existing account (`member` by default, `--admin` for admin). Data is
**account-scoped** — every user of an account sees all its clients; `role`
(`admin`/`member`) gates only the Settings/admin UI and `require_admin` routes,
not data. See [docs/api-reference.md](docs/api-reference.md) and the user-creation
flow in [docs/setup.md](docs/setup.md).

## Seeding

- `brands` and `marketplaces` are auto-upserted by `ensure_refs()` — no manual seeding for public scrapers.
- A `tenants` row (Client) now belongs to an **Account**. Create the account + its
  first admin login, then the client under it, and optionally more users:
  ```bash
  python -m cli account create --name "Foresight" --admin-email you@foresight.com
  python -m cli tenant create --name "Dobra" --account <account-id>
  python -m cli account add-user --account <account-id> --email teammate@foresight.com
  ```

## Coding Rules (abbreviated — see docs/code-standards.md)

- **Functions, not classes** — module-level async functions, state passed explicitly. Exception: SQLModel table models, Pydantic Settings.
- **selectors.py** — all CSS selectors and URL paths for Blinkit live there, nowhere else.
- **Raw → parsed** — `scraper.py` returns raw strings; `parser.py` cleans and types them.
- **Async everywhere** — no `threading.Thread`, no `time.sleep()`.

## Session Restore — Critical

When restoring a saved Playwright session, order is non-negotiable:

```python
ctx = await browser.new_context(storage_state=state)           # 1. cookies + localStorage
await ctx.add_init_script(firebase_idb_inject(session_data))   # 2. Firebase IndexedDB — BEFORE page JS
await ctx.route("**/*", write_blocker)                         # 3. block writes
```

Step 2 must execute before any page JavaScript. Firebase JS SDK v9+ stores the refresh token in IndexedDB only. Skip this step and Firebase sees the session as expired despite valid cookies.

## Public Scraper — Key Facts

Blinkit-only (Instamart/Zepto are out of scope). Fully per-tenant and DB-driven.
Deep dive + status: [docs/public-scraper-refactor.md](docs/public-scraper-refactor.md).

- **Config is a workbook, applied via `cli sync`.** `config.xlsx` (sheets
  `locations` / `brands` / `coverage`) is the source of truth: the darkstore
  catalog, each tenant's keywords/aliases, and which stores it covers. The `brands`
  sheet also carries per-tenant `keyword_cap` / `brand_cap` (own rows). `cli sync`
  reconciles the DB (upsert; `--dry-run`, `--prune`). `scraper/utils/cities.py` is
  legacy/unreliable and being retired — NOT used by this path.
- **Two complementary scrapes.** `public-run` = the **keyword scrape** (category
  keywords → SoV/rank + competitors, `cap=keyword_cap`, → `search_snapshots` /
  `search_listings`). `public-skus` = the **targeted scrape** (searches the
  tenant's *brand name*, paginates the whole catalog to `brand_cap`, own-only →
  `sku_snapshots`, keyed on `platform_product_id`). Own price/inventory truth comes
  from the targeted scrape; SoV + competitors come from the keyword scrape.
- **The unit is the STORE (`merchant_id`); the coordinate is only the probe.**
  Every product in a search response is stamped with the store that fulfils it
  (`merchant_id`) and the tier it is sold under (`merchant_type`) — read them
  **per product**, never per response. `lat/lon` is where we knock; the response
  says who answered. ⚠️ *Superseded 2026-07-18* — this used to say the unit was the
  location `(lat,lon)` "not the store", which was a reasonable but untested belief.
  See [docs/darkstores.md](docs/darkstores.md) for the evidence that overturned it.
  **The read APIs still aggregate at location grain and have not been migrated yet.**
- **`merchant_type` is a property of the PRODUCT's fulfilment tier, not of the store.**
  Values seen: `express` · `longtail` · `super_longtail` · `dummy` (`unicorn` never
  observed). One store can serve express to its own catchment and longtail to a
  neighbour, and two tiers at once. **Never derive it from a store lookup table.**
- **One coordinate can resolve to several stores** (express + longtail hubs), and
  **one store can answer several coordinates** (when the catalog drifts). So always
  `COUNT(DISTINCT merchant_id)` and take one row per `(store, product)` — raw row
  counts over-report.
- **Reach vs Distribution**: *Reach* = stores where the SKU is listed ÷ stores covered
  (breadth); *Distribution %* = in-stock ÷ listed (in-stock rate). Segment denominators
  **by tier** — ~2059 express stores vs ~510 shared hubs. See
  [docs/public-glossary.md](docs/public-glossary.md).
- **Combos separated from main SKUs.** `is_combo` (on `sku_snapshots` + `search_listings`)
  is derived from `pack_count > 1` (the parsed `unit` string), falling back to a name
  regex only when the unit is unparseable — the name alone missed ~13% of multipacks.
  Combos are stocked selectively, so views filter `?kind=main|combo|all` (default main).
  `keyword_cap`/`brand_cap` live on the `brands` config sheet.
- **Per-unit price** normalizes price across pack sizes (₹/100 ml · 100 g · piece),
  parsed from the `unit` string into `pack_size`/`pack_uom`/`pack_count` on both public
  tables; per-unit price is derived (`price ÷ pack_size`), never stored. All parsing goes
  through `scraper/utils/pack.py` — scraper, staging, loader, backfill and Explorer alike.
  Supersedes the never-populated `grammage` (dropped). **Shipped + backfilled 2026-07-24,
  100% coverage.** See [docs/per-unit-price.md](docs/per-unit-price.md).
- **`sku_map` bridges private↔public** (`item_id` ↔ `platform_product_id`) — different
  Blinkit id systems, no shared UPC, built by name-match (`cli sku-map build`/`apply`).
  Powers the Products page public panel (`/products/{item_id}/public`).
- **Cloudflare** blocks direct httpx (403, TLS fingerprint) even with cookies — must
  fetch via in-page `page.evaluate(fetch(...))` in a real browser session. **One
  session is reused across all locations** by swapping the lat/lon headers (no
  per-location relaunch); ~0.4s/fetch. Retry-with-backoff on transient 403/429/5xx.
- **Storage is per-tenant**: `search_snapshots`/`search_listings` (keyword scrape) +
  `sku_snapshots` (brand scrape). Append-only.
- **⚠️ Public scrapes DO NOT write to Postgres.** They stage to a local SQLite file;
  `cli scrape load` pushes it later in one all-or-nothing transaction. A ~1.5h run no
  longer dies with the database, and the scrape phase needs **zero** DB connections.
  A scraped file sitting unloaded is the new failure mode — `cli scrape staged` lists
  them. See [docs/staging.md](docs/staging.md).
- **Orchestrators**: `scraper/public/orchestrator.py` (keyword, `run_tenant`/`run_all`)
  + `scraper/public/targeted.py` (brand, `run_targeted`/`run_all_targeted`) — worker
  pool (`--workers`), `--resume` continues an interrupted run (reads the staging file,
  so it works even while Supabase is down). The `scrape_jobs` row is created at **load**
  time, not scrape time, so an unloaded run leaves no phantom `running` job.

## CLI (quick ref)

```bash
python -m cli account create --name "Foresight" --admin-email you@foresight.com
python -m cli account add-user --account <account-id> --email teammate@foresight.com [--name "Name"] [--admin]
python -m cli account list

python -m cli tenant create --name "Brand" --account <account-id>
python -m cli tenant list

# Platform auth — no browser, no human (see docs/platform-auth.md)
python -m cli auth platforms                                  # registry + mail-rule status
python -m cli auth credentials set blinkit -t <uuid> --email ops@brand.com [--password]
python -m cli auth credentials set zepto   -t <uuid> --email ops@brand.com --password  # Zepto NEEDS one
python -m cli auth login blinkit -t <uuid> [--manual]         # unattended by default
python -m cli auth login zepto   -t <uuid>                    # same command, any platform
python -m cli auth probe   blinkit -t <uuid>                  # is the session ACTUALLY alive
python -m cli auth refresh blinkit -t <uuid>                  # extend, no email
python -m cli auth refresh-all -t <uuid>                      # what the auth.refresh job runs
python -m cli auth reset   blinkit -t <uuid>                  # clear the circuit breaker
python -m cli auth status  --tenant <uuid>

python -m cli scrape blinkit --tenant <uuid>
python -m cli scrape blinkit-seller --tenant <uuid> [--sales] [--po] [--soh]
python -m cli scrape blinkit-scorecard --tenant <uuid>

python -m cli sync --file config.xlsx [--dry-run] [--prune]   # apply config workbook → DB
python -m cli locations list [--city <slug>] [--tenant <uuid>]
python -m cli watchlist list --tenant <uuid>
python -m cli scrape public-run --tenant <uuid> [--resume] [--city <slug>] [--keyword <kw>] [--cap N]     # keyword scrape: SoV/rank + competitors → STAGING FILE
python -m cli scrape public-skus --tenant <uuid> [--resume] [--city <slug>] [--brand-cap N] [--workers N]  # targeted own-SKU scrape → STAGING FILE

# Public scrapes land in a local SQLite file — push them to Postgres afterwards:
python -m cli scrape staged [--pending]                  # review; Stores/Err flag a bad run
python -m cli scrape load [--all] [--file <ref>] [--dry-run]   # push (one txn per file)
python -m cli scrape discard --file <ref>                # bin a bad run without loading it
python -m cli sku-map build --tenant <uuid> [--file sku_map.xlsx]    # auto-match private item_id ↔ public product_id + export review workbook
python -m cli sku-map apply --tenant <uuid> --file sku_map.xlsx      # apply manual mapping corrections

# ad-hoc single scrape (no config needed; --save requires --tenant)
python -m cli scrape public --keyword "cola" --brand "dobra" --platform blinkit --tenant <uuid> --save

# Explorer — on-demand custom scrape → Excel (agency-facing, ephemeral; any brand/keywords/cities, no tenant)
python -m cli explore --brand "dobra" --keyword "goli soda,nimbu soda" --city bengaluru [--catalog] [--sample N]
```
