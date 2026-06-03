from beanie import Document
from datetime import datetime
from typing import Optional
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ScrapeJob(Document):
    platform: str
    tenant_id: str
    status: JobStatus = JobStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    created_at: datetime = datetime.utcnow()

    class Settings:
        name = "scrape_jobs"
