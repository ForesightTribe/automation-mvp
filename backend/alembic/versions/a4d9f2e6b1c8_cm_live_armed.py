"""cm cutover: live_armed flag on cm_platform_accounts

Revision ID: a4d9f2e6b1c8
Revises: f2a7c4e1d9b3
Create Date: 2026-07-31

The per-tenant arming switch for the V5 cutover. OFF by default — the automated loop
stays dry until armed. When True, the reconciler stamps `live=true` on the tenant's
engine schedules and the API's set-budget/reset pass live. server_default false so the
ADD is safe on the existing (populated) row.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4d9f2e6b1c8"
down_revision: Union[str, Sequence[str], None] = "f2a7c4e1d9b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cm_platform_accounts",
        sa.Column("live_armed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("cm_platform_accounts", "live_armed")
