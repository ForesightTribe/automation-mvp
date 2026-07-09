"""explorer_runs — on-demand Explorer scrape job/audit/progress record

The Explorer is agency-facing and ephemeral: the scrape writes nothing to the
per-tenant fact tables. This table is the run's audit + progress record (the
future admin UI polls it). `account_id`/`tenant_id` are nullable — CLI runs have
neither, and a standalone (prospect) run has no client.

Reuses the existing `jobstatus` enum (create_type=False — it already exists from
the scrape_jobs table).

Revision ID: a3e8d1f6c2b9
Revises: c3f9e1a7d2b8
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


revision: str = "a3e8d1f6c2b9"
down_revision: Union[str, Sequence[str], None] = "c3f9e1a7d2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Reference the enum already created by scrape_jobs — do NOT recreate it.
jobstatus = postgresql.ENUM(
    "pending", "running", "success", "failed", name="jobstatus", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "explorer_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("marketplace", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="blinkit"),
        sa.Column("mode", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="keyword"),
        sa.Column("brand_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("status", jobstatus, nullable=False, server_default="pending"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("keywords", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_path", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("output_filename", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_explorer_account", "explorer_runs", ["account_id", "created_at"])
    op.create_index("idx_explorer_status", "explorer_runs", ["status"])


def downgrade() -> None:
    op.drop_index("idx_explorer_status", table_name="explorer_runs")
    op.drop_index("idx_explorer_account", table_name="explorer_runs")
    op.drop_table("explorer_runs")
    # The `jobstatus` enum is owned by scrape_jobs — leave it in place.
