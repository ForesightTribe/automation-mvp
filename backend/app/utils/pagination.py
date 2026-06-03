import math
from fastapi import Query


class PaginationParams:
    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
    ):
        self.page = page
        self.limit = limit
        self.skip = (page - 1) * limit


def paginate(data: list, total: int, params: PaginationParams) -> dict:
    return {
        "data": data,
        "total": total,
        "page": params.page,
        "limit": params.limit,
        "total_pages": math.ceil(total / params.limit) if total > 0 else 0,
    }
