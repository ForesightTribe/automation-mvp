"""cm D19 lifecycle: state on cm_budget_schedules + cm_bid_rules

Adds `state` (active/paused/stopped) for the Pause/Resume/Stop/Reset controls (D19).
Budget uses active/stopped; bid uses all three. Default 'active' backfills every row —
additive, existing automations keep running.

Revision ID: e5c9b2d7a418
Revises: d8a3f16b5e94
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'e5c9b2d7a418'
down_revision: Union[str, Sequence[str], None] = 'd8a3f16b5e94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("cm_budget_schedules", "cm_bid_rules"):
        op.add_column(table, sa.Column(
            'state', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
            server_default='active'))


def downgrade() -> None:
    for table in ("cm_budget_schedules", "cm_bid_rules"):
        op.drop_column(table, 'state')
