"""instamart_ad_account_daily add_to_cart_count

The batch metrics endpoint was never asked for METRIC_TYPE_ADD_TO_CART_COUNT,
so the Insights KPI tile read 0 even though the per-campaign table
(instamart_ad_campaigns) already had real ATC figures. Adds the column;
existing rows backfill to 0 (server_default) until the next `scrape
instamart-ads` re-populates them for real.

Revision ID: f2a91c6e0d4b
Revises: e5c7d13a4f89
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a91c6e0d4b"
down_revision: Union[str, Sequence[str], None] = "e5c7d13a4f89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "instamart_ad_account_daily",
        sa.Column("add_to_cart_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("instamart_ad_account_daily", "add_to_cart_count")
