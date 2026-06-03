from fastapi import APIRouter
from app.api.routes import auth, analytics, products, inventory, ads, platforms

api_router = APIRouter()

api_router.include_router(auth.router,      prefix="/auth",      tags=["auth"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(products.router,  prefix="/products",  tags=["products"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(ads.router,       prefix="/ads",       tags=["ads"])
api_router.include_router(platforms.router, prefix="/platforms", tags=["platforms"])
