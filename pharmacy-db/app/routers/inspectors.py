from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.inspector import Inspector
from app.models.regulatory_body import RegulatoryBody
from app.schemas.inspector import InspectorCreate, InspectorRead, InspectorUpdate

router = APIRouter(prefix="/inspectors", tags=["inspectors"])


@router.get("", response_model=list[InspectorRead])
def list_inspectors(
    regulatory_body_id: UUID | None = Query(default=None),
    unassigned_only: bool = Query(
        default=False,
        description="If true, only return inspectors with no email yet "
                    "(awaiting supervisor assignment).",
    ),
    db: Session = Depends(get_db),
):
    query = db.query(Inspector)
    if regulatory_body_id is not None:
        query = query.filter(Inspector.regulatory_body_id == regulatory_body_id)
    if unassigned_only:
        query = query.filter(Inspector.email.is_(None))
    return query.order_by(Inspector.full_name).all()


@router.post("", response_model=InspectorRead, status_code=status.HTTP_201_CREATED)
def create_inspector(payload: InspectorCreate, db: Session = Depends(get_db)):
    if db.get(RegulatoryBody, payload.regulatory_body_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="regulatory_body_id does not exist",
        )

    # Pydantic's EmailStr is a string subclass but SQLAlchemy doesn't always
    # like it directly. Cast to plain str (or None).
    data = payload.model_dump()
    if data.get("email") is not None:
        data["email"] = str(data["email"])

    inspector = Inspector(**data)
    db.add(inspector)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An inspector with that email already exists for this regulator",
        )
    db.refresh(inspector)
    return inspector


@router.get("/{inspector_id}", response_model=InspectorRead)
def get_inspector(inspector_id: UUID, db: Session = Depends(get_db)):
    inspector = db.get(Inspector, inspector_id)
    if inspector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return inspector


@router.patch("/{inspector_id}", response_model=InspectorRead)
def update_inspector(
    inspector_id: UUID,
    payload: InspectorUpdate,
    db: Session = Depends(get_db),
):
    inspector = db.get(Inspector, inspector_id)
    if inspector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    update_data = payload.model_dump(exclude_unset=True)
    if "email" in update_data and update_data["email"] is not None:
        update_data["email"] = str(update_data["email"])

    for field, value in update_data.items():
        setattr(inspector, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Update would violate email uniqueness for this regulator",
        )
    db.refresh(inspector)
    return inspector