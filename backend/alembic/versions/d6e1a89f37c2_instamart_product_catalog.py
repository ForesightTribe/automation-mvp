"""instamart product catalog

`POST /api/v1/products/batch`, keyed by candidate_id -- product name and
image, resolved once and cached rather than fetched on every page load.

Revision ID: d6e1a89f37c2
Revises: a3b8f21e6c94
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "d6e1a89f37c2"
down_revision: Union[str, Sequence[str], None] = "a3b8f21e6c94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instamart_product_catalog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("product_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("image_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_ipc_tenant_candidate", "instamart_product_catalog",
        ["tenant_id", "candidate_id"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_ipc_tenant_candidate", table_name="instamart_product_catalog")
    op.drop_table("instamart_product_catalog")
