import math
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.dependencies import Pagination

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Generic paginated envelope used as a `response_model`, e.g.

        @router.get("/", response_model=Page[CompetitorRankRow])
    """

    items: list[T]
    total: int
    page: int
    limit: int
    pages: int

    @classmethod
    def build(cls, items: list[T], total: int, pagination: Pagination) -> "Page[T]":
        return cls(
            items=items,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            pages=math.ceil(total / pagination.limit) if total else 0,
        )
