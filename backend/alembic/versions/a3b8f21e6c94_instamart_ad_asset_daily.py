"""instamart ad product/keyword daily

`POST /api/v1/advertiser/metrics` with dimensions
[DIMENSION_TYPE_AD_CANDIDATE, DIMENSION_TYPE_DAY] or
[DIMENSION_TYPE_KEYWORD, DIMENSION_TYPE_DAY], no campaign filter -- a real
daily, account-wide breakdown, verified live (66 rows for 8 candidates x 8
days; 439 rows for the keyword table over the same window).

Revision ID: a3b8f21e6c94
Revises: f2a91c6e0d4b
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "a3b8f21e6c94"
down_revision: Union[str, Sequence[str], None] = "f2a91c6e0d4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _bookkeeping_cols():
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("upsert_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scrape_job_id", sa.Uuid(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
    ]


def _metric_cols():
    return [
        sa.Column("spend", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gmv", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("add_to_cart_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "instamart_ad_product_daily",
        *_bookkeeping_cols(),
        sa.Column("candidate_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        *_metric_cols(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["scrape_job_id"], ["scrape_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upsert_key"),
    )
    op.create_index(
        "idx_iapd_tenant_date", "instamart_ad_product_daily", ["tenant_id", "date"]
    )
    op.create_index(
        "idx_iapd_candidate", "instamart_ad_product_daily",
        ["tenant_id", "candidate_id", "date"],
    )

    op.create_table(
        "instamart_ad_keyword_daily",
        *_bookkeeping_cols(),
        sa.Column("keyword", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        *_metric_cols(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["scrape_job_id"], ["scrape_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upsert_key"),
    )
    op.create_index(
        "idx_iakd_tenant_date", "instamart_ad_keyword_daily", ["tenant_id", "date"]
    )
    op.create_index(
        "idx_iakd_keyword", "instamart_ad_keyword_daily",
        ["tenant_id", "keyword", "date"],
    )


def downgrade() -> None:
    op.drop_index("idx_iakd_keyword", table_name="instamart_ad_keyword_daily")
    op.drop_index("idx_iakd_tenant_date", table_name="instamart_ad_keyword_daily")
    op.drop_table("instamart_ad_keyword_daily")
    op.drop_index("idx_iapd_candidate", table_name="instamart_ad_product_daily")
    op.drop_index("idx_iapd_tenant_date", table_name="instamart_ad_product_daily")
    op.drop_table("instamart_ad_product_daily")
