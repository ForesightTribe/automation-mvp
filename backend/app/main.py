import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.utils.logger  # noqa: F401 — installs the unified logging pipeline before anything logs
from app.core.config import settings
from app.utils.logger import logger
from app.utils.exceptions import register_exception_handlers
from app.router import api_router
from app.utils import warmup

# The value shipped in config.py. Anyone who can read this repository has it.
_PLACEHOLDER_SECRET = "change-me-in-production"


def _check_signing_key() -> None:
    """Refuse to serve if the JWT signing key is the one in the repository.

    ⚠️ On the shipped default anyone with the repo can mint a token carrying any
    `account_id` and `role: admin`, and every other control sits behind token
    verification. Unset it fails OPEN and silently, hence a startup check.

    Lives here, not on `Settings`: the CLI, runner and scrapers load the same
    settings and issue no tokens. Matches only the exact placeholder and the
    empty string — a length or entropy rule could refuse a real key.
    """
    if settings.SECRET_KEY.strip() in ("", _PLACEHOLDER_SECRET):
        raise RuntimeError(
            "SECRET_KEY is unset or still the placeholder from config.py. "
            "Tokens signed with it can be forged by anyone with this repo. "
            "Set SECRET_KEY in the environment to a random secret, e.g. "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`"
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the cache warm-up beside the API.

    Detached rather than awaited: the first pass takes tens of seconds and the
    API must serve while it runs. It lives here, not in the CLI or the job
    runner, so only the process answering requests does this work.
    """
    _check_signing_key()
    if not settings.ENCRYPTION_KEY.strip():
        # Fails closed at first use (Fernet raises), so this is a louder warning
        # rather than a refusal: the API still serves everything that does not
        # touch stored marketplace credentials.
        logger.warning(
            "ENCRYPTION_KEY is unset — stored marketplace credentials and "
            "sessions cannot be read or written."
        )

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


# /docs, /redoc and /openapi.json describe every route, parameter and schema to
# anyone who asks, unauthenticated. Served only in development; elsewhere all
# three 404 because the routes are never registered.
_DOCS = settings.ENV.strip().lower() == "development"

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs" if _DOCS else None,
    redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix="/api")
