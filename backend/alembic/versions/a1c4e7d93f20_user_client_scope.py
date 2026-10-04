"""per-user client scoping: users.client_scope + user_clients

Revision ID: a1c4e7d93f20
Revises: 335b665ed095
Create Date: 2026-10-04

Adds `users.client_scope` ('all' | 'listed') and `user_clients`. Existing rows
backfill to 'all', so every current login keeps the access it has today.

⚠️ HAND-WRITTEN. The shared database carries tables from branches not merged
here, so `--autogenerate` emits DROP TABLE for them. Keep editing by hand.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'a1c4e7d93f20'
down_revision: Union[str, Sequence[str], None] = '335b665ed095'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default pins existing rows to 'all' in the same statement, and lets
    # older code INSERT a user without naming the column.
    op.add_column(
        'users',
        sa.Column(
            'client_scope',
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default='all',
        ),
    )
    op.create_table(
        'user_clients',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'tenant_id'),
    )
    op.create_index('idx_user_clients_user', 'user_clients', ['user_id'])


def downgrade() -> None:
    """Downgrade schema. ⚠️ Drops every grant, so a 'listed' user becomes 'all'."""
    op.drop_index('idx_user_clients_user', table_name='user_clients')
    op.drop_table('user_clients')
    op.drop_column('users', 'client_scope')
