"""add received_qty balanced_qty to instamart_po_item

Revision ID: 25c398d9e16b
Revises: b60b887664f1
Create Date: 2026-09-25 17:31:00.024881

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '25c398d9e16b'
down_revision: Union[str, Sequence[str], None] = 'b60b887664f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("instamart_po_item", sa.Column("received_qty", sa.Integer(), nullable=True))
    op.add_column("instamart_po_item", sa.Column("balanced_qty", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("instamart_po_item", "balanced_qty")
    op.drop_column("instamart_po_item", "received_qty")
