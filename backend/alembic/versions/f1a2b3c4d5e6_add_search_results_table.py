"""add search_results table (was missing from DB)

Revision ID: f1a2b3c4d5e6
Revises: adcf3ccd495b
Create Date: 2026-07-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'adcf3ccd495b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'search_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('brand_slug', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('mp_slug', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('city', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('zone', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('pincode', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('keyword', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('merchant_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('store_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.Column('brand_rank', sa.Integer(), nullable=True),
        sa.Column('brand_sov', sa.Float(), nullable=True),
        sa.Column('total_results', sa.Integer(), nullable=True),
        sa.Column('products', sa.JSON(), nullable=True),
        sa.Column('competitors', sa.JSON(), nullable=True),
        sa.Column('raw', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['brand_slug'], ['brands.slug']),
        sa.ForeignKeyConstraint(['mp_slug'], ['marketplaces.slug']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_sr_brand_mp', 'search_results', ['brand_slug', 'mp_slug'], unique=False)
    op.create_index('idx_sr_city', 'search_results', ['brand_slug', 'city'], unique=False)
    op.create_index('idx_sr_keyword', 'search_results', ['brand_slug', 'keyword', 'city'], unique=False)
    op.create_index('idx_sr_scraped', 'search_results', ['scraped_at'], unique=False)
    op.create_index('idx_sr_zone', 'search_results', ['brand_slug', 'city', 'zone'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_sr_zone', table_name='search_results')
    op.drop_index('idx_sr_scraped', table_name='search_results')
    op.drop_index('idx_sr_keyword', table_name='search_results')
    op.drop_index('idx_sr_city', table_name='search_results')
    op.drop_index('idx_sr_brand_mp', table_name='search_results')
    op.drop_table('search_results')
