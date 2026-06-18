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

logger.debug("...")    # verbose trace
logger.info("...")     # normal operational flow
logger.warning("...")  # unexpected but recoverable
logger.error("...")    # failure
```

Never use `print()`. Loguru writes to stdout and `logs/app.log`.

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
session.add(SearchResult(...))
await session.commit()
```

### ensure_refs()

Always call before saving public search data. Satisfies the FK constraints from `search_results` to `brands` and `marketplaces`:

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
