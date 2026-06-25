from fastapi import APIRouter
from app.routes import auth, clients, reference, analytics, overview, products, inventory, scorecard, competition, ads, platforms, watchlist, jobs, purchase_orders

api_router = APIRouter()

api_router.include_router(auth.router,        prefix="/auth",        tags=["auth"])
api_router.include_router(clients.router,     prefix="/clients",     tags=["clients"])
api_router.include_router(reference.router,   prefix="/reference",   tags=["reference"])
api_router.include_router(analytics.router,   prefix="/clients/{client_id}/analytics", tags=["analytics"])
api_router.include_router(overview.router,     prefix="/clients/{client_id}/overview", tags=["overview"])
api_router.include_router(products.router,    prefix="/clients/{client_id}/products", tags=["products"])
api_router.include_router(inventory.router,   prefix="/clients/{client_id}/inventory", tags=["inventory"])
api_router.include_router(scorecard.router,   prefix="/clients/{client_id}/scorecard", tags=["scorecard"])
api_router.include_router(watchlist.router,   prefix="/clients/{client_id}/watchlist", tags=["watchlist"])
api_router.include_router(jobs.router,        prefix="/clients/{client_id}/jobs", tags=["jobs"])
api_router.include_router(purchase_orders.router, prefix="/clients/{client_id}/purchase-orders", tags=["purchase-orders"])
api_router.include_router(competition.router, prefix="/clients/{client_id}/competition", tags=["competition"])
api_router.include_router(ads.router,         prefix="/clients/{client_id}/ads", tags=["ads"])
api_router.include_router(platforms.router,   prefix="/clients/{client_id}/platforms", tags=["platforms"])
