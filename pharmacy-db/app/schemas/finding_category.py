from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FindingCategoryCreate(BaseModel):
    regulatory_body_id: UUID
    full_path: str


class FindingCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    regulatory_body_id: UUID
    full_path: str
    parent: str | None
    child: str | None
    created_at: datetime
    updated_at: datetime