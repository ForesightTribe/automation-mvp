"""instamart ad product/keyword daily: drop the dead campaign_type column

Added by e91b4a2f65d7 for a by-ad-type breakdown that was later removed:
Instamart's METRIC_FILTER_TYPE_CAMPAIGN_TYPE stopped discriminating between
types (identical totals for ITEM/BANNER/COLLECTION_ADS) and triple-counted
spend. Since then nothing writes or reads this column — checked 2026-10-06 on
the shared DB: 0 of 430 product rows and 0 of 2,391 keyword rows have it set.
A campaign's type is read from instamart_ad_campaigns.campaign_type, which
stays.

⚠️ ORDER: run this only after every deployment that talks to the shared DB
(the VM and every working branch) runs code WITHOUT `campaign_type` on
InstamartAdProductDaily / InstamartAdKeywordDaily. Older code still selects
the column and fails with "column ... does not exist" once it is gone.

Revision ID: d4b7e2a9c615
Revises: a1c4e7d93f20
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "d4b7e2a9c615"
down_revision: Union[str, Sequence[str], None] = "a1c4e7d93f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("instamart_ad_keyword_daily", "campaign_type")
    op.drop_column("instamart_ad_product_daily", "campaign_type")


def downgrade() -> None:
    # Every value was NULL, so restoring the empty column loses nothing.
    op.add_column(
        "instamart_ad_product_daily",
        sa.Column("campaign_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "instamart_ad_keyword_daily",
        sa.Column("campaign_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
