"""zepto ad analytics metrics + keyword table

Revision ID: d4b29f7c15e3
Revises: c3f81a02d7b5
Create Date: 2026-08-20

Adds the Analytics-page metrics the Campaign Management endpoint does not
report (revenue, add-to-carts, FOC-excluded RoAS, windowed orders, SKU split)
and a keyword table — Zepto's equivalent of blinkit_ad_campaign_detail.

Hand-written: --autogenerate on this database also proposes dropping
ad_automation_rules / ad_automation_actions, loosening two foreign keys'
ondelete rules and dropping idx_listing_tenant_store, none of which are ours.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'd4b29f7c15e3'
down_revision: Union[str, Sequence[str], None] = 'c3f81a02d7b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_CAMPAIGN_COLS = [
    ("revenue", sa.Float()),
    ("atc", sa.Integer()),
    ("windowed_orders", sa.Integer()),
    ("robas", sa.Float()),
    ("cpm", sa.Float()),
    ("same_skus", sa.Integer()),
    ("other_skus", sa.Integer()),
    ("unique_reach", sa.Integer()),
    ("new_to_brand_pct", sa.Float()),
]


def upgrade() -> None:
    """Upgrade schema."""
    for name, coltype in _NEW_CAMPAIGN_COLS:
        op.add_column('zepto_ad_campaign_daily', sa.Column(name, coltype, nullable=True))

    op.create_table(
        'zepto_ad_keyword_daily',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('brand_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('campaign_category', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('keyword', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('match_type', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('spend', sa.Float(), nullable=False),
        sa.Column('revenue', sa.Float(), nullable=True),
        sa.Column('impressions', sa.Integer(), nullable=False),
        sa.Column('clicks', sa.Integer(), nullable=False),
        sa.Column('orders', sa.Integer(), nullable=True),
        sa.Column('atc', sa.Integer(), nullable=True),
        sa.Column('ctr', sa.Float(), nullable=True),
        sa.Column('cpc', sa.Float(), nullable=True),
        sa.Column('cpm', sa.Float(), nullable=True),
        sa.Column('roas', sa.Float(), nullable=True),
        sa.Column('robas', sa.Float(), nullable=True),
        sa.Column('same_skus', sa.Integer(), nullable=True),
        sa.Column('other_skus', sa.Integer(), nullable=True),
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('upsert_key'),
    )
    op.create_index(
        'idx_zakd_tenant_date', 'zepto_ad_keyword_daily', ['tenant_id', 'date'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_zakd_tenant_date', table_name='zepto_ad_keyword_daily')
    op.drop_table('zepto_ad_keyword_daily')
    for name, _ in reversed(_NEW_CAMPAIGN_COLS):
        op.drop_column('zepto_ad_campaign_daily', name)
