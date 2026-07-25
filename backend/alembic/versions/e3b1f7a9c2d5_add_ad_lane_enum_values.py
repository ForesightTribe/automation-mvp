"""add budget_scheduler, bid_optimizer, sync_campaign_data to lane enum

Revision ID: e3b1f7a9c2d5
Revises: 2bb4d44b4cf7
Create Date: 2026-07-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3b1f7a9c2d5"
down_revision: Union[str, Sequence[str], None] = "2bb4d44b4cf7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PG 12+ allows ADD VALUE inside a transaction block.
    for value in ("budget_scheduler", "bid_optimizer", "sync_campaign_data"):
        op.execute(sa.text(f"ALTER TYPE lane ADD VALUE IF NOT EXISTS '{value}'"))


def downgrade() -> None:
    # Postgres does not support removing enum values — downgrade is a no-op.
    pass
