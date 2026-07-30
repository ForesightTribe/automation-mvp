"""cm_platform_accounts — per-tenant, per-platform advertiser (ad-account) id

Stores the marketplace advertiser id for each tenant (B3). Blinkit doesn't expose it in
its read APIs, so it's captured at onboarding and stored here; live writes send it
explicitly (replacing reliance on a hardcoded constant). Per (tenant, platform) — MP-ready.

Revision ID: d8a3f16b5e94
Revises: c7f4e2a9b8d1
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'd8a3f16b5e94'
down_revision: Union[str, Sequence[str], None] = 'c7f4e2a9b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cm_platform_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('advertiser_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'platform', name='uq_cm_platacct_tenant_platform'),
    )


def downgrade() -> None:
    op.drop_table('cm_platform_accounts')
