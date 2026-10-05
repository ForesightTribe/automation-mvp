"""instamart ad account daily

`POST /api/v1/advertiser/metrics/batch` with `dimensions:
["DIMENSION_TYPE_DAY"]` -- a genuine day-by-day, account-wide series, unlike
`/api/v1/campaigns` (instamart_ad_campaigns, a lifetime-only snapshot).
Verified against the live account: 8 days summed here matched the portal's
own windowed dashboard exactly on GMV, impressions AND spend.

Revision ID: e5c7d13a4f89
Revises: d84a2f6b91c3
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "e5c7d13a4f89"
down_revision: Union[str, Sequence[str], None] = "d84a2f6b91c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instamart_ad_account_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("upsert_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scrape_job_id", sa.Uuid(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("spend", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gmv", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=True),
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
        "idx_iaad_tenant_date", "instamart_ad_account_daily", ["tenant_id", "date"]
    )


def downgrade() -> None:
    op.drop_index("idx_iaad_tenant_date", table_name="instamart_ad_account_daily")
    op.drop_table("instamart_ad_account_daily")
