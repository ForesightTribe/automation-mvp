from beanie import Document
from datetime import datetime
from typing import Optional


class User(Document):
    email: str
    hashed_password: str
    full_name: str
    tenant_id: str
    is_active: bool = True
    created_at: datetime = datetime.utcnow()

    class Settings:
        name = "users"
