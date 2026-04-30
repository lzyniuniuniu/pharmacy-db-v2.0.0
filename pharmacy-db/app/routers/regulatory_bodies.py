from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.regulatory_body import RegulatoryBody
from app.schemas.regulatory_body import RegulatoryBodyCreate, RegulatoryBodyRead

router = APIRouter(prefix="/regulatory-bodies", tags=["regulatory-bodies"])

@router.get("",response_model=list[RegulatoryBodyRead])
def list_regulatory_bodies(db: Session = Depends(get_db)):
    return db.query(RegulatoryBody).order_by(RegulatoryBody.short_name).all()


@router.post("", response_model=RegulatoryBodyRead, status_code=status.HTTP_201_CREATED)
def create_regulatory_body(payload: RegulatoryBodyCreate, db: Session = Depends(get_db)):
    body = RegulatoryBody(**payload.model_dump())
    db.add(body)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A regulatory body with that name or short name already exists.",
        )
    db.refresh(body)
    return body

@router.get("/{body_id}", response_model=RegulatoryBodyRead)
def get_regulatory_body(body_id: UUID, db: Session = Depends(get_db)):
    body = db.query(RegulatoryBody).filter_by(id=body_id).one_or_none()
    if body is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regulatory body not found.")
    return body