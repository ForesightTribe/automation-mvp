from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.utils.exceptions import register_exception_handlers
from app.router import api_router

_scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from app.services.ads_service import run_bid_optimizer_all_tenants, run_scheduler_all_tenants
    _scheduler.add_job(
        run_bid_optimizer_all_tenants,
        trigger="interval",
        minutes=30,
        id="bid_optimizer_auto",
        replace_existing=True,
    )
    _scheduler.add_job(
        run_scheduler_all_tenants,
        trigger="interval",
        minutes=5,
        id="budget_scheduler_auto",
        replace_existing=True,
    )
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix="/api")
