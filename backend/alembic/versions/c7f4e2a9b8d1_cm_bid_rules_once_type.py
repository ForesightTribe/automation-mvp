"""cm_bid_rules: add `type` + `date` + `days` for bid timing parity with budget

Brings bidding to parity with budget timing (decision 2026-07-29): a bid rule can be a
recurring daily window OR a one-time single-date span (`type`/`date`), and a recurring
rule can be filtered to weekdays (`days`, e.g. Fri/Sat/Sun). `type` defaults to
'recurring' (server_default backfills every existing row); `date` and `days` are
nullable. Purely additive — existing bid rules are unchanged and stay recurring, every
day, no weekday filter.

Revision ID: c7f4e2a9b8d1
Revises: b1d7e4a92f30
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'c7f4e2a9b8d1'
down_revision: Union[str, Sequence[str], None] = 'b1d7e4a92f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'cm_bid_rules',
        sa.Column('type', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default='recurring'),
    )
    op.add_column(
        'cm_bid_rules',
        sa.Column('date', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        'cm_bid_rules',
        sa.Column('days', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('cm_bid_rules', 'days')
    op.drop_column('cm_bid_rules', 'date')
    op.drop_column('cm_bid_rules', 'type')
