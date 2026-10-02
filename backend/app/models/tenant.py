import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, JSON, UniqueConstraint

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class Tenant(SQLModel, table=True):
    """A Client — the managed brand/seller and data unit. Belongs to an Account."""

    __tablename__ = "tenants"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id")
    name: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=now_ist)


class User(SQLModel, table=True):
    """A person who logs in. Belongs to an Account, can act on its Clients."""

    __tablename__ = "users"

    __table_args__ = (Index("idx_users_account", "account_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id")
    email: str = Field(unique=True, index=True)
    hashed_password: str
    full_name: str
    role: str = Field(default="member")  # 'admin' | 'member'
    is_active: bool = True
    created_at: datetime = Field(default_factory=now_ist)


class TenantWatchlist(SQLModel, table=True):
    __tablename__ = "tenant_watchlist"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    brand_slug: str = Field(foreign_key="brands.slug")
    relationship: str = Field(default="own")  # 'own' | 'competitor'
    # Brand-name variants used to match products to this brand during scraping
    # (e.g. ["dobra", "dobra cola"]). Drives brand-vs-competitor classification.
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    cities: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    marketplaces: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # ⚠️ RETIRED 2026-10-02 — read nothing from these. The caps are per MARKETPLACE now
    # (`TenantWatchlistCap`). The columns stay only until production runs the new code,
    # then a later migration drops them; no code writes or reads them any more.
    keyword_cap: int | None = None
    brand_cap: int | None = None
    created_at: datetime = Field(default_factory=now_ist)
    updated_at: datetime = Field(default_factory=now_ist)


class TenantWatchlistCap(SQLModel, table=True):
    """How deep one tracked brand's searches go on ONE marketplace (2026-10-02).

    The two caps used to sit on the watchlist row, one value for every marketplace. But a
    cap is a number of results, and each marketplace pages differently — Blinkit 12 a page
    (so 36 / 48), Zepto 30 a page (so 30 / 60). One number cannot fit both: Sereko's
    Blinkit-shaped 36 on Zepto fetched two pages and threw 24 rows away on every search.

      keyword_cap  the category-keyword scrape (SoV / rank) — `public-run`
      brand_cap    the brand-query own-SKU scrape (whole own catalog) — `public-skus`, and
                   the bid engine's stock check

    NULL (or no row) → the marketplace's own floor (`scraper/public/providers.py`). Own
    brands only — nothing reads a competitor's caps. Set from the config workbook's `caps`
    sheet; read through `scraper/public/caps.py`, never directly.
    """

    __tablename__ = "tenant_watchlist_caps"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "mp_slug", name="uq_tenant_watchlist_caps"),
    )

    id: int | None = Field(default=None, primary_key=True)
    watchlist_id: int = Field(foreign_key="tenant_watchlist.id", ondelete="CASCADE",
                              index=True)
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    keyword_cap: int | None = None
    brand_cap: int | None = None
    created_at: datetime = Field(default_factory=now_ist)
    updated_at: datetime = Field(default_factory=now_ist)
