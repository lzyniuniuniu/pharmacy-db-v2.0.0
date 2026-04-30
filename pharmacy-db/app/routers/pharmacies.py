from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.pharmacy import Pharmacy
from app.models.regulatory_body import RegulatoryBody
from app.schemas.pharmacy import PharmacyCreate, PharmacyRead, PharmacyUpdate

router = APIRouter(prefix="/pharmacies", tags=["pharmacies"])

@router.get("", response_model=list[PharmacyRead])
def list_pharmacies(
    regulatory_body_id: UUID | None = Query(
        None, description="Filter pharmacies by their regulatory body."
    ),
    db: Session = Depends(get_db),
):
    """List pharmacies, optionally filtered by regulatory body."""
    query = db.query(Pharmacy)
    if regulatory_body_id is not None:
        query = query.filter(Pharmacy.regulatory_body_id == regulatory_body_id)
    return query.order_by(Pharmacy.name).all()


@router.post("", response_model=PharmacyRead, status_code=status.HTTP_201_CREATED)
def create_pharmacy(payload: PharmacyCreate, db: Session = Depends(get_db)):
    # Verify the regulatory body exists. Without this, a bad UUID would
    # produce an IntegrityError at commit time with a confusing message.
    if db.get(RegulatoryBody, payload.regulatory_body_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="regulatory_body_id does not exist",
        )
    
    pharmacy = Pharmacy(**payload.model_dump())
    db.add(pharmacy)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pharmacy with that license number already exists for the specified regulatory body.",
        )
    db.refresh(pharmacy)
    return pharmacy

@router.get("/{pharmacy_id}", response_model=PharmacyRead)
def get_pharmacy(pharmacy_id: UUID, db: Session = Depends(get_db)):
    pharmacy = db.get(Pharmacy, pharmacy_id)
    if pharmacy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pharmacy not found",
        )
    return pharmacy

@router.patch("/{pharmacy_id}", response_model=PharmacyRead)
def update_pharmacy(
    pharmacy_id: UUID,
    payload: PharmacyUpdate,
    db: Session = Depends(get_db)
):
    pharmacy = db.get(Pharmacy, pharmacy_id)
    if pharmacy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pharmacy not found")
    
    # Only update fields that were actually provided in the request.
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(pharmacy, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Update would violate license_number uniqueness",
        )
    db.refresh(pharmacy)
    return pharmacy
