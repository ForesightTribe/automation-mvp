import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.time import now_ist


class Account(SQLModel, table=True):
    """The subscriber org that logs in and pays.

    An agency (many clients) or a direct seller (one client). Users belong to
    an Account; Clients (the `tenants` table) belong to an Account.
    """

    __tablename__ = "accounts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    type: str = Field(default="agency")  # 'agency' | 'direct'
    is_active: bool = True
    created_at: datetime = Field(default_factory=now_ist)
