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
| [docs/ui-rules.md](docs/ui-rules.md) | Frontend rules (TBD) |

---

## Stack (quick ref)

- **Runtime**: Python 3.12+, fully async/await
- **API**: FastAPI + Uvicorn
- **Database**: PostgreSQL via Supabase — SQLModel, asyncpg, Alembic
- **Browser**: Playwright (Chromium)
- **Encryption**: Fernet (`cryptography`)
- **Logging**: loguru — `from app.utils.logger import logger`, never `print()`
- **CLI**: typer + rich

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
Clients. The JWT carries `account_id`; the active client is chosen per-request
(`/api/clients/{client_id}/...`) and access-checked against the account.

See [docs/api-reference.md](docs/api-reference.md) for the full surface.

## Seeding

- `brands` and `marketplaces` are auto-upserted by `ensure_refs()` — no manual seeding for public scrapers.
- A `tenants` row (Client) now belongs to an **Account**. Create the account + its
  first admin login, then the client under it:
  ```bash
  python -m cli account create --name "Foresight" --admin-email you@foresight.com
  python -m cli tenant create --name "Dobra" --account <account-id>
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

- Location data comes entirely from `scraper/utils/cities.py` — hardcoded dict, no external geocoding.
- Blinkit's API is Cloudflare-protected — direct `httpx` always returns 403. Use in-page `page.evaluate(fetch(...))` instead. See `scraper/platforms/blinkit/public_data/scraper.py` for the reference implementation.
- Instamart and Zepto public scrapers are pending — they need the same Playwright treatment.

## CLI (quick ref)

```bash
python -m cli account create --name "Foresight" --admin-email you@foresight.com
python -m cli account list

python -m cli tenant create --name "Brand" --account <account-id>
python -m cli tenant list

python -m cli auth blinkit --tenant <uuid>
python -m cli auth blinkit-seller --tenant <uuid>
python -m cli auth status --tenant <uuid>

python -m cli scrape blinkit --tenant <uuid>
python -m cli scrape blinkit-seller --tenant <uuid> [--sales] [--po] [--soh]
python -m cli scrape blinkit-scorecard --tenant <uuid>

python -m cli scrape public --keyword "cola" --brand "dobra" --platform blinkit [--save]
python -m cli scrape public --keyword "cola" --brand "dobra" --city mumbai --all-zones
```
