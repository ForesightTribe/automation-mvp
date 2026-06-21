"""Client-scoped product (SKU) performance. Mounted under
/clients/{client_id}/products."""
from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.common import Page
from app.schemas.product import ProductDetail, ProductListRow
from app.services import product_service

router = APIRouter()


@router.get("", response_model=Page[ProductListRow])
async def list_products(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    days: int = Query(30, ge=1, le=365),
    search: str | None = Query(None, description="Match item name"),
    category: str | None = None,
):
    return await product_service.get_products(
        session,
        tenant_id=client.id,
        pagination=pagination,
        days=days,
        search=search,
        category=category,
    )


@router.get("/{item_id}", response_model=ProductDetail)
async def product_detail(
    session: SessionDep,
    client: ClientDep,
    item_id: str,
    days: int = Query(30, ge=1, le=365),
):
    data = await product_service.get_product_detail(
        session, tenant_id=client.id, item_id=item_id, days=days
    )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    return data
