from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.assessment import Assessment
from app.models.case import Case
from app.schemas.assessment import AssessmentCreate, AssessmentRead, AssessmentUpdate

router = APIRouter(prefix="/assessments", tags=["assessments"])


@router.get("", response_model=list[AssessmentRead])
def list_assessments(
    case_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """List assessments, optionally filtered by case."""
    query = db.query(Assessment)
    if case_id is not None:
        query = query.filter(Assessment.case_id == case_id)
    return query.order_by(Assessment.case_id, Assessment.ordinal).all()


@router.post("", response_model=AssessmentRead, status_code=status.HTTP_201_CREATED)
def create_assessment(payload: AssessmentCreate, db: Session = Depends(get_db)):
    if db.get(Case, payload.case_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="case_id does not exist",
        )

    assessment = Assessment(**payload.model_dump())
    db.add(assessment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An assessment with this ordinal already exists for this case",
        )
    db.refresh(assessment)
    return assessment


@router.get("/{assessment_id}", response_model=AssessmentRead)
def get_assessment(assessment_id: UUID, db: Session = Depends(get_db)):
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return assessment


@router.patch("/{assessment_id}", response_model=AssessmentRead)
def update_assessment(
    assessment_id: UUID,
    payload: AssessmentUpdate,
    db: Session = Depends(get_db),
):
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(assessment, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Update would violate ordinal uniqueness for this case",
        )
    db.refresh(assessment)
    return assessment