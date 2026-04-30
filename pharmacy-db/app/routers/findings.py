from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.assessment import Assessment
from app.models.case import Case
from app.models.finding import Finding
from app.models.finding_category import FindingCategory
from app.schemas.finding import (
    CategoryBrief,
    FindingCreate,
    FindingRead,
    FindingUpdate,
)

router = APIRouter(prefix="/findings", tags=["findings"])


def _to_read(finding: Finding) -> FindingRead:
    """Assemble a FindingRead, including the nested category if present."""
    return FindingRead(
        id=finding.id,
        assessment_id=finding.assessment_id,
        case_id=finding.case_id,
        source_document_id=finding.source_document_id,
        ordinal=finding.ordinal,
        identified_date=finding.identified_date,
        due_date=finding.due_date,
        completed_date=finding.completed_date,
        state=finding.state,
        person_responsible=finding.person_responsible,
        category_raw=finding.category_raw,
        category=CategoryBrief.model_validate(finding.category) if finding.category else None,
        description_verbatim=finding.description_verbatim,
        description_summary=finding.description_summary,
        summary_bullets=finding.summary_bullets,
        referenced_standards=finding.referenced_standards,
        referenced_urls=finding.referenced_urls,
        source_page_numbers=finding.source_page_numbers,
        created_at=finding.created_at,
        updated_at=finding.updated_at,
    )


@router.get("", response_model=list[FindingRead])
def list_findings(
    case_id: UUID | None = Query(default=None),
    assessment_id: UUID | None = Query(default=None),
    category_id: UUID | None = Query(default=None),
    state: str | None = Query(default=None),
    search: str | None = Query(
        default=None,
        description="Full-text search across description_verbatim. "
                    "Supports stemming and stopword removal.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List findings, with optional filters and full-text search."""
    query = db.query(Finding)

    if case_id is not None:
        query = query.filter(Finding.case_id == case_id)
    if assessment_id is not None:
        query = query.filter(Finding.assessment_id == assessment_id)
    if category_id is not None:
        query = query.filter(Finding.category_id == category_id)
    if state is not None:
        query = query.filter(Finding.state == state)
    if search is not None and search.strip():
        # Use the GIN-indexed tsvector column for full-text search
        query = query.filter(
            text("description_tsv @@ plainto_tsquery('english', :q)")
        ).params(q=search)

    findings = (
        query.order_by(Finding.case_id, Finding.assessment_id, Finding.ordinal)
        .limit(limit)
        .all()
    )
    return [_to_read(f) for f in findings]


@router.post("", response_model=FindingRead, status_code=status.HTTP_201_CREATED)
def create_finding(payload: FindingCreate, db: Session = Depends(get_db)):
    # Verify all the FKs exist before insert
    assessment = db.get(Assessment, payload.assessment_id)
    if assessment is None:
        raise HTTPException(404, "assessment_id does not exist")
    if db.get(Case, payload.case_id) is None:
        raise HTTPException(404, "case_id does not exist")
    if assessment.case_id != payload.case_id:
        raise HTTPException(
            400,
            "case_id does not match the assessment's case_id",
        )
    if payload.category_id is not None and db.get(FindingCategory, payload.category_id) is None:
        raise HTTPException(404, "category_id does not exist")

    data = payload.model_dump()
    # Convert Pydantic StandardReferenceSchema list back to plain dicts for JSONB
    if data.get("referenced_standards") is not None:
        # model_dump already handled the conversion; this is just being explicit
        pass

    finding = Finding(**data)
    db.add(finding)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A finding with this ordinal already exists in this assessment",
        )
    db.refresh(finding)
    return _to_read(finding)


@router.get("/{finding_id}", response_model=FindingRead)
def get_finding(finding_id: UUID, db: Session = Depends(get_db)):
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _to_read(finding)


@router.patch("/{finding_id}", response_model=FindingRead)
def update_finding(finding_id: UUID, payload: FindingUpdate, db: Session = Depends(get_db)):
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    update_data = payload.model_dump(exclude_unset=True)

    # Validate category_id change if present
    if "category_id" in update_data and update_data["category_id"] is not None:
        if db.get(FindingCategory, update_data["category_id"]) is None:
            raise HTTPException(404, "category_id does not exist")

    for field, value in update_data.items():
        setattr(finding, field, value)
    db.commit()
    db.refresh(finding)
    return _to_read(finding)