"""add blinkit seller hub sales city daily table

Revision ID: 3e23ee39b4e4
Revises: 22a1672fa473
Create Date: 2026-10-01 16:16:43.166843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '3e23ee39b4e4'
down_revision: Union[str, Sequence[str], None] = '22a1672fa473'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_bshscd_tenant_date', table_name='blinkit_seller_hub_sales_city_daily_ro')
    op.drop_index('idx_bshscd_tenant_city', table_name='blinkit_seller_hub_sales_city_daily_ro')
    op.drop_table('blinkit_seller_hub_sales_city_daily_ro')
