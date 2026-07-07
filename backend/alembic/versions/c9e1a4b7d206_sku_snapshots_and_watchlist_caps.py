"""sku_snapshots table + tenant_watchlist per-scrape caps

Targeted own-SKU scrape storage (append-only, keyed on platform_product_id) plus
two per-tenant cap knobs on the watchlist: keyword_cap (category-keyword scrape)
and brand_cap (brand-query targeted scrape). Both nullable — code applies a
default when absent; meaningful on 'own' rows.

Revision ID: c9e1a4b7d206
Revises: b8d2f4a6c1e3
Create Date: 2026-07-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "c9e1a4b7d206"
down_revision: Union[str, Sequence[str], None] = "b8d2f4a6c1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sku_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("mp_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("brand_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("platform_product_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("product_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("merchant_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("mrp", sa.Float(), nullable=True),
        sa.Column("discount_pct", sa.Float(), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("inventory", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["scrape_jobs.id"]),
        sa.ForeignKeyConstraint(["mp_slug"], ["marketplaces.slug"]),
        sa.ForeignKeyConstraint(["brand_slug"], ["brands.slug"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sku_tenant_product", "sku_snapshots",
                    ["tenant_id", "platform_product_id", "scraped_at"])
    op.create_index("idx_sku_tenant_store", "sku_snapshots",
                    ["tenant_id", "merchant_id", "scraped_at"])
    op.create_index("idx_sku_scraped", "sku_snapshots", ["scraped_at"])

    op.add_column("tenant_watchlist", sa.Column("keyword_cap", sa.Integer(), nullable=True))
    op.add_column("tenant_watchlist", sa.Column("brand_cap", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_watchlist", "brand_cap")
    op.drop_column("tenant_watchlist", "keyword_cap")

    op.drop_index("idx_sku_scraped", table_name="sku_snapshots")
    op.drop_index("idx_sku_tenant_store", table_name="sku_snapshots")
    op.drop_index("idx_sku_tenant_product", table_name="sku_snapshots")
    op.drop_table("sku_snapshots")
