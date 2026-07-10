import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, JSON

from app.models.job import JobStatus
from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class ExplorerRun(SQLModel, table=True):
    """One on-demand Explorer scrape → Excel run.

    The Explorer is agency-facing and EPHEMERAL: the scrape writes nothing to the
    per-tenant fact tables (`search_snapshots`/`search_listings`/`sku_snapshots`).
    This row is the run's audit + progress record — the future admin UI polls it
    for status and a progress bar, and reads `params` to reproduce/re-run it.

    `account_id`/`tenant_id` are nullable: CLI runs have neither, and a standalone
    (prospect) run has no client. `tenant_id`, when set, only means the run's
    defaults were seeded from that client's watchlist — it does NOT scope storage.
    """

    __tablename__ = "explorer_runs"

    __table_args__ = (
        Index("idx_explorer_account", "account_id", "created_at"),
        Index("idx_explorer_status", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID | None = Field(default=None, foreign_key="accounts.id")
    tenant_id: uuid.UUID | None = Field(default=None, foreign_key="tenants.id")

    marketplace: str = "blinkit"
    mode: str = "keyword"          # 'keyword' | 'catalog' | 'both'
    brand_slug: str = ""
    label: str = ""                # optional human label for the run

    # The full ExplorerSpec — makes the run reproducible / re-runnable from the UI.
    params: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    status: JobStatus = JobStatus.pending
    # Progress (locations): processed / total drives the UI progress bar.
    processed: int = 0
    total: int = 0

    # Result counters.
    keywords: int = 0
    locations: int = 0
    snapshots: int = 0
    rows: int = 0
    errors: int = 0

    # The workbook artifact (local disk now; object storage + download endpoint
    # in the frontend phase).
    output_path: str | None = None
    output_filename: str | None = None

    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_ist)
