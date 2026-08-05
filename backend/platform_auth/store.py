"""Encrypted persistence for platform sessions.

Moved here from `scraper/utils/session.py` — the campaign manager and the API
depend on sessions too, so living under `scraper/` was always a misfiling. That
module is now a thin re-export, so existing imports keep working.

Two things this adds beyond the old save/load pair:

**An envelope.** A session is no longer just a Playwright storage_state; it is a
native credential plus projections (see types.AuthSession). Rows written before
this module hold a bare storage_state and are read as legacy — no backfill needed.

**Honest status.** `platform_sessions` previously recorded only "a row exists",
so `cli auth status` reported a session that died four days ago as present. That
is exactly how the seller scrape failed silently from 2026-07-21. Status,
last_validated_at and consecutive_failures make expiry visible without launching
a browser.
"""
import json
import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.job import PlatformCredential, PlatformSession
from app.utils.encryption import decrypt, encrypt
from app.utils.logger import logger
from app.utils.time import now_ist
from platform_auth.types import AuthSession, Credentials

# platform_sessions.status
STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_UNKNOWN = "unknown"


async def _row(db: AsyncSession, tenant_id: str, platform: str) -> PlatformSession | None:
    result = await db.execute(
        select(PlatformSession).where(
            PlatformSession.tenant_id == uuid.UUID(tenant_id),
            PlatformSession.platform == platform,
        )
    )
    return result.scalars().first()


async def save(db: AsyncSession, tenant_id: str, session: AuthSession) -> None:
    """Upsert a freshly-obtained session and mark it active."""
    now = now_ist()
    encrypted = encrypt(json.dumps(session.to_envelope()))
    stmt = (
        insert(PlatformSession)
        .values(
            tenant_id=uuid.UUID(tenant_id),
            platform=session.platform,
            encrypted_session=encrypted,
            status=STATUS_ACTIVE,
            last_login_at=now,
            last_validated_at=now,
            consecutive_failures=0,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "platform"],
            set_={
                "encrypted_session": encrypted,
                "status": STATUS_ACTIVE,
                "last_login_at": now,
                "last_validated_at": now,
                "consecutive_failures": 0,
                "last_error": None,
                "updated_at": now,
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
    logger.info(f"Session saved: tenant={tenant_id} platform={session.platform}")


async def load(db: AsyncSession, tenant_id: str, platform: str) -> AuthSession | None:
    row = await _row(db, tenant_id, platform)
    if not row:
        return None
    data = json.loads(decrypt(row.encrypted_session))
    if data.get("__v") != 2:
        # Legacy row: the stored blob IS the storage_state. Stamp the platform so
        # the authenticator can still recover credentials out of it.
        data = dict(data)
        data["__legacy_platform"] = platform
    session = AuthSession.from_envelope(data)
    if not session.platform:
        session.platform = platform
    if not session.email:
        creds = await get_credentials(db, tenant_id, platform)
        if creds:
            session.email = creds.email
    return session


# ── Credentials — the login INPUT ─────────────────────────────────────────────


async def _cred_row(
    db: AsyncSession, tenant_id: str, platform: str
) -> PlatformCredential | None:
    result = await db.execute(
        select(PlatformCredential).where(
            PlatformCredential.tenant_id == uuid.UUID(tenant_id),
            PlatformCredential.platform == platform,
        )
    )
    return result.scalars().first()


async def save_credentials(
    db: AsyncSession, tenant_id: str, platform: str, credentials: Credentials
) -> None:
    """Store what this tenant needs to log in. The password is encrypted at rest."""
    now = now_ist()
    encrypted_password = (
        encrypt(credentials.password) if credentials.password else None
    )
    values = {
        "tenant_id": uuid.UUID(tenant_id),
        "platform": platform,
        "login_email": credentials.email,
        "encrypted_password": encrypted_password,
        "extra": json.dumps(credentials.extra) if credentials.extra else None,
        "created_at": now,
        "updated_at": now,
    }
    update = {k: v for k, v in values.items() if k not in ("tenant_id", "platform", "created_at")}
    # Never blank an existing password just because this call omitted one — the
    # common case is updating only the address.
    if encrypted_password is None:
        update.pop("encrypted_password")

    await db.execute(
        insert(PlatformCredential)
        .values(**values)
        .on_conflict_do_update(index_elements=["tenant_id", "platform"], set_=update)
    )
    await db.commit()
    logger.info(
        f"Credentials saved: tenant={tenant_id} platform={platform} "
        f"({credentials.redacted()})"
    )


async def get_credentials(
    db: AsyncSession, tenant_id: str, platform: str
) -> Credentials | None:
    row = await _cred_row(db, tenant_id, platform)
    if not row:
        return None
    return Credentials(
        email=row.login_email,
        password=decrypt(row.encrypted_password) if row.encrypted_password else None,
        extra=json.loads(row.extra) if row.extra else {},
    )


async def delete_credentials(db: AsyncSession, tenant_id: str, platform: str) -> bool:
    row = await _cred_row(db, tenant_id, platform)
    if not row:
        return False
    await db.delete(row)
    await db.commit()
    logger.info(f"Credentials deleted: tenant={tenant_id} platform={platform}")
    return True


async def credentials_for_tenant(db: AsyncSession, tenant_id: str) -> list[dict]:
    """Listing view — never returns the password itself."""
    result = await db.execute(
        select(PlatformCredential)
        .where(PlatformCredential.tenant_id == uuid.UUID(tenant_id))
        .order_by(PlatformCredential.platform)
    )
    return [
        {
            "platform": r.platform,
            "login_email": r.login_email,
            "has_password": r.encrypted_password is not None,
            "updated_at": r.updated_at,
        }
        for r in result.scalars().all()
    ]


async def login_email(db: AsyncSession, tenant_id: str, platform: str) -> str | None:
    creds = await get_credentials(db, tenant_id, platform)
    return creds.email if creds else None


async def mark_validated(db: AsyncSession, tenant_id: str, platform: str) -> None:
    row = await _row(db, tenant_id, platform)
    if not row:
        return
    row.status = STATUS_ACTIVE
    row.last_validated_at = now_ist()
    row.consecutive_failures = 0
    row.last_error = None
    row.updated_at = now_ist()
    db.add(row)
    await db.commit()


async def mark_failed(
    db: AsyncSession,
    tenant_id: str,
    platform: str,
    error: str,
    *,
    login_attempt: bool = True,
) -> None:
    """Record a failure without destroying the session.

    The credential is kept: most failures are transient, and throwing away a
    session that might still work turns a blip into a mandatory re-login.

    ⚠️ `login_attempt=False` for anything that is NOT a failed login — a probe
    finding an expired session, or `ensure(auto_login=False)` declining to fix
    one. Those are **normal**: sessions expire on a timer by design. Counting
    them toward `consecutive_failures` makes the circuit breaker measure session
    lifetime instead of auto-login health, and three ordinary expiries over three
    weeks would then disable auto-login permanently. The counter must answer only
    "is logging in broken?".
    """
    row = await _row(db, tenant_id, platform)
    if not row:
        return
    row.status = STATUS_EXPIRED
    if login_attempt:
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
    row.last_error = error[:500]
    row.updated_at = now_ist()
    db.add(row)
    await db.commit()


async def clear_failures(db: AsyncSession, tenant_id: str, platform: str) -> bool:
    """Reset the circuit breaker after a human has fixed the cause."""
    row = await _row(db, tenant_id, platform)
    if not row:
        return False
    row.consecutive_failures = 0
    row.last_error = None
    row.updated_at = now_ist()
    db.add(row)
    await db.commit()
    logger.info(f"Failure count reset: tenant={tenant_id} platform={platform}")
    return True


async def all_for_tenant(db: AsyncSession, tenant_id: str) -> list[dict]:
    """Session health per platform, with the login address joined in."""
    result = await db.execute(
        select(PlatformSession)
        .where(PlatformSession.tenant_id == uuid.UUID(tenant_id))
        .order_by(PlatformSession.platform)
    )
    rows = result.scalars().all()
    creds = {c["platform"]: c for c in await credentials_for_tenant(db, tenant_id)}
    return [
        {
            "platform": r.platform,
            "login_email": (creds.get(r.platform) or {}).get("login_email"),
            "status": r.status or STATUS_UNKNOWN,
            "last_login_at": r.last_login_at,
            "last_validated_at": r.last_validated_at,
            "consecutive_failures": r.consecutive_failures or 0,
            "last_error": r.last_error,
        }
        for r in rows
    ]


# ── Backwards-compatible surface ──────────────────────────────────────────────
# Six call sites still speak storage_state (cli/commands/scrape.py, the campaign
# manager client, ads_service). They keep working unchanged; `scraper/utils/
# session.py` re-exports these three names.


async def save_session(
    db: AsyncSession, tenant_id: str, platform: str, storage_state: dict
) -> None:
    await save(
        db,
        tenant_id,
        AuthSession(platform=platform, email="", raw={}, storage_state=storage_state),
    )


async def load_session(db: AsyncSession, tenant_id: str, platform: str) -> dict | None:
    session = await load(db, tenant_id, platform)
    if session is None:
        logger.warning(f"No session found: tenant={tenant_id} platform={platform}")
        return None
    return session.storage_state


async def session_exists(db: AsyncSession, tenant_id: str, platform: str) -> bool:
    return await _row(db, tenant_id, platform) is not None
