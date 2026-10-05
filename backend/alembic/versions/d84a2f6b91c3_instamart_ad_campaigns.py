"""instamart ad campaigns

`/api/v1/campaigns` (same signed session as the seller sales report) returns
campaign identity and lifetime metrics together — no daily backbone exists on
Instamart's side, so this is one snapshot table, replaced whole per campaign
on every scrape, not a `*_daily` table like Blinkit's/Zepto's.

Revision ID: d84a2f6b91c3
Revises: c7f2a9d13e56
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "d84a2f6b91c3"
down_revision: Union[str, Sequence[str], None] = "c7f2a9d13e56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instamart_ad_campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("upsert_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scrape_job_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("campaign_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("placements", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("budget_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("daily_budget", sa.Float(), nullable=True),
        sa.Column("spend", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gmv", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.Column("add_to_cart_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversion_rate", sa.Float(), nullable=True),
        sa.Column("roi", sa.Float(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["scrape_job_id"], ["scrape_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upsert_key"),
    )
    op.create_index(
        "idx_iac_tenant", "instamart_ad_campaigns", ["tenant_id", "campaign_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_iac_tenant", table_name="instamart_ad_campaigns")
    op.drop_table("instamart_ad_campaigns")
