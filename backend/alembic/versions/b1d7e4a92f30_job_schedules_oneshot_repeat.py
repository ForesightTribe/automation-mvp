"""job_schedules one-shot support: repeat flag + nullable cron

V3.0 (Campaign Manager v2) — the unified scheduler. Adds a `repeat` flag to
`job_schedules` so one-time and recurring jobs share one system:
  - repeat=True  (default) → recurring; after firing, next_run_at advances via cron.
  - repeat=False           → one-shot; cron is NULL, next_run_at is an explicit fire
                             time, and the producer disables the row after it fires.

`cron` becomes nullable (a one-shot has no cron). Purely additive: every existing row
is recurring, and `repeat` defaults to True with a server_default so the backfill is
automatic and the runner keeps behaving exactly as before.

Revision ID: b1d7e4a92f30
Revises: aef972735d57
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1d7e4a92f30'
down_revision: Union[str, Sequence[str], None] = 'aef972735d57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New `repeat` column — server_default backfills every existing row to recurring.
    op.add_column(
        'job_schedules',
        sa.Column('repeat', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # A one-shot has no cron.
    op.alter_column('job_schedules', 'cron', existing_type=sa.VARCHAR(), nullable=True)


def downgrade() -> None:
    # Restore NOT NULL on cron only if no one-shots exist (they'd have NULL cron).
    op.execute("UPDATE job_schedules SET cron = '0 0 * * *' WHERE cron IS NULL")
    op.alter_column('job_schedules', 'cron', existing_type=sa.VARCHAR(), nullable=False)
    op.drop_column('job_schedules', 'repeat')
