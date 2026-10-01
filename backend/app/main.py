import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.utils.logger  # noqa: F401 — installs the unified logging pipeline before anything logs
from app.core.config import settings
from app.utils.exceptions import register_exception_handlers
from app.router import api_router
from app.utils import warmup

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the cache warm-up beside the API.

    Detached rather than awaited: the first pass takes tens of seconds and the
    API must serve while it runs. It lives here, not in the CLI or the job
    runner, so only the process answering requests does this work.
    """
    task = (
        asyncio.create_task(warmup.warm_forever())
        if settings.WARM_CACHE
        else None
    )
    try:
        yield
    finally:
        if task:
            task.cancel()


app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix="/api")
