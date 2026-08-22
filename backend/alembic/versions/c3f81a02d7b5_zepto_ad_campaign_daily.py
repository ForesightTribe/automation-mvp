"""zepto ad campaign daily

Revision ID: c3f81a02d7b5
Revises: 960b16030b12
Create Date: 2026-08-20

Written by hand rather than with --autogenerate. On this database autogenerate
also proposes dropping ad_automation_rules / ad_automation_actions, loosening
the ondelete rules on two foreign keys, and dropping idx_listing_tenant_store —
pre-existing model/DB drift unrelated to Zepto. Adding a table should only add
a table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'c3f81a02d7b5'
down_revision: Union[str, Sequence[str], None] = '960b16030b12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'zepto_ad_campaign_daily',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('campaign_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('brand_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('brand_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('campaign_category', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('campaign_type', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('campaign_sub_type', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('bid_targeting_type', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('campaign_targeting_type', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('daily_budget', sa.Float(), nullable=True),
        sa.Column('lifetime_budget', sa.Float(), nullable=True),
        sa.Column('base_bid', sa.Float(), nullable=True),
        sa.Column('spend', sa.Float(), nullable=False),
        sa.Column('impressions', sa.Integer(), nullable=False),
        sa.Column('clicks', sa.Integer(), nullable=False),
        sa.Column('orders', sa.Integer(), nullable=False),
        sa.Column('cpc', sa.Float(), nullable=True),
        sa.Column('ecpm', sa.Float(), nullable=True),
        sa.Column('roi', sa.Float(), nullable=True),
        sa.Column('sov', sa.Float(), nullable=True),
        sa.Column('ad_position', sa.Float(), nullable=True),
        sa.Column('campaign_start_date', sa.DateTime(), nullable=True),
        sa.Column('campaign_end_date', sa.DateTime(), nullable=True),
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('upsert_key'),
    )
    op.create_index(
        'idx_zacd_tenant_date', 'zepto_ad_campaign_daily', ['tenant_id', 'date'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_zacd_tenant_date', table_name='zepto_ad_campaign_daily')
    op.drop_table('zepto_ad_campaign_daily')
