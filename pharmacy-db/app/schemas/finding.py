from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StandardReferenceSchema(BaseModel):
    """One reference to a regulation/standard, as extracted from text."""
    raw_text: str
    standard_code: str | None = None
    document: str | None = None


class CategoryBrief(BaseModel):
    """Compact category info embedded in a finding response."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_path: str
    parent: str | None
    child: str | None


class FindingCreate(BaseModel):
    assessment_id: UUID
    case_id: UUID
    ordinal: int
    description_verbatim: str

    category_id: UUID | None = None
    source_document_id: UUID | None = None

    identified_date: date | None = None
    due_date: date | None = None
    completed_date: date | None = None
    state: str | None = None
    person_responsible: str | None = None
    category_raw: str | None = None

    description_summary: str | None = None
    summary_bullets: list[str] | None = None
    referenced_standards: list[StandardReferenceSchema] | None = None
    referenced_urls: list[str] | None = None
    source_page_numbers: list[int] | None = None


class FindingUpdate(BaseModel):
    """Updates to a finding. The relationships and ordinal are immutable;
    everything else is mutable, since downstream processes (LLM summarization,
    category re-resolution, page-number corrections) might update them."""
    category_id: UUID | None = None
    identified_date: date | None = None
    due_date: date | None = None
    completed_date: date | None = None
    state: str | None = None
    person_responsible: str | None = None
    description_summary: str | None = None
    summary_bullets: list[str] | None = None
    referenced_standards: list[StandardReferenceSchema] | None = None
    referenced_urls: list[str] | None = None
    source_page_numbers: list[int] | None = None


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    assessment_id: UUID
    case_id: UUID
    source_document_id: UUID | None
    ordinal: int

    identified_date: date | None
    due_date: date | None
    completed_date: date | None
    state: str | None
    person_responsible: str | None

    category_raw: str | None
    category: CategoryBrief | None  # nested object, not just an ID

    description_verbatim: str
    description_summary: str | None
    summary_bullets: list[str] | None
    
    referenced_standards: list[dict[str, Any]] | None
    referenced_urls: list[str] | None
    source_page_numbers: list[int] | None

    created_at: datetime
    updated_at: datetime