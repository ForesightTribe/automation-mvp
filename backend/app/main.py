from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.utils.logger  # noqa: F401 — installs the unified logging pipeline before anything logs
from app.core.config import settings
from app.utils.exceptions import register_exception_handlers
from app.router import api_router

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix="/api")
