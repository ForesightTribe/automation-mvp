"""How a dashboard scrape logs — the standard (2026-10-06, Zepto + Blinkit).

    zepto-cm-exp/plans/PLAN-private-scrape.md §8b (P52). Level chosen by Deepansh: "Steps".

A run reads as a short story a person can follow, not a transcript of every request:

    10:30:02 INFO  | zepto·brik-oven        | start · sales, po, ads
    10:30:40 INFO  | zepto·brik-oven·sales  | products · 8 days · 64 rows
    10:31:40 INFO  | zepto·brik-oven·sales  | done · saved 90 rows
    10:34:30 INFO  | zepto·brik-oven·ads    | 09-29 · 28 campaigns · ₹324
    10:41:12 INFO  | zepto·brik-oven        | finished · ok · 11m10s

* **INFO** = one line per STEP: a sub-fetch, a day of ads, a section's summary, start and
  finish. **WARNING** = something a person should look at that did NOT recover.
  **ERROR** = something that fails the run. Everything per-request — each page, each
  retry that worked, each WAF re-mint — is **DEBUG** (`LOG_LEVEL=DEBUG` brings it back),
  and recoveries are COUNTED into the section's summary instead.
* **Every line says where it is from**: a tag `<marketplace>·<tenant>·<section>`, set
  once with `tag(...)` — loguru's contextualize, so every logger call underneath (the
  scraper modules included) carries it without being handed a logger.
* **One writer**: no spinners, no printed tables. A scrape's output is its log.

Alerting does not depend on any of this: it fires on the runner's own ERROR when a job
exits non-zero (deploy/ops-agent-logging.yaml), so quieter scraper lines cannot hide a
failure.
"""
import re
import time
import uuid
from contextlib import contextmanager

from loguru import logger
from sqlmodel import select

from app.models.tenant import Tenant


@contextmanager
def tag(*parts: str):
    """Every log line inside the block carries the tag `part·part·part`."""
    with logger.contextualize(tag="·".join(p for p in parts if p)):
        yield


async def tenant_slug(db, tenant_id: str) -> str:
    """Short readable tenant name for the tag — "Brik Oven" -> "brik-oven". Falls back to
    the first 8 characters of the id, so a lookup failure never stops a scrape."""
    try:
        name = (await db.execute(
            select(Tenant.name).where(Tenant.id == uuid.UUID(str(tenant_id)))
        )).scalar()
    except Exception:
        name = None
    if not name:
        return str(tenant_id)[:8]
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or str(tenant_id)[:8]


def took(started: float) -> str:
    """'11m10s' / '42s' since `started` (a time.monotonic() reading)."""
    s = int(time.monotonic() - started)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def rupees(v: float | int | None) -> str:
    return f"₹{(v or 0):,.0f}"


def short(items: list[str], n: int = 5) -> str:
    return ", ".join(items[:n]) + (f" (+{len(items) - n} more)" if len(items) > n else "")
