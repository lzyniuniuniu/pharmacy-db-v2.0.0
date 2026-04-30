from datetime import datetime 
from uuid import UUID

from pydantic import BaseModel, ConfigDict

class RegulatoryBodyCreate(BaseModel):
    """Shape of a request to create a regulatory body."""
    name: str
    short_name: str
    jurisdiction: str | None = None

class RegulatoryBodyRead(BaseModel):
    """Shape of a regulatory body returned by the API."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    short_name: str
    jurisdiction: str | None
    created_at: datetime
    updated_at: datetime

   