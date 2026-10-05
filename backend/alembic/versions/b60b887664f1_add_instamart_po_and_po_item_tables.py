"""add instamart po and po item tables

Revision ID: b60b887664f1
Revises: f2a7c93d51e8
Create Date: 2026-09-25 12:00:15.023637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'b60b887664f1'
down_revision: Union[str, Sequence[str], None] = 'f2a7c93d51e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('instamart_po',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
    sa.Column('purchase_order_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('facility_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('vendor_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('vendor_code', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('receiving_status', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('po_date', sa.Date(), nullable=True),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('completed_date', sa.Date(), nullable=True),
    sa.Column('value', sa.Float(), nullable=True),
    sa.Column('is_low_stock_po', sa.Boolean(), nullable=False),
    sa.Column('total_quantity', sa.Integer(), nullable=False),
    sa.Column('pending_quantity', sa.Integer(), nullable=False),
    sa.Column('grn_quantity', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('scraped_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upsert_key')
    )
    op.create_index('idx_impo_facility', 'instamart_po', ['tenant_id', 'facility_name'], unique=False)
    op.create_index('idx_impo_tenant_po_date', 'instamart_po', ['tenant_id', 'po_date'], unique=False)
    op.create_table('instamart_po_item',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
    sa.Column('purchase_order_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('external_item_code', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('category_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('pending_qty', sa.Integer(), nullable=False),
    sa.Column('mrp', sa.Float(), nullable=True),
    sa.Column('line_cost_excluding_tax', sa.Float(), nullable=True),
    sa.Column('scraped_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upsert_key')
    )
    op.create_index('idx_impoi_item', 'instamart_po_item', ['tenant_id', 'external_item_code'], unique=False)
    op.create_index('idx_impoi_tenant_po', 'instamart_po_item', ['tenant_id', 'purchase_order_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_impoi_tenant_po', table_name='instamart_po_item')
    op.drop_index('idx_impoi_item', table_name='instamart_po_item')
    op.drop_table('instamart_po_item')
    op.drop_index('idx_impo_tenant_po_date', table_name='instamart_po')
    op.drop_index('idx_impo_facility', table_name='instamart_po')
    op.drop_table('instamart_po')
