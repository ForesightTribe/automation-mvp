"""zepto ad breakdown daily (category + city + page)

Revision ID: f2c68d31a9e4
Revises: e7a1c94b2f60
Create Date: 2026-08-21

Replaces `zepto_ad_category_daily` with `zepto_ad_breakdown_daily`, which
covers three structurally identical tabular views — category_table, city_table
and page_table. All three return only a `{dim}_name` plus the same twelve
metrics, so three tables would have had identical columns; the view is stored
in a `dimension` column instead.

Existing category rows are copied across rather than dropped, so no re-scrape
is needed. The upsert_key is rewritten to include the dimension, matching what
the parser now emits — without that, a city and a category sharing a name on
the same day would collide.

Hand-written: --autogenerate on this database also proposes dropping
ad_automation_rules / ad_automation_actions, loosening two foreign keys'
ondelete rules and dropping idx_listing_tenant_store, none of which are ours.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'f2c68d31a9e4'
down_revision: Union[str, Sequence[str], None] = 'e7a1c94b2f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_METRICS = [
    ("spend", sa.Float(), False),
    ("revenue", sa.Float(), True),
    ("impressions", sa.Integer(), False),
    ("clicks", sa.Integer(), False),
    ("orders", sa.Integer(), True),
    ("atc", sa.Integer(), True),
    ("cpc", sa.Float(), True),
    ("cpm", sa.Float(), True),
    ("roas", sa.Float(), True),
    ("robas", sa.Float(), True),
    ("same_skus", sa.Integer(), True),
    ("other_skus", sa.Integer(), True),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'zepto_ad_breakdown_daily',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('brand_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('campaign_category', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('dimension', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        *[sa.Column(n, t, nullable=nul) for n, t, nul in _METRICS],
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('upsert_key'),
    )
    op.create_index(
        'idx_zabd_tenant_date', 'zepto_ad_breakdown_daily', ['tenant_id', 'date'], unique=False
    )
    op.create_index(
        'idx_zabd_dimension', 'zepto_ad_breakdown_daily',
        ['tenant_id', 'dimension', 'date'], unique=False,
    )

    # Carry the already-scraped category rows over. The upsert_key gains the
    # dimension so it matches what the parser now produces — otherwise the next
    # scrape would insert duplicates alongside these instead of updating them.
    op.execute(
        """
        INSERT INTO zepto_ad_breakdown_daily (
            tenant_id, platform, upsert_key, scrape_job_id, date, brand_id,
            campaign_category, dimension, name,
            spend, revenue, impressions, clicks, orders, atc,
            cpc, cpm, roas, robas, same_skus, other_skus, scraped_at
        )
        SELECT
            tenant_id, platform,
            replace(upsert_key, ':ad_category_daily:', ':ad_breakdown_daily:category:'),
            scrape_job_id, date, brand_id,
            campaign_category, 'category', category_name,
            spend, revenue, impressions, clicks, orders, atc,
            cpc, cpm, roas, robas, same_skus, other_skus, scraped_at
        FROM zepto_ad_category_daily
        """
    )

    op.drop_index('idx_zacatd_tenant_date', table_name='zepto_ad_category_daily')
    op.drop_table('zepto_ad_category_daily')


def downgrade() -> None:
    """Downgrade schema.

    Recreates the category table and moves its rows back; city and page rows
    have no home in the old shape and are dropped with the table.
    """
    op.create_table(
        'zepto_ad_category_daily',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('brand_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('campaign_category', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('category_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        *[sa.Column(n, t, nullable=nul) for n, t, nul in _METRICS],
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('upsert_key'),
    )
    op.create_index(
        'idx_zacatd_tenant_date', 'zepto_ad_category_daily', ['tenant_id', 'date'], unique=False
    )
    op.execute(
        """
        INSERT INTO zepto_ad_category_daily (
            tenant_id, platform, upsert_key, scrape_job_id, date, brand_id,
            campaign_category, category_name,
            spend, revenue, impressions, clicks, orders, atc,
            cpc, cpm, roas, robas, same_skus, other_skus, scraped_at
        )
        SELECT
            tenant_id, platform,
            replace(upsert_key, ':ad_breakdown_daily:category:', ':ad_category_daily:'),
            scrape_job_id, date, brand_id,
            campaign_category, name,
            spend, revenue, impressions, clicks, orders, atc,
            cpc, cpm, roas, robas, same_skus, other_skus, scraped_at
        FROM zepto_ad_breakdown_daily WHERE dimension = 'category'
        """
    )
    op.drop_index('idx_zabd_dimension', table_name='zepto_ad_breakdown_daily')
    op.drop_index('idx_zabd_tenant_date', table_name='zepto_ad_breakdown_daily')
    op.drop_table('zepto_ad_breakdown_daily')
