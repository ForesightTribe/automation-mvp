from typing import Any
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class Brand(SQLModel, table=True):
    __tablename__ = "brands"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    category: str | None = None
    logo: str | None = None
    tint: str | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict, sa_column=Column("metadata", JSON, nullable=False))


class Marketplace(SQLModel, table=True):
    __tablename__ = "marketplaces"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    color: str | None = None
