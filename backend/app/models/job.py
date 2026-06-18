import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, Index, LargeBinary
from sqlmodel import Field, SQLModel


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class ScrapeJob(SQLModel, table=True):
    __tablename__ = "scrape_jobs"

    __table_args__ = (
        Index("idx_jobs_tenant", "tenant_id", "platform"),
        Index("idx_jobs_status", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    dashboard: str
    status: JobStatus = JobStatus.pending
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    records_written: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PlatformSession(SQLModel, table=True):
    __tablename__ = "platform_sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str
    encrypted_session: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
