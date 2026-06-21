import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: str
    dashboard: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    records_written: int
    created_at: datetime
