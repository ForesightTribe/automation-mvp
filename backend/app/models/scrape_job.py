from beanie import Document
from datetime import datetime
from typing import Optional
from enum import Enum
from pymongo import IndexModel, ASCENDING, DESCENDING


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ScrapeJob(Document):
    tenant_id: str
    platform: str
    dashboard: str              # sales | marketing | unified
    status: JobStatus = JobStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    records_written: int = 0
    created_at: datetime = datetime.utcnow()

    class Settings:
        name = "scrape_jobs"
        indexes = [
            IndexModel([("tenant_id", ASCENDING), ("platform", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("status", ASCENDING)]),
        ]
