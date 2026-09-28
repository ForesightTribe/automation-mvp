"""In-process result cache for expensive read-only queries.

⚠️ Three limits, each load-bearing:

  - It lives in the worker's memory. Two API workers keep two copies and a
    restart empties both — fine here, because every cached value comes from a
    scrape rather than from something a user just wrote.
  - READ-ONLY analytics only. Anything reflecting a write must not go through
    it, or a user will act and see their own change ignored.
  - The AsyncSession is never part of the key: sessions are per-request and
    unhashable. The tenant and the window identify a result.

For aggregates over the scrape tables, whose cost is measured in seconds while
the scrape behind them lands days apart.
"""
import asyncio
import functools
import time
from typing import Any

# key -> (expires_at, value). Bounded so a wide date-range picker cannot grow it
# without limit.
_store: dict[Any, tuple[float, Any]] = {}
_MAX_ENTRIES = 256


def _key(fn, args, kwargs) -> tuple:
    """Everything that identifies the answer, minus the database session."""
    from sqlalchemy.ext.asyncio import AsyncSession

    parts = [fn.__module__, fn.__qualname__]
    parts += [repr(a) for a in args if not isinstance(a, AsyncSession)]
    parts += [
        f"{k}={v!r}"
        for k, v in sorted(kwargs.items())
        if not isinstance(v, AsyncSession)
    ]
    return tuple(parts)


def ttl_cache(seconds: int):
    """Cache an async function's result for `seconds`.

    Errors are never cached — a failed scrape read should be retried, not
    remembered.
    """

    def wrap(fn):
        lock = asyncio.Lock()

        @functools.wraps(fn)
        async def inner(*args, **kwargs):
            key = _key(fn, args, kwargs)
            now = time.monotonic()
            hit = _store.get(key)
            if hit and hit[0] > now:
                return hit[1]
            # One caller computes; the rest wait and take the result rather than
            # all running the same 20-second query at once.
            async with lock:
                hit = _store.get(key)
                if hit and hit[0] > time.monotonic():
                    return hit[1]
                value = await fn(*args, **kwargs)
                if len(_store) >= _MAX_ENTRIES:
                    oldest = min(_store, key=lambda k: _store[k][0])
                    _store.pop(oldest, None)
                _store[key] = (time.monotonic() + seconds, value)
                return value

        inner.cache_clear = _store.clear
        return inner

    return wrap
