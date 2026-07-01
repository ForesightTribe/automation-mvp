"""public scraper per-tenant schema

Phase 1 of the public-scraper refactor (docs/public-scraper-refactor.md).

- drop dead/superseded tables: search_results, competitor_rankings,
  scraped_products, brand_snapshots (clean break — no data preserved)
- create header+detail storage: search_snapshots + search_listings (per-tenant)
- create shared location reference: marketplace_locations
- create per-tenant location selection: tenant_locations
- inventory_depth: add tenant_id + job_id (write path wired in a later phase)
- tenant_watchlist: add aliases (brand-name variants for classification)

Revision ID: f3a9c1d7b2e5
Revises: adcf3ccd495b
Create Date: 2026-06-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "f3a9c1d7b2e5"
down_revision: Union[str, Sequence[str], None] = "adcf3ccd495b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Drop dead / superseded public-data tables (clean break) ──────────────
    op.drop_index("idx_sr_zone", table_name="search_results")
    op.drop_index("idx_sr_scraped", table_name="search_results")
    op.drop_index("idx_sr_keyword", table_name="search_results")
    op.drop_index("idx_sr_city", table_name="search_results")
    op.drop_index("idx_sr_brand_mp", table_name="search_results")
    op.drop_table("search_results")

    op.drop_index("idx_cr_competitor", table_name="competitor_rankings")
    op.drop_index("idx_cr_brand", table_name="competitor_rankings")
    op.drop_table("competitor_rankings")

    op.drop_table("scraped_products")
    op.drop_table("brand_snapshots")

    # ── search_snapshots — per-search header ─────────────────────────────────
    op.create_table(
        "search_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("brand_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("mp_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("keyword", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("zone", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pincode", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.Column("brand_rank", sa.Integer(), nullable=True),
        sa.Column("brand_sov", sa.Float(), nullable=True),
        sa.Column("total_results", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["scrape_jobs.id"]),
        sa.ForeignKeyConstraint(["brand_slug"], ["brands.slug"]),
        sa.ForeignKeyConstraint(["mp_slug"], ["marketplaces.slug"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_snap_tenant_kw", "search_snapshots",
        ["tenant_id", "mp_slug", "keyword", "scraped_at"], unique=False,
    )
    op.create_index(
        "idx_snap_tenant_brand", "search_snapshots",
        ["tenant_id", "brand_slug", "scraped_at"], unique=False,
    )
    op.create_index("idx_snap_scraped", "search_snapshots", ["scraped_at"], unique=False)

    # ── search_listings — per-product detail ─────────────────────────────────
    op.create_table(
        "search_listings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("mp_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("brand_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("keyword", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("zone", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pincode", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("product_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_brand", sa.Boolean(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("mrp", sa.Float(), nullable=True),
        sa.Column("discount_pct", sa.Float(), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.Column("inventory", sa.Integer(), nullable=True),
        sa.Column("platform_product_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["snapshot_id"], ["search_snapshots.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["scrape_jobs.id"]),
        sa.ForeignKeyConstraint(["brand_slug"], ["brands.slug"]),
        sa.ForeignKeyConstraint(["mp_slug"], ["marketplaces.slug"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_listing_tenant_kw", "search_listings",
        ["tenant_id", "mp_slug", "keyword", "scraped_at"], unique=False,
    )
    op.create_index("idx_listing_snapshot", "search_listings", ["snapshot_id"], unique=False)
    op.create_index(
        "idx_listing_tenant_brand", "search_listings",
        ["tenant_id", "brand_slug", "scraped_at"], unique=False,
    )

    # ── marketplace_locations — shared serviceability reference ──────────────
    op.create_table(
        "marketplace_locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mp_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("zone", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pincode", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["mp_slug"], ["marketplaces.slug"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mp_slug", "city", "zone", "pincode", name="uq_mploc_mp_zone"),
    )
    op.create_index("idx_mploc_mp_city", "marketplace_locations", ["mp_slug", "city"], unique=False)

    # ── tenant_locations — per-tenant location selection ─────────────────────
    op.create_table(
        "tenant_locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("mp_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["mp_slug"], ["marketplaces.slug"]),
        sa.ForeignKeyConstraint(["location_id"], ["marketplace_locations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "location_id", name="uq_tenant_location"),
    )
    op.create_index("idx_tenloc_tenant_mp", "tenant_locations", ["tenant_id", "mp_slug"], unique=False)

    # ── inventory_depth — provision per-tenant columns ───────────────────────
    op.add_column("inventory_depth", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.add_column("inventory_depth", sa.Column("job_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_inv_tenant", "inventory_depth", "tenants", ["tenant_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_inv_job", "inventory_depth", "scrape_jobs", ["job_id"], ["id"]
    )
    op.create_index("idx_inv_tenant", "inventory_depth", ["tenant_id", "scraped_at"], unique=False)

    # ── tenant_watchlist — add aliases ───────────────────────────────────────
    op.add_column(
        "tenant_watchlist",
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade() -> None:
    op.drop_column("tenant_watchlist", "aliases")

    op.drop_index("idx_inv_tenant", table_name="inventory_depth")
    op.drop_constraint("fk_inv_job", "inventory_depth", type_="foreignkey")
    op.drop_constraint("fk_inv_tenant", "inventory_depth", type_="foreignkey")
    op.drop_column("inventory_depth", "job_id")
    op.drop_column("inventory_depth", "tenant_id")

    op.drop_index("idx_tenloc_tenant_mp", table_name="tenant_locations")
    op.drop_table("tenant_locations")

    op.drop_index("idx_mploc_mp_city", table_name="marketplace_locations")
    op.drop_table("marketplace_locations")

    op.drop_index("idx_listing_tenant_brand", table_name="search_listings")
    op.drop_index("idx_listing_snapshot", table_name="search_listings")
    op.drop_index("idx_listing_tenant_kw", table_name="search_listings")
    op.drop_table("search_listings")

    op.drop_index("idx_snap_scraped", table_name="search_snapshots")
    op.drop_index("idx_snap_tenant_brand", table_name="search_snapshots")
    op.drop_index("idx_snap_tenant_kw", table_name="search_snapshots")
    op.drop_table("search_snapshots")

    # ── Recreate the dropped tables (original DDL) ───────────────────────────
    op.create_table(
        "brand_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brand_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("mp_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["brand_slug"], ["brands.slug"]),
        sa.ForeignKeyConstraint(["mp_slug"], ["marketplaces.slug"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "scraped_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brand_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("mp_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("sku", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("keyword", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["brand_slug"], ["brands.slug"]),
        sa.ForeignKeyConstraint(["mp_slug"], ["marketplaces.slug"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "competitor_rankings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brand_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("mp_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("zone", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pincode", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("keyword", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.Column("competitor", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["brand_slug"], ["brands.slug"]),
        sa.ForeignKeyConstraint(["mp_slug"], ["marketplaces.slug"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_cr_brand", "competitor_rankings", ["brand_slug", "city", "keyword"], unique=False)
    op.create_index("idx_cr_competitor", "competitor_rankings", ["competitor", "city", "mp_slug"], unique=False)

    op.create_table(
        "search_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brand_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("mp_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("zone", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pincode", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("keyword", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("merchant_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("store_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.Column("brand_rank", sa.Integer(), nullable=True),
        sa.Column("brand_sov", sa.Float(), nullable=True),
        sa.Column("total_results", sa.Integer(), nullable=True),
        sa.Column("products", sa.JSON(), nullable=True),
        sa.Column("competitors", sa.JSON(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["brand_slug"], ["brands.slug"]),
        sa.ForeignKeyConstraint(["mp_slug"], ["marketplaces.slug"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sr_brand_mp", "search_results", ["brand_slug", "mp_slug"], unique=False)
    op.create_index("idx_sr_city", "search_results", ["brand_slug", "city"], unique=False)
    op.create_index("idx_sr_keyword", "search_results", ["brand_slug", "keyword", "city"], unique=False)
    op.create_index("idx_sr_scraped", "search_results", ["scraped_at"], unique=False)
    op.create_index("idx_sr_zone", "search_results", ["brand_slug", "city", "zone"], unique=False)
