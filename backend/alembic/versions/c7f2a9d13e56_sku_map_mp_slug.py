"""sku_map — add mp_slug so multi-marketplace tenants don't collide

`sku_map` had one row per (tenant, item_id) with no marketplace on it. That
was fine while a tenant sold on at most one of Blinkit/Zepto, but Brik Oven
now sells on all three (Blinkit, Zepto, Instamart) and the auto-matcher's
public-product index was built from ALL marketplaces' listings by name alone
— an Instamart private SKU could match a Zepto public listing of the same
product name and get written into the same slot a Zepto row would use.

Backfills mp_slug for the 29 existing rows by checking which private source
table (blinkit_seller_sales / zepto_seller_sales) each item_id came from —
the only two sources that existed before Instamart was added. Widens the
unique constraint from (tenant_id, item_id) to (tenant_id, mp_slug, item_id):
a pure superset, so it can never reject an insert the old constraint accepted.

Revision ID: c7f2a9d13e56
Revises: b1e4c7a9d20f
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "c7f2a9d13e56"
down_revision: Union[str, Sequence[str], None] = "b1e4c7a9d20f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='blinkit' (not '') because mp_slug carries a FK to
    # marketplaces.slug — '' would violate it. 'blinkit' matches what any
    # not-yet-updated caller on another branch was implicitly assuming anyway
    # (it's the only source the table's very first version supported).
    op.add_column(
        "sku_map",
        sa.Column(
            "mp_slug", sqlmodel.sql.sqltypes.AutoString(),
            nullable=False, server_default="blinkit",
        ),
    )
    op.create_foreign_key(
        "fk_skumap_mp_slug", "sku_map", "marketplaces", ["mp_slug"], ["slug"],
    )

    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE sku_map sm SET mp_slug = 'zepto'
        WHERE EXISTS (
            SELECT 1 FROM zepto_seller_sales z
            WHERE z.product_variant_id = sm.item_id
        )
    """))
    # blinkit needs no UPDATE: every existing row is already 'blinkit' via the
    # server_default, and the diagnostic query confirmed 0 rows are unaccounted
    # for (20 blinkit-sourced + 9 zepto-sourced = all 29).

    op.drop_constraint("uq_skumap_tenant_item", "sku_map", type_="unique")
    op.create_unique_constraint(
        "uq_skumap_tenant_mp_item", "sku_map", ["tenant_id", "mp_slug", "item_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_skumap_tenant_mp_item", "sku_map", type_="unique")
    op.create_unique_constraint(
        "uq_skumap_tenant_item", "sku_map", ["tenant_id", "item_id"],
    )
    op.drop_constraint("fk_skumap_mp_slug", "sku_map", type_="foreignkey")
    op.drop_column("sku_map", "mp_slug")
