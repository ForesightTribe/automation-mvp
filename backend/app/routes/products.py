"""Client-scoped product (SKU) performance. Mounted under
/clients/{client_id}/products. Private plane only (keyed on item_id)."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import ClientDep, PaginationDep, PeriodDep, SessionDep
from app.schemas.common import Page
from app.schemas.product import ProductDetail, ProductListResponse, ProductPoRow
from app.services import product_service

router = APIRouter()


@router.get("", response_model=ProductListResponse)
async def list_products(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
    search: str | None = Query(None, description="Match item name"),
    category: str | None = None,
    sort: Literal["revenue", "units", "price", "cover"] = "revenue",
    sku_status: Literal["out_of_stock", "low_cover", "no_sales", "healthy"]
    | None = Query(None, description="Filter rows to one health status."),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await product_service.get_products(
        session,
        tenant_id=client.id,
        pagination=pagination,
        period=period,
        marketplaces=mps,
        search=search,
        category=category,
        sort=sort,
        status=sku_status,
    )


@router.get("/{item_id}", response_model=ProductDetail)
async def product_detail(
    session: SessionDep,
    client: ClientDep,
    item_id: str,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    data = await product_service.get_product_detail(
        session,
        tenant_id=client.id,
        item_id=item_id,
        period=period,
        marketplaces=mps,
    )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    return data


@router.get("/{item_id}/pos", response_model=Page[ProductPoRow])
async def product_pos(
    session: SessionDep,
    client: ClientDep,
    item_id: str,
    pagination: PaginationDep,
):
    return await product_service.get_product_pos(
        session,
        tenant_id=client.id,
        item_id=item_id,
        pagination=pagination,
    )
