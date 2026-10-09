from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings

_db_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Port 6543 is Supabase's TRANSACTION pooler: consecutive queries can land on
# different backends, so asyncpg's auto-named prepared statements collide
# (DuplicatePreparedStatementError). Its cache must be off on that port only.
_tx_pooler = ":6543" in _db_url
_connect_args = {"statement_cache_size": 0} if _tx_pooler else {}

engine = create_async_engine(
    _db_url,
    echo=settings.DEBUG,
    connect_args=_connect_args,
    pool_pre_ping=True,
    # Per PROCESS, and every open pooled connection holds one of the Supabase pooler's 45
    # slots (session mode). Configurable because API + runner + each job subprocess +
    # every local dev backend has its own pool. See DB_POOL_SIZE in config.py.
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=0,
    # Long scrape runs hold a pooled connection across slow browser work; the
    # Supabase pooler / a home-network NAT can silently drop one that idles too
    # long, surfacing as asyncpg ConnectionDoesNotExistError at the next commit.
    # asyncpg (unlike libpq) exposes no TCP-keepalive knobs, so we can't stop the
    # drop at the socket — instead recycle any pooled connection older than 30 min
    # so a stale one is never reused. pool_pre_ping (above) validates at checkout;
    # the write paths retry once on a mid-flight drop (see sku_storage.save_skus).
    pool_recycle=1800,
)

if settings.DB_IDLE_TX_TIMEOUT_S:
    # ⚠️ Must be a SET on every new connection. asyncpg's `server_settings` (a startup
    # parameter) is silently dropped by Supavisor — verified 2026-09-11, the value stayed
    # 0. A session-level SET survives ROLLBACK and lasts for the connection's life, and the
    # pooler resets it (DISCARD ALL) when the client disconnects, so it can't leak to other
    # clients. Past the limit Postgres terminates the connection: the stalled request
    # fails, and pool_pre_ping discards the dead connection at the next checkout.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_idle_tx_timeout(dbapi_connection, _record) -> None:
        dbapi_connection.run_async(
            lambda conn: conn.execute(
                f"SET idle_in_transaction_session_timeout = '{settings.DB_IDLE_TX_TIMEOUT_S}s'"
            )
        )

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    session: AsyncSession = AsyncSessionLocal()
    try:
        yield session
    finally:
        try:
            await session.close()
        except Exception:
            pass  # ignore stale-connection errors on cleanup


async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
