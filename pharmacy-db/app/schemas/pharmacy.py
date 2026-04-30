from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PharmacyCreate(BaseModel):
    """Request payload to create a pharmacy."""

    regulatory_body_id: UUID
    license_number: str | None = None
    name: str | None = None

class PharmacyUpdate(BaseModel):
    """Request payload to update a pharmacy. All fields optional."""
    license_number: str | None = None
    name: str | None = None


class PharmacyRead(BaseModel):
    """Pharmacy as returned by the API."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    regulatory_body_id: UUID
    license_number: str | None
    name: str | None
    created_at: datetime
    updated_at: datetime