"""zepto seller sales tables

Revision ID: 960b16030b12
Revises: e4a2c8d1b769
Create Date: 2026-08-19 17:09:43.718835

Hand-trimmed to the two new tables only. `--autogenerate` also proposed
dropping `ad_automation_rules`/`ad_automation_actions`, removing the ondelete
rules from the `budget_schedule_rules` and `jobs` foreign keys, adding health
columns to `platform_credentials`, and dropping `idx_listing_tenant_store` —
i.e. pre-existing model/DB drift plus another branch's in-flight work, none of
it related to Zepto. Adding tables should only add tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '960b16030b12'
down_revision: Union[str, Sequence[str], None] = 'e4a2c8d1b769'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'zepto_seller_sales_daily',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('brand_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('brand_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('gmv', sa.Float(), nullable=False),
        sa.Column('units', sa.Integer(), nullable=False),
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('upsert_key'),
    )
    op.create_index(
        'idx_zssd_tenant_date', 'zepto_seller_sales_daily', ['tenant_id', 'date'], unique=False
    )

    op.create_table(
        'zepto_seller_product_perf',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('product_variant_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('product_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('sku_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('pack_size', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('unit_of_measure', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('category_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('subcategory_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('gmv', sa.Float(), nullable=False),
        sa.Column('qty_sold', sa.Integer(), nullable=False),
        sa.Column('sales_contribution', sa.Float(), nullable=True),
        sa.Column('available_stores', sa.Float(), nullable=True),
        sa.Column('week_on_week_growth', sa.Float(), nullable=True),
        sa.Column('month_on_month_growth', sa.Float(), nullable=True),
        sa.Column('stock_on_hand', sa.Integer(), nullable=True),
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('upsert_key'),
    )
    op.create_index(
        'idx_zspp_tenant_period',
        'zepto_seller_product_perf',
        ['tenant_id', 'period_start', 'period_end'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_zspp_tenant_period', table_name='zepto_seller_product_perf')
    op.drop_table('zepto_seller_product_perf')
    op.drop_index('idx_zssd_tenant_date', table_name='zepto_seller_sales_daily')
    op.drop_table('zepto_seller_sales_daily')
