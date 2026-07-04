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
| [docs/public-scraper-refactor.md](docs/public-scraper-refactor.md) | Working plan — per-tenant public scraper refactor (header+detail storage, orchestrator, phases, open questions) |

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

- **Runtime**: Python 3.12+, fully async/await
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
- **Location = lat/lon, not pincode.** Blinkit picks the dark store from the
  lat/lon request headers. `marketplace_locations` is keyed on `merchant_id`;
  pincode/zone are best-effort metadata.
- **Cloudflare** blocks direct httpx (403, TLS fingerprint) even with cookies — must
  fetch via in-page `page.evaluate(fetch(...))` in a real browser session. **One
  session is reused across all stores** by swapping the lat/lon headers (no
  per-store relaunch); ~0.4s/fetch. Retry-with-backoff on transient 403/429/5xx.
- **Storage is per-tenant header+detail**: `search_snapshots` (rank/SoV per search)
  + `search_listings` (per product: brand, price, mrp, discount, stock). Append-only.
- **Orchestrator**: `scraper/public/orchestrator.py` (`run_tenant`/`run_all`) —
  driven by watchlist + `tenant_locations`, one `scrape_job` per run, `--resume`
  continues an interrupted job (skips already-scraped stores).

## CLI (quick ref)

```bash
python -m cli account create --name "Foresight" --admin-email you@foresight.com
python -m cli account add-user --account <account-id> --email teammate@foresight.com [--name "Name"] [--admin]
python -m cli account list

python -m cli tenant create --name "Brand" --account <account-id>
python -m cli tenant list

python -m cli auth blinkit --tenant <uuid>
python -m cli auth blinkit-seller --tenant <uuid>
python -m cli auth status --tenant <uuid>

python -m cli scrape blinkit --tenant <uuid>
python -m cli scrape blinkit-seller --tenant <uuid> [--sales] [--po] [--soh]
python -m cli scrape blinkit-scorecard --tenant <uuid>

python -m cli sync --file config.xlsx [--dry-run] [--prune]   # apply config workbook → DB
python -m cli locations list [--city <slug>] [--tenant <uuid>]
python -m cli watchlist list --tenant <uuid>
python -m cli scrape public-run --tenant <uuid> [--resume] [--city <slug>] [--keyword <kw>] [--cap N]     # keyword scrape: SoV/rank + competitors
python -m cli scrape public-skus --tenant <uuid> [--resume] [--city <slug>] [--brand-cap N] [--workers N]  # targeted own-SKU scrape → sku_snapshots

# ad-hoc single scrape (no config needed; --save requires --tenant)
python -m cli scrape public --keyword "cola" --brand "dobra" --platform blinkit --tenant <uuid> --save
```
