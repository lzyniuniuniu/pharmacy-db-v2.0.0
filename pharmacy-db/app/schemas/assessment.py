from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AssessmentCreate(BaseModel):
    case_id: UUID
    ordinal: int
    assessment_date: date | None = None


class AssessmentUpdate(BaseModel):
    """Updates to an assessment. case_id and ordinal are identity — not
    updatable. Only the date can change (e.g., after manual correction
    of an extraction error)."""
    assessment_date: date | None = None


class AssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    ordinal: int
    assessment_date: date | None
    created_at: datetime
    updated_at: datetime