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
