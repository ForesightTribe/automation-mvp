"""instamart ad product/keyword daily add campaign_type

Verified live that METRIC_FILTER_TYPE_CAMPAIGN_TYPE genuinely narrows the
product/keyword breakdown (BANNER: 9 products; SEARCH_AUTO_SUGGEST: 1, the
brand-wide row) -- adds a nullable campaign_type column to both daily
tables so a type-specific breakdown can be stored alongside the existing
unfiltered "All types" rows (campaign_type IS NULL), without touching them.

Revision ID: e91b4a2f65d7
Revises: d6e1a89f37c2
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "e91b4a2f65d7"
down_revision: Union[str, Sequence[str], None] = "d6e1a89f37c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "instamart_ad_product_daily",
        sa.Column("campaign_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "instamart_ad_keyword_daily",
        sa.Column("campaign_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instamart_ad_keyword_daily", "campaign_type")
    op.drop_column("instamart_ad_product_daily", "campaign_type")
