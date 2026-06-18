from fastapi import APIRouter, Depends
from app.dependencies import get_current_user

router = APIRouter()


@router.get("/overview")
async def get_overview(user=Depends(get_current_user)):
    pass


@router.get("/revenue")
async def get_revenue(user=Depends(get_current_user)):
    pass
