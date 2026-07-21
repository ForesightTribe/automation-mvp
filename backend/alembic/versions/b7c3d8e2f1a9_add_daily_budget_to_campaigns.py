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
    # Idempotent on purpose. On some databases (local campaign-manager dev, and the
    # shared Supabase DB) this column is created out of band by the campaign-manager
    # models' create_all, so a plain ADD COLUMN fails with DuplicateColumn. On a
    # database provisioned purely from migrations the column is absent and must be
    # created. `IF NOT EXISTS` is correct for both — no per-DB stamping needed.
    op.execute(
        "ALTER TABLE blinkit_ad_campaigns "
        "ADD COLUMN IF NOT EXISTS daily_budget INTEGER"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE blinkit_ad_campaigns "
        "DROP COLUMN IF EXISTS daily_budget"
    )
