"""per-marketplace watchlist caps: tenant_watchlist_caps

Revision ID: c639761284ff
Revises: 8f3230b33b37
Create Date: 2026-10-02

A cap is a number of RESULTS, and each marketplace pages differently (Blinkit 12 a page,
Zepto 30), so the two caps move off `tenant_watchlist` onto one row per (watchlist row,
marketplace).

ADDITIVE ONLY. Production still runs code that reads `tenant_watchlist.keyword_cap` /
`brand_cap`, so those columns are left exactly as they are; a later migration drops them
once production runs the new code. This one creates the table and copies the current
values across AS THEY ARE — one row for each marketplace the watchlist row lists — to be
adjusted by hand afterwards (e.g. Sereko's Blinkit-shaped 36/48 on Zepto).

Parented on dev's head (8f3230b33b37), not on the branch it was written on.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'c639761284ff'
down_revision: Union[str, Sequence[str], None] = '8f3230b33b37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tenant_watchlist_caps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('watchlist_id', sa.Integer(), nullable=False),
        sa.Column('mp_slug', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('keyword_cap', sa.Integer(), nullable=True),
        sa.Column('brand_cap', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['watchlist_id'], ['tenant_watchlist.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mp_slug'], ['marketplaces.slug']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('watchlist_id', 'mp_slug', name='uq_tenant_watchlist_caps'),
    )
    op.create_index(op.f('ix_tenant_watchlist_caps_watchlist_id'), 'tenant_watchlist_caps',
                    ['watchlist_id'], unique=False)

    # Copy, as is: every watchlist row that sets a cap gets one caps row per marketplace it
    # lists (only marketplaces that exist — the FK would refuse anything else). Nothing on
    # `tenant_watchlist` is touched.
    op.execute("""
        INSERT INTO tenant_watchlist_caps
            (watchlist_id, mp_slug, keyword_cap, brand_cap, created_at, updated_at)
        SELECT w.id, m.slug, w.keyword_cap, w.brand_cap,
               now() AT TIME ZONE 'Asia/Kolkata', now() AT TIME ZONE 'Asia/Kolkata'
        FROM tenant_watchlist w
        CROSS JOIN LATERAL json_array_elements_text(w.marketplaces::json) AS e(slug)
        JOIN marketplaces m ON m.slug = e.slug
        WHERE w.keyword_cap IS NOT NULL OR w.brand_cap IS NOT NULL
        ON CONFLICT (watchlist_id, mp_slug) DO NOTHING
    """)


def downgrade() -> None:
    # Drops only the new table; `tenant_watchlist` was never changed.
    op.drop_index(op.f('ix_tenant_watchlist_caps_watchlist_id'),
                  table_name='tenant_watchlist_caps')
    op.drop_table('tenant_watchlist_caps')
