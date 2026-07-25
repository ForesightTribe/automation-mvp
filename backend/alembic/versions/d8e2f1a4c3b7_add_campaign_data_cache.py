"""add campaign_data_cache table

Revision ID: d8e2f1a4c3b7
Revises: c7d1e9f3a2b4
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e2f1a4c3b7"
down_revision: Union[str, Sequence[str], None] = "c7d1e9f3a2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaign_data_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("products", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "campaign_id", name="uq_cdc_tenant_campaign"),
    )
    op.create_index("idx_cdc_tenant", "campaign_data_cache", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_cdc_tenant", table_name="campaign_data_cache")
    op.drop_table("campaign_data_cache")
