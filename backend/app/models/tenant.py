import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, JSON
from sqlmodel import Field, SQLModel


class Tenant(SQLModel, table=True):
    """A Client — the managed brand/seller and data unit. Belongs to an Account."""

    __tablename__ = "tenants"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id")
    name: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    """A person who logs in. Belongs to an Account, can act on its Clients."""

    __tablename__ = "users"

    __table_args__ = (Index("idx_users_account", "account_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id")
    email: str = Field(unique=True, index=True)
    hashed_password: str
    full_name: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TenantWatchlist(SQLModel, table=True):
    __tablename__ = "tenant_watchlist"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    brand_slug: str = Field(foreign_key="brands.slug")
    relationship: str = Field(default="own")  # 'own' | 'competitor'
    cities: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    marketplaces: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
