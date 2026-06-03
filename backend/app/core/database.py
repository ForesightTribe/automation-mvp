from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings

client: AsyncIOMotorClient = None


async def connect_db():
    global client
    client = AsyncIOMotorClient(settings.MONGODB_URL)

    from app.models.user import User
    from app.models.tenant import Tenant
    from app.models.product import Product
    from app.models.sales import Sales
    from app.models.inventory import Inventory
    from app.models.scrape_job import ScrapeJob

    await init_beanie(
        database=client[settings.DB_NAME],
        document_models=[User, Tenant, Product, Sales, Inventory, ScrapeJob],
    )


async def close_db():
    global client
    if client:
        client.close()
