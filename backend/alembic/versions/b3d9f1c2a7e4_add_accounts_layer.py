"""add accounts layer

Adds the Account (subscriber org) above Clients (tenants) and Users.
- new `accounts` table
- `tenants.account_id`  -> each client belongs to an account
- `users.account_id`    -> users belong to an account, not a single client
  (replaces the old `users.tenant_id`)

Revision ID: b3d9f1c2a7e4
Revises: 627daf7d24e9
Create Date: 2026-06-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "b3d9f1c2a7e4"
down_revision: Union[str, Sequence[str], None] = "627daf7d24e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Clients now belong to an account.
    op.add_column("tenants", sa.Column("account_id", sa.Uuid(), nullable=False))
    op.create_foreign_key("fk_tenants_account", "tenants", "accounts", ["account_id"], ["id"])

    # Users now belong to an account, not a single client.
    op.add_column("users", sa.Column("account_id", sa.Uuid(), nullable=False))
    op.create_foreign_key("fk_users_account", "users", "accounts", ["account_id"], ["id"])
    op.create_index("idx_users_account", "users", ["account_id"], unique=False)
    # Dropping the column also drops idx_users_tenant and the tenant_id FK.
    op.drop_column("users", "tenant_id")


def downgrade() -> None:
    op.add_column("users", sa.Column("tenant_id", sa.Uuid(), nullable=False))
    op.create_foreign_key("users_tenant_id_fkey", "users", "tenants", ["tenant_id"], ["id"])
    op.create_index("idx_users_tenant", "users", ["tenant_id"], unique=False)
    op.drop_index("idx_users_account", table_name="users")
    op.drop_constraint("fk_users_account", "users", type_="foreignkey")
    op.drop_column("users", "account_id")

    op.drop_constraint("fk_tenants_account", "tenants", type_="foreignkey")
    op.drop_column("tenants", "account_id")

    op.drop_table("accounts")
