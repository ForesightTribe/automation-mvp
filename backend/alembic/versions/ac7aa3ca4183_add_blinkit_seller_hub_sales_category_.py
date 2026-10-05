"""add blinkit seller hub sales category daily table

Revision ID: ac7aa3ca4183
Revises: 3e23ee39b4e4
Create Date: 2026-10-01 17:31:10.734086

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'ac7aa3ca4183'
down_revision: Union[str, Sequence[str], None] = '3e23ee39b4e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_bshscatd_tenant_date', table_name='blinkit_seller_hub_sales_category_daily_ro')
    op.drop_index('idx_bshscatd_tenant_category', table_name='blinkit_seller_hub_sales_category_daily_ro')
    op.drop_table('blinkit_seller_hub_sales_category_daily_ro')
