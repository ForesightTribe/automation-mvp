"""In-process rate limiting for the login endpoint.

⚠️ PER PROCESS, deliberately. Render runs the API as a single worker, so one
counter sees every attempt. Add a second worker (or a second instance) and each
keeps its own, multiplying the effective limit by the worker count — at that
point this needs to move to Redis. The limits below are low enough that even
2-3× remains a meaningful bound.

Only FAILED attempts are counted. Someone with several tabs open, or a flaky
network retrying a good password, must never lock themselves out.
"""
import time
from collections import defaultdict

from app.utils.logger import logger

# Keyed by (bucket, identity) -> failure timestamps inside the window.
_fails: dict[tuple[str, str], list[float]] = defaultdict(list)

# Stop the dict growing without bound under a spray attack across many
# identities. Well above any real traffic, so a sweep means something is wrong.
_MAX_KEYS = 10_000


def _sweep(now: float, window: float) -> None:
    for k in [k for k, v in _fails.items() if not v or now - v[-1] > window]:
        _fails.pop(k, None)


def check(bucket: str, identity: str, limit: int, window: float) -> float | None:
    """Seconds the caller must wait, or None if the attempt may proceed.

    Read-only — a blocked attempt does not extend its own lockout, so hammering
    a locked account cannot keep it locked forever.
    """
    if not identity:
        return None
    now = time.monotonic()
    hits = _fails[(bucket, identity)] = [
        t for t in _fails[(bucket, identity)] if now - t < window
    ]
    if len(hits) < limit:
        return None
    return max(0.0, window - (now - hits[0]))


def record_failure(bucket: str, identity: str, window: float) -> None:
    if not identity:
        return
    now = time.monotonic()
    if len(_fails) > _MAX_KEYS:
        _sweep(now, window)
        logger.warning("login rate limiter swept {} keys", len(_fails))
    _fails[(bucket, identity)].append(now)


def clear(bucket: str, identity: str) -> None:
    """Forget an identity's failures — called on a successful login."""
    _fails.pop((bucket, identity), None)


def client_ip(request) -> str:
    """The caller's address as well as we can know it behind Cloudflare+Render.

    ⚠️ Spoofable if anyone reaches the origin directly: `CF-Connecting-IP` is
    overwritten by Cloudflare for traffic through it, but a request straight to
    Render carries whatever header the client set. The per-EMAIL limit is the
    one that cannot be evaded this way, because it keys on the request body;
    treat the IP limit as the wider net, not the wall.
    """
    h = request.headers
    cf = h.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    fwd = h.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""
