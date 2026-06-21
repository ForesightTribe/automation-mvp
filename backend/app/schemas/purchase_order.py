from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    po_number: str
    scraped_at: datetime
    raw: dict[str, Any]  # full PO payload incl. vendor + line items


class POSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    window_start: date
    scraped_at: datetime
    raw: dict[str, Any]
