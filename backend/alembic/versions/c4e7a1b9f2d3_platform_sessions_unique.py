"""unique constraint on platform_sessions (tenant_id, platform)

The session upsert in scraper/utils/session.py relies on
ON CONFLICT (tenant_id, platform), which requires a matching unique
constraint. Add it so a tenant has at most one session row per platform.

Revision ID: c4e7a1b9f2d3
Revises: b3d9f1c2a7e4
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4e7a1b9f2d3"
down_revision: Union[str, Sequence[str], None] = "b3d9f1c2a7e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_platform_sessions_tenant_platform",
        "platform_sessions",
        ["tenant_id", "platform"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_platform_sessions_tenant_platform",
        "platform_sessions",
        type_="unique",
    )
