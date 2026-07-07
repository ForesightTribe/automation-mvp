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
    pool_recycle=300,        # recycle connections every 5 min (prevents stale conn errors)
    pool_size=5,
    max_overflow=10,
    connect_args={
        "server_settings": {"application_name": "foresight-backend"},
    },
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
