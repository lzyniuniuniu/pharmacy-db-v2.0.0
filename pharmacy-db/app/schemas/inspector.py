from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class InspectorCreate(BaseModel):
    regulatory_body_id: UUID
    full_name: str | None = None
    email: EmailStr | None = None
    role: str | None = None

class InspectorUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    role: str | None = None

class InspectorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    regulatory_body_id: UUID
    full_name: str | None = None
    email: EmailStr | None = None
    role: str | None = None
    created_at: datetime    
    updated_at: datetime