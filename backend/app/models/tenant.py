from beanie import Document
from datetime import datetime
from typing import Optional


class Tenant(Document):
    name: str
    is_active: bool = True
    created_at: datetime = datetime.utcnow()

    class Settings:
        name = "tenants"
