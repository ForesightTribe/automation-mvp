"""Instamart ad-asset daily: campaign_id on the by-type breakdown rows.

Adds `campaign_id` to `instamart_ad_product_daily` / `instamart_ad_keyword_daily`,
populated only on the by-type breakdown (campaign_type IS NOT NULL) — the
unfiltered "All types" rows never carry this dimension.

The by-type rows are DELETED here rather than left in place: their upsert_key
never included campaign_id (verified: `asset_metrics.py`'s old key format was
`instamart|{tid}|{date}|{key}|{campaign_type}`), so two campaigns advertising
the same product on the same day silently overwrote each other under the old
scrape. Keeping those stale, incomplete rows around next to freshly-scraped
ones (now keyed to include campaign_id) would double-count on re-scrape. This
table is a derived cache, not source-of-truth data — safe to clear and rebuild
via `scrape instamart-ads --ad-type-breakdown`. The unfiltered rows
(campaign_type IS NULL) are untouched.

Revision ID: f2a7c93d51e8
Revises: e91b4a2f65d7
"""
from alembic import op
import sqlalchemy as sa

revision = "f2a7c93d51e8"
down_revision = "e91b4a2f65d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "instamart_ad_product_daily",
        sa.Column("campaign_id", sa.String(), nullable=True),
    )
    op.add_column(
        "instamart_ad_keyword_daily",
        sa.Column("campaign_id", sa.String(), nullable=True),
    )
    op.execute(
        "DELETE FROM instamart_ad_product_daily WHERE campaign_type IS NOT NULL"
    )
    op.execute(
        "DELETE FROM instamart_ad_keyword_daily WHERE campaign_type IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("instamart_ad_keyword_daily", "campaign_id")
    op.drop_column("instamart_ad_product_daily", "campaign_id")
