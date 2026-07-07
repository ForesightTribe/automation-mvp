"""add daily_budget to blinkit_ad_campaigns

Revision ID: b7c3d8e2f1a9
Revises: f1a2b3c4d5e6
Create Date: 2026-07-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7c3d8e2f1a9'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'blinkit_ad_campaigns',
        sa.Column('daily_budget', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('blinkit_ad_campaigns', 'daily_budget')
