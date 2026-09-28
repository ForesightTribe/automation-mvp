"""add booking slot fields to instamart_po

Revision ID: a9757fea742a
Revises: 25c398d9e16b
Create Date: 2026-09-28 13:42:17.840737

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a9757fea742a'
down_revision: Union[str, Sequence[str], None] = '25c398d9e16b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("instamart_po", sa.Column("appointment_start_date", sa.DateTime(), nullable=True))
    op.add_column("instamart_po", sa.Column("po_min_order_qty_fulfilled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("instamart_po", sa.Column("po_min_order_value_fulfilled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("instamart_po", sa.Column("supplier_multi_grn_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("instamart_po", sa.Column("pdp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("instamart_po", "pdp_enabled")
    op.drop_column("instamart_po", "supplier_multi_grn_enabled")
    op.drop_column("instamart_po", "po_min_order_value_fulfilled")
    op.drop_column("instamart_po", "po_min_order_qty_fulfilled")
    op.drop_column("instamart_po", "appointment_start_date")
