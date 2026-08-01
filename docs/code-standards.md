# Code Standards

## Functions, not classes

Write module-level async functions. Pass state explicitly as parameters.

```python
# wrong
class BlinkitScraper:
    def __init__(self, session): self.session = session
    async def scrape(self): ...

# right
async def scrape(session: dict) -> dict: ...
```

Exceptions to this rule: SQLModel `table=True` models in `app/models/`, Pydantic `BaseSettings` in `config.py`.

---

## CSS selectors belong in selectors.py

Every CSS selector, URL path, and DOM identifier used by the Blinkit scraper lives in `scraper/platforms/blinkit/selectors.py`. Never hardcode selector strings anywhere else. When Blinkit changes its DOM, one file changes.

Apply the same pattern when building Instamart/Zepto scrapers — one `selectors.py` per platform.

---

## Raw strings in, parsed values out

`scraper.py` returns raw strings exactly as the platform renders them. `parser.py` cleans and types them. Nothing else touches raw strings.

```python
# scraper.py returns this
{"budget": "₹ 74,341", "roas": "3.14x"}

# parser.py produces this
{"budget": 74341.0, "roas": 3.14}
```

---

## Async everywhere

All I/O is async. No `threading.Thread` for scraper logic. No `time.sleep()` — use `await asyncio.sleep()` when delay is needed.

---

## Logging

```python
from app.utils.logger import logger

logger.debug("...")    # verbose trace — hidden at INFO, surfaced when LOG_LEVEL=DEBUG
logger.info("...")     # normal operational flow
logger.warning("...")  # unexpected but recoverable
logger.error("...")    # failure
```

Never use `print()`. `app/utils/logger.py` configures **one pipeline** for the whole
process: format `HH:MM:SS | LEVEL | tag | message`, sinks = stdout + `logs/app.log`,
verbosity = `settings.LOG_LEVEL` (INFO in prod; DEBUG surfaces the Blinkit-client /
Playwright / httpx play-by-play).

- **Prefer loguru**, but stdlib `logging` (`logging.getLogger(__name__)`) is fine too — an
  `InterceptHandler` routes it into loguru, so third-party libs share the same format. The
  record's module short-name becomes the `tag`.
- **Noisy third-party loggers** (`playwright`, `httpx`, `httpcore`, `asyncio`, `uvicorn.access`)
  are pinned to WARNING — don't fight that; raise `LOG_LEVEL` instead.
- **Tag a run** for correlation with `logger.bind(tag="...")` (e.g. the campaign-manager
  engines bind `tag="cm[<run_id>]"` so every line of one run greps together; the scheduler
  binds `tag="sched"`).
- **Keep the History table (`cm_run_log`) for real actions only** — no-op / "nothing changed"
  narration goes to the log (Cloud Logging), not the DB (D6). High-frequency loops (poll,
  bid `*/15`) would otherwise bury the real changes.

---

## Database patterns

### Session

Every function that reads or writes the database:

```python
async with AsyncSessionLocal() as session:
    result = await session.execute(select(MyModel).where(...))
    rows = result.scalars().all()
```

### Upsert (private data — replace on conflict)

```python
from sqlalchemy.dialects.postgresql import insert

stmt = (
    insert(Model)
    .values(rows)
    .on_conflict_do_update(index_elements=["upsert_key"], set_={...})
)
await session.execute(stmt)
await session.commit()
```

### Public data (append-only — no upsert)

```python
# public data = header + detail, both tagged with tenant_id / job_id
session.add(snapshot)          # SearchSnapshot
await session.flush()          # assign snapshot.id
session.add_all(listings)      # SearchListing rows (FK snapshot_id)
await session.commit()
```

### ensure_refs()

Always call before saving public search data. Satisfies the FK constraints from `search_snapshots`/`search_listings`/`sku_snapshots` to `brands` and `marketplaces`:

```python
from scraper.utils.storage import ensure_refs

await ensure_refs(session, brand_slug="dobra", mp_slug="blinkit")
```

This auto-upserts both rows if they don't exist. No manual seeding needed.

---

## Migrations

After editing any SQLModel table class:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

Never edit the database schema directly in Supabase. All changes go through Alembic so the codebase stays in sync.

---

## Currency parsing

Two formats appear in Blinkit dashboard data — both are handled in `parser.py`:

| Format | Example | How to parse |
|---|---|---|
| Campaign budgets | `"₹ 74,341"` | Strip `₹`, spaces, commas → `float()` |
| Plan budgets | `"Rs. 1,21,500"` | Strip `Rs.`, spaces, commas → `float()` |

Indian number system places commas at thousands, then every 2 digits. `"1,21,500".replace(",", "")` → `"121500"` works correctly for both formats.
