"""Pre-flight session check for Zepto's seller scrapes.

Zepto's login is deliberately kept outside `platform_auth/` for now (its
sign-in is a browser flow, not the HTTP flows that package models), so this
is the small piece that lets a scrape refuse to start on a dead session.

Storage and health bookkeeping are NOT reimplemented here — `platform_auth.store`
already owns `platform_sessions`, including status/last_validated_at/
consecutive_failures. This module only decides *when* to call it.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Awaitable, Callable

from platform_auth import store
from scraper.utils.session import load_session


class SessionUnhealthy(Exception):
    """The saved session is missing or the platform rejected it. The caller
    should stop and ask for a fresh login rather than start real scrape work."""


async def ensure_healthy_session(
    db: AsyncSession,
    tenant_id: str,
    platform: str,
    validator: Callable[[dict], Awaitable[tuple[bool, str | None]]],
) -> dict:
    """Load the saved session, probe it, and return it only if the platform
    still accepts it. Raises SessionUnhealthy (never returns None) so a scrape
    fails fast with a clear "re-login required" instead of burning time on a
    session that is already dead."""
    storage_state = await load_session(db, tenant_id, platform)
    if not storage_state:
        raise SessionUnhealthy(
            f"No saved session for tenant={tenant_id} platform={platform} — run the login command first"
        )

    ok, error = await validator(storage_state)
    if ok:
        await store.mark_validated(db, tenant_id, platform)
        return storage_state

    # login_attempt=False: this is a probe finding an expired session, not a
    # failed login. Per store.mark_failed's contract, counting ordinary expiry
    # toward consecutive_failures would make the circuit breaker measure session
    # lifetime rather than whether logging in is broken.
    await store.mark_failed(
        db, tenant_id, platform, error or "validation failed", login_attempt=False
    )
    raise SessionUnhealthy(
        f"Session for tenant={tenant_id} platform={platform} was rejected ({error}) — re-login required"
    )
