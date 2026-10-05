"""drop retired blinkit seller hub daily / city / category tables

Revision ID: 4b7e2c91d0a3
Revises: 8f3230b33b37
Create Date: 2026-10-02 17:10:00.000000

The day, city-day and category-day chart tables stopped being written on
2026-10-01: every number they held is a GROUP BY on
blinkit_seller_hub_sales_order_ro. Their rows (61 / 1,490 / 90, Sereko only,
Aug-Sep 2026) were exported to CSV before this drop. Downgrade recreates the
empty tables exactly as their original migrations (22a1672fa473, 3e23ee39b4e4,
ac7aa3ca4183) created them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '4b7e2c91d0a3'
down_revision: Union[str, Sequence[str], None] = '8f3230b33b37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index('idx_bshscatd_tenant_date', table_name='blinkit_seller_hub_sales_category_daily_ro')
    op.drop_index('idx_bshscatd_tenant_category', table_name='blinkit_seller_hub_sales_category_daily_ro')
    op.drop_table('blinkit_seller_hub_sales_category_daily_ro')
    op.drop_index('idx_bshscd_tenant_date', table_name='blinkit_seller_hub_sales_city_daily_ro')
    op.drop_index('idx_bshscd_tenant_city', table_name='blinkit_seller_hub_sales_city_daily_ro')
    op.drop_table('blinkit_seller_hub_sales_city_daily_ro')
    op.drop_index('idx_bshsd_tenant_date', table_name='blinkit_seller_hub_sales_daily_ro')
    op.drop_table('blinkit_seller_hub_sales_daily_ro')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('blinkit_seller_hub_sales_daily_ro',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('sales_amount', sa.Float(), nullable=False),
    sa.Column('units_sold', sa.Integer(), nullable=False),
    sa.Column('scraped_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upsert_key')
    )
    op.create_index('idx_bshsd_tenant_date', 'blinkit_seller_hub_sales_daily_ro', ['tenant_id', 'date'], unique=False)
    op.create_table('blinkit_seller_hub_sales_city_daily_ro',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
    sa.Column('city', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('sales_amount', sa.Float(), nullable=False),
    sa.Column('units_sold', sa.Integer(), nullable=False),
    sa.Column('scraped_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upsert_key')
    )
    op.create_index('idx_bshscd_tenant_city', 'blinkit_seller_hub_sales_city_daily_ro', ['tenant_id', 'city'], unique=False)
    op.create_index('idx_bshscd_tenant_date', 'blinkit_seller_hub_sales_city_daily_ro', ['tenant_id', 'date'], unique=False)
    op.create_table('blinkit_seller_hub_sales_category_daily_ro',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
    sa.Column('category', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('sales_amount', sa.Float(), nullable=False),
    sa.Column('units_sold', sa.Integer(), nullable=False),
    sa.Column('scraped_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upsert_key')
    )
    op.create_index('idx_bshscatd_tenant_category', 'blinkit_seller_hub_sales_category_daily_ro', ['tenant_id', 'category'], unique=False)
    op.create_index('idx_bshscatd_tenant_date', 'blinkit_seller_hub_sales_category_daily_ro', ['tenant_id', 'date'], unique=False)
