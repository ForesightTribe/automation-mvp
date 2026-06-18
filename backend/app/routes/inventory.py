from fastapi import APIRouter, Depends
from app.dependencies import get_current_user

router = APIRouter()


@router.get("/")
async def list_inventory(user=Depends(get_current_user)):
    pass
