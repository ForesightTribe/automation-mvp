"""sku_map — bridge private item_id to public platform_product_id

The two Blinkit id systems (seller `item_id` vs consumer `platform_product_id`)
share no key, so this table is built by normalized name matching (auto) + manual
confirmation. `platform_product_id` is NULL until matched.

Revision ID: f5b3d8e1c4a2
Revises: e2a7c9d5b1f4
Create Date: 2026-07-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "f5b3d8e1c4a2"
down_revision: Union[str, Sequence[str], None] = "e2a7c9d5b1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sku_map",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("platform_product_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("item_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("product_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("unit", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("match_method", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "item_id", name="uq_skumap_tenant_item"),
    )
    op.create_index("idx_skumap_tenant_pid", "sku_map", ["tenant_id", "platform_product_id"])


def downgrade() -> None:
    op.drop_index("idx_skumap_tenant_pid", table_name="sku_map")
    op.drop_table("sku_map")
