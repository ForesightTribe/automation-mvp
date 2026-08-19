"""The orchestration everything else calls. One entry point, three operations.

    login(db, tenant, platform)          — full login, secret from inbox or human
    ensure(db, tenant, platform)         — load; refresh/re-login only if needed
    refresh_if_possible(...)             — slide the window, no secret at all

**Lazy, never scheduled.** Re-auth fires only when a session is actually dead.
Repeated logins from a single Google-datacenter IP look exactly like a bot, and
both platforms can refresh indefinitely — so the steady state is refresh, and a
real login is the rare exception.

**Serialized per (tenant, platform)** with a Postgres advisory lock. Two jobs
hitting a dead session at once must not both log in: with a shared inbox, two
in-flight OTP requests genuinely cross wires — the second request invalidates the
first's code, and both fail. The lock makes the second caller wait and then find
a fresh session already stored.
"""
import asyncio
import hashlib
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine
from app.utils.logger import logger
from platform_auth import store
from platform_auth.errors import (
    AuthError,
    LoginFailed,
    NoSession,
    SecretNotFound,
    SessionExpired,
)
from platform_auth.inbox import imap as imap_inbox
from platform_auth.inbox import manual as manual_inbox
from platform_auth.registry import get as get_authenticator, wired_slugs
from platform_auth.types import AuthSession, Credentials

# How many times to attempt a full login before giving up. Each attempt requests
# a NEW secret, so this is deliberately small: the common recoverable case is a
# magic link consumed by a mail scanner, which one retry fixes.
MAX_LOGIN_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 5.0

# Circuit breaker. Past this many consecutive failures, stop trying to log in
# automatically and surface it instead. Repeatedly hammering a login endpoint
# from one datacenter IP is how an account gets flagged, and burning OTP quota on
# a broken config helps nobody. Cleared by any success.
MAX_CONSECUTIVE_FAILURES = 3

# Give up waiting for another process's login rather than blocking a scrape for
# ever. Slightly longer than the slowest mail timeout in mail_rules.py.
LOCK_TIMEOUT_SECONDS = 180


def _lock_key(tenant_id: str, platform: str) -> int:
    """A stable 63-bit key for pg_advisory_lock from (tenant, platform)."""
    digest = hashlib.sha256(f"{tenant_id}:{platform}".encode()).digest()
    return int.from_bytes(digest[:8], "big") >> 1


class _AuthLock:
    """Cross-process mutex for one (tenant, platform) login.

    ⚠️ This holds its OWN connection rather than borrowing the caller's session,
    and that is not incidental. `pg_advisory_lock` is scoped to a *connection*.
    An AsyncSession returns its connection to the pool on commit — and this code
    commits several times mid-login — so locking and unlocking through the caller's
    session can land on two different connections. The unlock then silently does
    nothing and the lock leaks onto a pooled connection that never closes,
    permanently wedging that (tenant, platform). Same class of bug as the stale
    `running` jobs that needed a reaper.

    Holding a dedicated connection also gives us free crash recovery: if the
    process dies, the connection drops and Postgres releases the lock.
    """

    def __init__(self, tenant_id: str, platform: str):
        self._key = _lock_key(tenant_id, platform)
        self._conn = None

    async def __aenter__(self):
        self._conn = await engine.connect()
        # Bound the wait so a hung login can't block every other caller for ever.
        await self._conn.execute(
            text(f"SET lock_timeout = '{LOCK_TIMEOUT_SECONDS}s'")
        )
        await self._conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": self._key})
        return self

    async def __aexit__(self, *exc):
        try:
            await self._conn.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": self._key}
            )
        finally:
            # Closing is the real guarantee — it releases the lock even if the
            # unlock statement itself failed.
            await self._conn.close()
            self._conn = None


async def resolve_credentials(
    db: AsyncSession,
    tenant_id: str,
    platform: str,
    *,
    email: str | None = None,
    password: str | None = None,
) -> Credentials:
    """Stored credentials, with any explicit overrides applied.

    Raises rather than guessing: a login that silently proceeds without the
    password a platform requires fails later, in a way that looks like the
    platform's fault.
    """
    auth = get_authenticator(platform)
    stored = await store.get_credentials(db, tenant_id, platform)

    address = email or (stored.email if stored else None)
    if not address:
        raise LoginFailed(
            f"No credentials stored for {platform}. Run: "
            f"python -m cli auth credentials set {platform} -t {tenant_id} --email <address>"
        )

    secret = password or (stored.password if stored else None)
    if auth.needs_password and not secret:
        raise LoginFailed(
            f"{auth.name} requires a password and none is stored. Run: "
            f"python -m cli auth credentials set {platform} -t {tenant_id} "
            f"--email {address} --password"
        )

    return Credentials(
        email=address,
        password=secret,
        extra=(stored.extra if stored else {}) or {},
    )


async def login(
    db: AsyncSession,
    tenant_id: str,
    platform: str,
    *,
    email: str | None = None,
    password: str | None = None,
    auto: bool = True,
    timeout: float | None = None,
    remember: bool = True,
) -> AuthSession:
    """Run a full login and store the result.

    `auto` reads the secret from the forwarding mailbox; otherwise a human is
    prompted. The first login for a tenant is normally manual — it is the moment
    most likely to hit something unexpected, and `remember` persists the
    credentials so every later login can run unattended.
    """
    auth = get_authenticator(platform)

    if not settings.AUTH_ALLOW_LOGIN:
        raise LoginFailed(
            f"{platform}: logins are disabled in this process (AUTH_ALLOW_LOGIN=false). "
            "Platform logins must run on the scraper VM — enqueue an auth.refresh job "
            "or run `cli auth login` there."
        )

    credentials = await resolve_credentials(
        db, tenant_id, platform, email=email, password=password
    )
    if remember:
        await store.save_credentials(db, tenant_id, platform, credentials)

    if auto:
        await _check_circuit_breaker(db, tenant_id, platform)

    async with _AuthLock(tenant_id, platform):
        last_error: Exception | None = None

        for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
            try:
                logger.info(
                    f"Requesting {auth.secret_kind.value} for {platform} "
                    f"({credentials.email}) — attempt {attempt}/{MAX_LOGIN_ATTEMPTS}"
                )
                challenge = await auth.start_login(credentials)

                secret = (
                    await imap_inbox.get_secret(challenge, timeout=timeout)
                    if auto
                    else await manual_inbox.get_secret(challenge)
                )
                session = await auth.complete_login(challenge, secret)

            except AuthError as e:
                last_error = e
                # A human at a terminal shouldn't be silently re-prompted, and a
                # config error (no password stored) won't fix itself on a retry.
                if not auto or not _is_retryable(e) or attempt == MAX_LOGIN_ATTEMPTS:
                    break
                logger.warning(
                    f"{auth.name}: attempt {attempt} failed ({e}) — retrying in "
                    f"{RETRY_BACKOFF_SECONDS:.0f}s with a fresh secret"
                )
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                continue

            await store.save(db, tenant_id, session)   # clears the failure count
            logger.info(f"{auth.name}: login successful")
            return session

    # Every failure path lands here, so the counter can never drift. The earlier
    # version only recorded SecretNotFound, which left a login that failed at the
    # token-exchange step invisible to anything built on consecutive_failures.
    await store.mark_failed(db, tenant_id, platform, str(last_error))
    raise last_error


def _is_retryable(error: Exception) -> bool:
    """Would a second attempt plausibly succeed?

    Retryable, because a fresh secret is genuinely likely to work:
      - SecretNotFound — mail delayed past the window, or forwarding lagged
      - a consumed/expired code — a mail scanner opened the single-use magic
        link before we did, which is a real and recurring hazard

    Not retryable — another attempt just burns a second secret:
      - no credentials stored, or a password is required (config, not luck)
      - the address is not a real user on that platform
    """
    if isinstance(error, SecretNotFound):
        return True
    if isinstance(error, LoginFailed):
        detail = str(error).lower()
        if any(s in detail for s in ("no credentials", "requires a password")):
            return False
        if "no user corresponding" in detail:
            return False
        return any(
            s in detail
            for s in ("expired_oob_code", "invalid_oob_code", "expired", "invalid code")
        )
    return False


async def _check_circuit_breaker(db: AsyncSession, tenant_id: str, platform: str) -> None:
    """Refuse to auto-login when it has already failed repeatedly.

    Auto-login that quietly fails forever is worse than the manual state it
    replaced: it hammers a login endpoint from one datacenter IP, burns OTP
    quota, and buries a broken config in noise. Any successful login clears it.
    """
    rows = await store.all_for_tenant(db, tenant_id)
    row = next((r for r in rows if r["platform"] == platform), None)
    if row and row["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
        raise LoginFailed(
            f"{platform}: auto-login suspended after {row['consecutive_failures']} "
            f"consecutive failures (last: {row['last_error']}). Fix the cause, then "
            f"run: python -m cli auth login {platform} -t {tenant_id} --manual"
        )


async def refresh_all(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    """Refresh every stored session for a tenant. The scheduled upkeep path.

    ⚠️ **Skips any platform whose tenant has a job running.** Seller rotation
    ISSUES A NEW TOKEN AND KILLS THE OLD ONE (verified 2026-08-04: the previous
    access token returns 401 "Access token not authenticated" immediately after
    rotate). Lanes run in parallel, so a refresh firing while a seller scrape is
    mid-flight would break that scrape — and scheduling this at a quiet hour is
    not a guarantee, it is a hope that nobody adds a conflicting schedule later.

    Skipping is safe: refresh is preventive and runs daily, so missing one day
    costs nothing. The session still has days of life, and `ensure()` would
    recover it regardless.
    """
    from sqlalchemy import func, select as sa_select

    from app.models.job import Job, JobStatus

    results: dict[str, str] = {}

    busy = await db.execute(
        sa_select(func.count())
        .select_from(Job)
        .where(
            Job.tenant_id == uuid.UUID(tenant_id),
            Job.status.in_([JobStatus.running, JobStatus.pending]),
            Job.job_type != "auth.refresh",
        )
    )
    if busy.scalar_one() > 0:
        logger.warning(
            f"tenant {tenant_id}: other jobs are active — skipping refresh so a "
            "token rotation cannot invalidate a running scrape's session"
        )
        return {p: "skipped_busy" for p in wired_slugs()}

    for platform in wired_slugs():
        if await store.load(db, tenant_id, platform) is None:
            results[platform] = "no_session"
            continue
        try:
            session = await refresh_if_possible(db, tenant_id, platform)
            results[platform] = "refreshed" if session else "not_refreshable"
        except AuthError as e:
            # Never fatal: the session may still be fine, and ensure() will fix it
            # on next use. A failed refresh must not fail the job and page someone.
            logger.warning(f"{platform}: refresh failed ({e})")
            results[platform] = "failed"
    return results


async def refresh_if_possible(
    db: AsyncSession, tenant_id: str, platform: str
) -> AuthSession | None:
    """Extend a stored session without any email. None if it can't be extended."""
    auth = get_authenticator(platform)
    if not auth.refreshable or auth.refresh is None:
        return None

    session = await store.load(db, tenant_id, platform)
    if session is None:
        return None

    refreshed = await auth.refresh(session)
    if refreshed is None:
        return None

    # Carry the address forward: legacy rows have no email inside the envelope.
    refreshed.email = refreshed.email or session.email or (
        await store.login_email(db, tenant_id, platform) or ""
    )
    await store.save(db, tenant_id, refreshed)
    logger.info(f"{auth.name}: session refreshed (no login needed)")
    return refreshed


async def ensure(
    db: AsyncSession,
    tenant_id: str,
    platform: str,
    *,
    auto_login: bool = True,
) -> AuthSession:
    """Return a session that is known good, doing the least work necessary.

    Ladder: stored session that probes clean -> refresh -> full login. Each rung
    costs more, so we only climb when the one below fails.
    """
    auth = get_authenticator(platform)

    session = await store.load(db, tenant_id, platform)
    if session is not None:
        if auth.probe is None or await auth.probe(session):
            await store.mark_validated(db, tenant_id, platform)
            return session
        logger.warning(f"{auth.name}: stored session failed its probe")

    async with _AuthLock(tenant_id, platform):
        # Another caller may have fixed it while we waited for the lock.
        session = await store.load(db, tenant_id, platform)
        if session is not None and auth.probe is not None and await auth.probe(session):
            return session

        if session is not None:
            refreshed = await refresh_if_possible(db, tenant_id, platform)
            if refreshed is not None:
                return refreshed

    if not auto_login:
        if session is None:
            raise NoSession(platform, tenant_id)
        # Not a login failure — no login was attempted. Must not feed the breaker.
        await store.mark_failed(
            db, tenant_id, platform, "expired, auto-login disabled", login_attempt=False
        )
        raise SessionExpired(platform, "auto-login disabled")

    return await login(db, tenant_id, platform, auto=True)


async def probe(db: AsyncSession, tenant_id: str, platform: str) -> bool:
    """Check liveness and record the verdict. Cheap — no browser on either platform."""
    auth = get_authenticator(platform)
    session = await store.load(db, tenant_id, platform)
    if session is None:
        return False

    alive = auth.probe is None or await auth.probe(session)
    if alive:
        await store.mark_validated(db, tenant_id, platform)
    else:
        # A session reaching its expiry is normal, not a sign auto-login is
        # broken — record the state, leave the breaker alone.
        await store.mark_failed(
            db, tenant_id, platform, "probe failed", login_attempt=False
        )
    return alive
