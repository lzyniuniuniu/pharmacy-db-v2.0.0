from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.finding_category import FindingCategory
from app.models.regulatory_body import RegulatoryBody
from app.schemas.finding_category import FindingCategoryCreate, FindingCategoryRead
from app.services.finding_categories import get_or_create_category

router = APIRouter(prefix="/finding-categories", tags=["finding_categories"])


@router.get("", response_model=list[FindingCategoryRead])
def list_categories(
    regulatory_body_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """List all categories, optionally filtered by regulatory body."""
    query = db.query(FindingCategory)
    if regulatory_body_id is not None:
        query = query.filter(FindingCategory.regulatory_body_id == regulatory_body_id)
    return query.order_by(FindingCategory.full_path).all()


@router.post("", response_model=FindingCategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(payload: FindingCategoryCreate, db: Session = Depends(get_db)):
    """Create a category. If one with the same path already exists for this
    regulator, return it (200) instead of creating a duplicate (idempotent
    create, same pattern as documents)."""
    if db.get(RegulatoryBody, payload.regulatory_body_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="regulatory_body_id does not exist",
        )

    # Delegate to the service — handles the find-or-create logic.
    existed_before = (
        db.query(FindingCategory)
        .filter(
            FindingCategory.regulatory_body_id == payload.regulatory_body_id,
            FindingCategory.full_path == payload.full_path.strip(),
        )
        .one_or_none()
        is not None
    )

    try:
        category = get_or_create_category(db, payload.regulatory_body_id, payload.full_path)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Category creation failed due to integrity error",
        )

    db.refresh(category)
    if existed_before:
        from fastapi import Response
        body = FindingCategoryRead.model_validate(category).model_dump_json()
        return Response(content=body, status_code=200, media_type="application/json")
    return category


@router.get("/{category_id}", response_model=FindingCategoryRead)
def get_category(category_id: UUID, db: Session = Depends(get_db)):
    category = db.get(FindingCategory, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return category