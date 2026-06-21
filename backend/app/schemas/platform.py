from datetime import datetime

from pydantic import BaseModel


class PlatformStatus(BaseModel):
    platform: str
    connected: bool
    connected_at: datetime | None
