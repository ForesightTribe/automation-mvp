"""add blinkit seller hub sales tables

Revision ID: 22a1672fa473
Revises: c4f7b2e81a93
Create Date: 2026-10-01 12:00:04.234309

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '22a1672fa473'
down_revision: Union[str, Sequence[str], None] = 'c4f7b2e81a93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Only the two new Blinkit seller-hub sales tables. Hand-trimmed from the
    autogenerate output, which also picked up unrelated pre-existing drift
    (a dropped zepto_seller_sales_city_daily table, index/FK rewrites on
    jobs/cm_bid_rules/zepto_seller_sales/search_listings) that has nothing to
    do with this change and is not included here.
    """
    op.create_table('blinkit_seller_hub_sales_by_product_ro',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
    sa.Column('window_label', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('product_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('item_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('upc', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('product_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('unit', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('business_category_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('units_sold', sa.Integer(), nullable=False),
    sa.Column('sales_amount', sa.Float(), nullable=False),
    sa.Column('sales_contribution_pct', sa.Float(), nullable=True),
    sa.Column('is_transitioned', sa.Boolean(), nullable=True),
    sa.Column('transition_date', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('scraped_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upsert_key')
    )
    op.create_index('idx_bshsbp_tenant_asof', 'blinkit_seller_hub_sales_by_product_ro', ['tenant_id', 'as_of_date'], unique=False)
    op.create_index('idx_bshsbp_tenant_item', 'blinkit_seller_hub_sales_by_product_ro', ['tenant_id', 'item_id'], unique=False)
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_bshsd_tenant_date', table_name='blinkit_seller_hub_sales_daily_ro')
    op.drop_table('blinkit_seller_hub_sales_daily_ro')
    op.drop_index('idx_bshsbp_tenant_item', table_name='blinkit_seller_hub_sales_by_product_ro')
    op.drop_index('idx_bshsbp_tenant_asof', table_name='blinkit_seller_hub_sales_by_product_ro')
    op.drop_table('blinkit_seller_hub_sales_by_product_ro')
