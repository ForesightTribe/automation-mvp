"""Zepto ads reads — guards on the traps in backend/docs/zepto/database.md.

P40 (2026-10-07): `zepto_ad_breakdown_daily` stacks three views of the SAME money
(`dimension` = category | city | page), so a sum that does not pick one view reports ~3×
the real spend. Its one reader, `zepto_ads.breakdown`, must always filter on it.

No database: the session records the SQL and answers empty.

    python -m pytest app/tests/test_zepto_ads.py
"""
import asyncio
import inspect
import uuid
from datetime import date

from sqlalchemy.dialects import postgresql

from app.services import zepto_ads

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")


class _Empty:
    def all(self):
        return []


class _Recorder:
    def __init__(self):
        self.sql: list[str] = []

    async def execute(self, stmt, *_a, **_k):
        self.sql.append(str(stmt.compile(dialect=postgresql.dialect(),
                                         compile_kwargs={"literal_binds": True})))
        return _Empty()


def test_breakdown_always_picks_one_view():
    for dim in ("category", "city", "page"):
        s = _Recorder()
        asyncio.run(zepto_ads.breakdown(s, tenant_id=TENANT, start=date(2026, 10, 1),
                                        end=date(2026, 10, 6), dimension=dim))
        (sql,) = s.sql
        where = sql.split("WHERE", 1)[1]
        assert f"zepto_ad_breakdown_daily.dimension = '{dim}'" in where, sql


def test_breakdown_has_no_default_view_to_forget():
    """A default would let a caller sum all three views without noticing."""
    param = inspect.signature(zepto_ads.breakdown).parameters["dimension"]
    assert param.default is inspect.Parameter.empty
