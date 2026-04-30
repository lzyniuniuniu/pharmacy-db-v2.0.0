from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

class LicenseeRead(BaseModel):
    """Snapshot of the licensee at the time of the case"""
    name: str | None
    email: str | None

class ConsultantRead(BaseModel):
    """The inspector assigned to the case."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: str | None
    role: str | None


class CaseCreate(BaseModel):
    case_number: str
    regulatory_body_id: UUID
    pharmacy_id: UUID | None = None
    consultant_id: UUID | None = None
    case_type: str | None = None
    case_state: str | None = None
    case_closed_date: date | None = None
    licensee_name: str | None = None
    licensee_email: EmailStr | None = None
    consultant_assignment_status: str = "unknown"
    notes: str | None = None

class CaseUpdate(BaseModel):
    """Updates to a case. Most fields are mutable;
        case_number and regulatory_body_id are not (they're identity)
    """
    pharmacy_id: UUID | None = None
    consultant_id: UUID | None = None
    case_type: str | None = None
    case_state: str | None = None
    case_closed_date: date | None = None
    licensee_name: str | None = None
    licensee_email: EmailStr | None = None
    consultant_assignment_status: str | None = None
    notes: str | None = None


class CaseRead(BaseModel):
    """Case as returned by the API. Licensee fields are nested; consultant
    is nested with the full inspector record."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_number: str
    regulatory_body_id: UUID
    pharmacy_id: UUID | None
    case_type: str | None
    case_state: str | None
    case_closed_date: date | None
    consultant_assignment_status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

    # Nested objects assembled by a custom builder (see router)
    licensee: LicenseeRead
    consultant: ConsultantRead | None

    @model_validator(mode="before")
    @classmethod
    def _build_nested_from_orm(cls, data: Any) -> Any:
        """Allow construction directly from a Case ORM instance.

        Synthesizes the nested `licensee` from the flat licensee_name /
        licensee_email columns, and pulls `consultant` off the relationship.
        Falls through unchanged for plain dict input (so test payloads
        and JSON bodies still work).
        """
        if isinstance(data, dict):
            return data
        # Treat as ORM-like object
        return {
            "id": data.id,
            "case_number": data.case_number,
            "regulatory_body_id": data.regulatory_body_id,
            "pharmacy_id": data.pharmacy_id,
            "case_type": data.case_type,
            "case_state": data.case_state,
            "case_closed_date": data.case_closed_date,
            "consultant_assignment_status": data.consultant_assignment_status,
            "notes": data.notes,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
            "licensee": {
                "name": data.licensee_name,
                "email": data.licensee_email,
            },
            "consultant": data.consultant,
        }