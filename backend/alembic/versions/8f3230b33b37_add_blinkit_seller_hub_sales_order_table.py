"""add blinkit seller hub sales order table

Revision ID: 8f3230b33b37
Revises: ac7aa3ca4183
Create Date: 2026-10-01 19:50:48.214206

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '8f3230b33b37'
down_revision: Union[str, Sequence[str], None] = 'ac7aa3ca4183'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('blinkit_seller_hub_sales_order_ro',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
    sa.Column('order_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('order_date', sa.Date(), nullable=False),
    sa.Column('item_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('product_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('brand_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('upc', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('variant_description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('consumer_app_mapping', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('business_category', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('expansion_level', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('supply_city', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('supply_state', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('supply_state_gst', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('customer_city', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('customer_state', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('order_status', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('hsn_code', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('igst_pct', sa.Float(), nullable=True),
    sa.Column('cgst_pct', sa.Float(), nullable=True),
    sa.Column('sgst_pct', sa.Float(), nullable=True),
    sa.Column('cess_pct', sa.Float(), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('mrp', sa.Float(), nullable=False),
    sa.Column('selling_price', sa.Float(), nullable=False),
    sa.Column('igst_value', sa.Float(), nullable=False),
    sa.Column('cgst_value', sa.Float(), nullable=False),
    sa.Column('sgst_value', sa.Float(), nullable=False),
    sa.Column('cess_value', sa.Float(), nullable=False),
    sa.Column('total_tax', sa.Float(), nullable=False),
    sa.Column('total_gross_amount', sa.Float(), nullable=False),
    sa.Column('scraped_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upsert_key')
    )
    op.create_index('idx_bshso_tenant_city', 'blinkit_seller_hub_sales_order_ro', ['tenant_id', 'supply_city'], unique=False)
    op.create_index('idx_bshso_tenant_date', 'blinkit_seller_hub_sales_order_ro', ['tenant_id', 'order_date'], unique=False)
    op.create_index('idx_bshso_tenant_item', 'blinkit_seller_hub_sales_order_ro', ['tenant_id', 'item_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_bshso_tenant_item', table_name='blinkit_seller_hub_sales_order_ro')
    op.drop_index('idx_bshso_tenant_date', table_name='blinkit_seller_hub_sales_order_ro')
    op.drop_index('idx_bshso_tenant_city', table_name='blinkit_seller_hub_sales_order_ro')
    op.drop_table('blinkit_seller_hub_sales_order_ro')
