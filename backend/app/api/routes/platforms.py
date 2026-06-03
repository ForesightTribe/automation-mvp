from fastapi import APIRouter, Depends
from app.api.deps import get_current_user

router = APIRouter()


@router.get("/")
async def list_platforms(user=Depends(get_current_user)):
    pass


@router.post("/{platform}/connect")
async def connect_platform(platform: str, user=Depends(get_current_user)):
    pass


@router.delete("/{platform}/disconnect")
async def disconnect_platform(platform: str, user=Depends(get_current_user)):
    pass
