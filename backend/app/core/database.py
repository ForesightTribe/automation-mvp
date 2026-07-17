from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings

_db_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    _db_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    # Supabase's pooler caps total clients (currently 25). The concurrent public
    # scraper uses ~one DB connection per worker (default 5) + the main session.
    # Configurable because every PROCESS gets its own pool: the runner spawns each
    # scrape as a subprocess, so API + runner + N subprocesses must sum under the
    # cap. On the VM set DB_POOL_SIZE=3–5 in .env. See docs/jobs.md.
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
