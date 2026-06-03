from fastapi import APIRouter, Depends
from app.api.deps import get_current_user

router = APIRouter()


@router.get("/")
async def list_campaigns(user=Depends(get_current_user)):
    pass


@router.get("/performance")
async def get_ad_performance(user=Depends(get_current_user)):
    pass
