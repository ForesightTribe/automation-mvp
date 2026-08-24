"""zepto seller sales by city

Revision ID: a91d47e0b3c2
Revises: f2c68d31a9e4
Create Date: 2026-08-21

Adds the per-city sales split. Purely additive — one new table, nothing
existing is altered.

Hand-written: --autogenerate on this database also proposes dropping
ad_automation_rules / ad_automation_actions, loosening two foreign keys'
ondelete rules and dropping idx_listing_tenant_store, none of which are ours.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'a91d47e0b3c2'
down_revision: Union[str, Sequence[str], None] = 'f2c68d31a9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'zepto_seller_sales_city_daily',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('brand_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('city_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('city_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('gmv', sa.Float(), nullable=False),
        sa.Column('units', sa.Integer(), nullable=False),
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('upsert_key'),
    )
    op.create_index(
        'idx_zsscd_tenant_date', 'zepto_seller_sales_city_daily',
        ['tenant_id', 'date'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_zsscd_tenant_date', table_name='zepto_seller_sales_city_daily')
    op.drop_table('zepto_seller_sales_city_daily')
