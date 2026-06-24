"""add user role

Adds `users.role` ('admin' | 'member') for in-account authorization.
New users default to 'member'; the first user of an account (created via
`cli account create`) is an 'admin'. Existing users all predate this column and
were each created as their account's admin, so they are backfilled to 'admin'.

Revision ID: d5f8a2c1b6e9
Revises: e428162c451f
Create Date: 2026-06-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "d5f8a2c1b6e9"
down_revision: Union[str, Sequence[str], None] = "e428162c451f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default lets the NOT NULL column be added to a populated table.
    op.add_column(
        "users",
        sa.Column(
            "role",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="member",
        ),
    )
    # Existing users were each created as their account's admin.
    op.execute("UPDATE users SET role = 'admin'")


def downgrade() -> None:
    op.drop_column("users", "role")
