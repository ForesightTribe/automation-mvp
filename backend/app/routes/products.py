from fastapi import APIRouter, Depends
from app.dependencies import get_current_user

router = APIRouter()


@router.get("/")
async def list_products(user=Depends(get_current_user)):
    pass


@router.get("/{product_id}")
async def get_product(product_id: str, user=Depends(get_current_user)):
    pass
