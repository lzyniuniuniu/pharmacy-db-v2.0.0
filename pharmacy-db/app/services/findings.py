from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.finding import Finding


def get_or_create_finding(
    db: Session,
    *,
    assessment_id: UUID,
    case_id: UUID,
    ordinal: int,
    description_verbatim: str,
    category_id: UUID | None = None,
    source_document_id: UUID | None = None,
    identified_date: date | None = None,
    due_date: date | None = None,
    completed_date: date | None = None,
    state: str | None = None,
    person_responsible: str | None = None,
    category_raw: str | None = None,
    referenced_standards: list[dict[str, Any]] | None = None,
    referenced_urls: list[str] | None = None,
    source_page_numbers: list[int] | None = None,
) -> Finding:
    """Find a finding by (assessment_id, ordinal), creating if missing.

    On match, updates fields that came from extraction (description, dates,
    state, etc.). Does not touch summary fields (description_summary,
    summary_bullets) — those are populated by the LLM step downstream and
    re-running the loader shouldn't clobber them.
    """
    existing = (
        db.query(Finding)
        .filter_by(assessment_id=assessment_id, ordinal=ordinal)
        .one_or_none()
    )
    if existing is not None:
        existing.description_verbatim = description_verbatim
        existing.category_id = category_id
        existing.source_document_id = source_document_id
        existing.identified_date = identified_date
        existing.due_date = due_date
        existing.completed_date = completed_date
        existing.state = state
        existing.person_responsible = person_responsible
        existing.category_raw = category_raw
        existing.referenced_standards = referenced_standards
        existing.referenced_urls = referenced_urls
        existing.source_page_numbers = source_page_numbers
        # Note: description_summary and summary_bullets are deliberately NOT
        # touched here. They're owned by a downstream LLM process.
        return existing

    finding = Finding(
        assessment_id=assessment_id,
        case_id=case_id,
        ordinal=ordinal,
        description_verbatim=description_verbatim,
        category_id=category_id,
        source_document_id=source_document_id,
        identified_date=identified_date,
        due_date=due_date,
        completed_date=completed_date,
        state=state,
        person_responsible=person_responsible,
        category_raw=category_raw,
        referenced_standards=referenced_standards,
        referenced_urls=referenced_urls,
        source_page_numbers=source_page_numbers,
    )
    db.add(finding)
    db.flush()
    return finding