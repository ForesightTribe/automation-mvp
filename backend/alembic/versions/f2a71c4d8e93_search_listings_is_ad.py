"""search_listings.is_ad — mark sponsored placements

Zepto interleaves paid placements with organic ones and says which is which; we were
not reading it. On a live `bread` search **9 of 24 results (37.5%) were sponsored**,
every one stored as organic — so SoV and rank are currently computed over a mixture of
bought and earned placements.

Marketplace-agnostic on purpose. Zepto populates it from `meta.tagsV2[*].tagType ==
"SPONSORED"` as of this change; Blinkit will populate it from
`tracking.common_attributes.ads_campaign_id`, which is already parsed correctly in
`campaign_manager/marketplaces/blinkit/live_position.py` but never reached the scraper
(see zepto-cm-exp/TODO-blinkit-is-ad.md). One column serves both — a Zepto-only column
would have meant a second migration.

NOT NULL DEFAULT false, matching `is_combo` beside it. Existing rows become `false`,
which is the honest reading: those scrapes could not tell, and reporting them organic
under-counts ads rather than inventing them.

⚠️ ORDERING. This migration must run BEFORE `is_ad` is added to the `SearchListing`
model — a model column that does not exist in the database breaks every read of the
table immediately. That exact ordering already caused an incident on
`cm_platform_accounts.account_ref`.

Revision ID: f2a71c4d8e93
Revises: d3b8f6a04c71
Create Date: 2026-09-01
"""
import sqlalchemy as sa
from alembic import op

revision = "f2a71c4d8e93"
down_revision = "d3b8f6a04c71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_listings",
        sa.Column("is_ad", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("search_listings", "is_ad")
