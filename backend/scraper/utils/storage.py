from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def make_upsert_key(*parts: Any) -> str:
    return ":".join(str(p) for p in parts)


_MP_NAMES = {
    "blinkit":   "Blinkit",
    "instamart": "Instamart",
    "zepto":     "Zepto",
}


async def ensure_refs(session: AsyncSession, brand_slug: str, mp_slug: str) -> None:
    await session.execute(
        text(
            "INSERT INTO brands (slug, name, metadata) VALUES (:slug, :name, '{}') "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": brand_slug, "name": brand_slug.replace("-", " ").title()},
    )
    await session.execute(
        text(
            "INSERT INTO marketplaces (slug, name) VALUES (:slug, :name) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": mp_slug, "name": _MP_NAMES.get(mp_slug, mp_slug.title())},
    )
