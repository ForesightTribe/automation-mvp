from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ProductOut(BaseModel):
    id: str
    platform: str
    name: str
    sku: str
    category: str
    price: float
    mrp: float
    scraped_at: datetime
