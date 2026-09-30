"""In-process result cache for expensive read-only queries.

⚠️ Three limits, each load-bearing:

  - It lives in the worker's memory. Two API workers keep two copies and a
    restart empties both — fine here, because every cached value comes from a
    scrape rather than from something a user just wrote.
  - READ-ONLY analytics only. Anything reflecting a write must not go through
    it, or a user will act and see their own change ignored.
  - The AsyncSession is never part of the key: sessions are per-request and
    unhashable. The tenant and the window identify a result.
  - NOT RE-ENTRANT. One caller computes while the rest wait on a per-function
    lock, so a function that calls ITSELF (`po_service.insights_summary` asks
    itself for the previous window) deadlocks on its own lock. Cache its
    caller instead.

For aggregates over the scrape tables, whose cost is measured in seconds while
the scrape behind them lands days apart.
"""
import asyncio
import functools
import inspect
import time
from typing import Any

# key -> (expires_at, value). Bounded so a wide date-range picker cannot grow it
# without limit.
_store: dict[Any, tuple[float, Any]] = {}
_MAX_ENTRIES = 256


def _key(fn, args, kwargs, sig=None) -> tuple:
    """Everything that identifies the answer, minus the database session.

    ⚠️ Arguments are bound to the signature and defaults filled in, so a caller
    that omits `kind="main"` and one that passes it land on the SAME entry.
    Without that, a warm-up relying on defaults fills keys no route ever reads.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    if sig is not None:
        try:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            args, kwargs = (), dict(bound.arguments)
        except TypeError:
            pass

    def norm(v):
        # The session is dropped wherever it appears, not just at the top
        # level: a wrapper taking *args hands it back inside a tuple, and a
        # per-request object in the key means every call is a miss.
        if isinstance(v, AsyncSession):
            return None
        # A filter list means the same thing in any order, and two callers
        # passing the same marketplaces differently must share one entry.
        if isinstance(v, (list, set)):
            return tuple(sorted(repr(norm(x)) for x in v))
        if isinstance(v, tuple):
            return tuple(norm(x) for x in v if not isinstance(x, AsyncSession))
        if isinstance(v, dict):
            return tuple(
                (k, norm(x))
                for k, x in sorted(v.items())
                if not isinstance(x, AsyncSession)
            )
        return repr(v)

    parts = [fn.__module__, fn.__qualname__]
    parts += [repr(norm(a)) for a in args if not isinstance(a, AsyncSession)]
    parts += [
        f"{k}={norm(v)!r}"
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
        sig = inspect.signature(fn)
        # ⚠️ One lock PER KEY, not per function. A single lock would make two
        # callers asking for DIFFERENT windows queue behind each other, which on
        # a page that fires a dozen requests at once turns parallel work back
        # into a sequence.
        locks: dict[Any, asyncio.Lock] = {}

        @functools.wraps(fn)
        async def inner(*args, **kwargs):
            key = _key(fn, args, kwargs, sig)
            now = time.monotonic()
            hit = _store.get(key)
            if hit and hit[0] > now:
                return hit[1]
            lock = locks.get(key)
            if lock is None:
                lock = locks.setdefault(key, asyncio.Lock())
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
                # The key is cached now, so anyone arriving later reads it
                # without the lock; keeping it would grow this dict forever.
                if len(locks) > _MAX_ENTRIES:
                    locks.clear()
                return value

        inner.cache_clear = _store.clear
        return inner

    return wrap
