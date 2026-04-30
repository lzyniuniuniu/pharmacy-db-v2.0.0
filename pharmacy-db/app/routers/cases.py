from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.case import Case
from app.models.inspector import Inspector
from app.models.pharmacy import Pharmacy
from app.models.regulatory_body import RegulatoryBody
from app.schemas.case import (
    CaseCreate,
    CaseRead,
    CaseUpdate,
)

router = APIRouter(prefix="/cases", tags=["cases"])


def _validate_fk_targets(payload, db: Session):
    """Verify that any provided FK ids point to real rows.

    The DB would reject bad FKs anyway, but doing this check up-front lets
    us return a clean 404 with a useful message instead of a 500 from
    a deferred IntegrityError.
    """
    if db.get(RegulatoryBody, payload.regulatory_body_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="regulatory_body_id does not exist",
        )
    if payload.pharmacy_id is not None and db.get(Pharmacy, payload.pharmacy_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="pharmacy_id does not exist",
        )
    if payload.consultant_id is not None and db.get(Inspector, payload.consultant_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="consultant_id does not exist",
        )


@router.get("", response_model=list[CaseRead])
def list_cases(
    regulatory_body_id: UUID | None = Query(default=None),
    pharmacy_id: UUID | None = Query(default=None),
    consultant_id: UUID | None = Query(default=None),
    case_state: str | None = Query(default=None),
    needs_assignment: bool = Query(
        default=False,
        description="If true, only return cases awaiting supervisor assignment "
                    "(missing pharmacy or consultant).",
    ),
    db: Session = Depends(get_db),
):
    query = db.query(Case)
    if regulatory_body_id is not None:
        query = query.filter(Case.regulatory_body_id == regulatory_body_id)
    if pharmacy_id is not None:
        query = query.filter(Case.pharmacy_id == pharmacy_id)
    if consultant_id is not None:
        query = query.filter(Case.consultant_id == consultant_id)
    if case_state is not None:
        query = query.filter(Case.case_state == case_state)
    if needs_assignment:
        query = query.filter(
            (Case.pharmacy_id.is_(None)) | (Case.consultant_id.is_(None))
        )
    return query.order_by(Case.created_at.desc()).all()


@router.post("", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
def create_case(payload: CaseCreate, db: Session = Depends(get_db)):
    _validate_fk_targets(payload, db)

    data = payload.model_dump()
    if data.get("licensee_email") is not None:
        data["licensee_email"] = str(data["licensee_email"])

    case = Case(**data)
    db.add(case)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A case with this number already exists for this regulator",
        )
    db.refresh(case)
    return case


@router.get("/{case_id}", response_model=CaseRead)
def get_case(case_id: UUID, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return case


@router.patch("/{case_id}", response_model=CaseRead)
def update_case(case_id: UUID, payload: CaseUpdate, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    update_data = payload.model_dump(exclude_unset=True)

    # Validate FK changes
    if "pharmacy_id" in update_data and update_data["pharmacy_id"] is not None:
        if db.get(Pharmacy, update_data["pharmacy_id"]) is None:
            raise HTTPException(404, "pharmacy_id does not exist")
    if "consultant_id" in update_data and update_data["consultant_id"] is not None:
        if db.get(Inspector, update_data["consultant_id"]) is None:
            raise HTTPException(404, "consultant_id does not exist")

    if "licensee_email" in update_data and update_data["licensee_email"] is not None:
        update_data["licensee_email"] = str(update_data["licensee_email"])

    for field, value in update_data.items():
        setattr(case, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Update would violate a uniqueness or integrity constraint",
        )
    db.refresh(case)
    return case


@router.post(
    "/{case_id}/assign-consultant",
    response_model=CaseRead,
    summary="A consultant is assigned to a case",
)
def assign_consultant(
    case_id: UUID,
    consultant_id: UUID,
    db: Session = Depends(get_db),
):
    """Convenience endpoint for the supervisor workflow.

    Sets consultant_id and updates consultant_assignment_status to
    'supervisor_assigned'. Equivalent to a PATCH but more explicit.
    """
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    if db.get(Inspector, consultant_id) is None:
        raise HTTPException(404, "consultant_id does not exist")

    case.consultant_id = consultant_id
    case.consultant_assignment_status = "supervisor_assigned"
    db.commit()
    db.refresh(case)
    return case