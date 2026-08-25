"""zepto ad product + category daily tables

Revision ID: e7a1c94b2f60
Revises: d4b29f7c15e3
Create Date: 2026-08-21

Adds the Analytics page's Product Performance and Category Performance tables,
the two tabular views not yet stored. Purely additive — two new tables, no
change to anything that exists.

Hand-written: --autogenerate on this database also proposes dropping
ad_automation_rules / ad_automation_actions, loosening two foreign keys'
ondelete rules and dropping idx_listing_tenant_store, none of which are ours.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'e7a1c94b2f60'
down_revision: Union[str, Sequence[str], None] = 'd4b29f7c15e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Metrics shared by both views. Zepto reports no CTR on the category view.
_METRICS = [
    ("spend", sa.Float(), False),
    ("revenue", sa.Float(), True),
    ("impressions", sa.Integer(), False),
    ("clicks", sa.Integer(), False),
    ("orders", sa.Integer(), True),
    ("atc", sa.Integer(), True),
    ("cpc", sa.Float(), True),
    ("cpm", sa.Float(), True),
    ("roas", sa.Float(), True),
    ("robas", sa.Float(), True),
    ("same_skus", sa.Integer(), True),
    ("other_skus", sa.Integer(), True),
]


def _common() -> list:
    return [
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('upsert_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scrape_job_id', sa.Uuid(), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('brand_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('campaign_category', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    ]


def _tail() -> list:
    return [
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scrape_job_id'], ['scrape_jobs.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('upsert_key'),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'zepto_ad_product_daily',
        *_common(),
        sa.Column('product_variant_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('product_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('image_link', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('product_category', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('ctr', sa.Float(), nullable=True),
        *[sa.Column(n, t, nullable=nul) for n, t, nul in _METRICS],
        *_tail(),
    )
    op.create_index(
        'idx_zapd_tenant_date', 'zepto_ad_product_daily', ['tenant_id', 'date'], unique=False
    )

    op.create_table(
        'zepto_ad_category_daily',
        *_common(),
        sa.Column('category_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        *[sa.Column(n, t, nullable=nul) for n, t, nul in _METRICS],
        *_tail(),
    )
    op.create_index(
        'idx_zacatd_tenant_date', 'zepto_ad_category_daily', ['tenant_id', 'date'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_zacatd_tenant_date', table_name='zepto_ad_category_daily')
    op.drop_table('zepto_ad_category_daily')
    op.drop_index('idx_zapd_tenant_date', table_name='zepto_ad_product_daily')
    op.drop_table('zepto_ad_product_daily')
