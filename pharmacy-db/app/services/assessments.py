from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.assessment import Assessment


def get_or_create_assessment(
    db: Session,
    *,
    case_id: UUID,
    ordinal: int,
    assessment_date: date | None = None,
) -> Assessment:
    """Find an assessment by (case_id, ordinal), creating if missing."""
    existing = (
        db.query(Assessment)
        .filter_by(case_id=case_id, ordinal=ordinal)
        .one_or_none()
    )
    if existing is not None:
        # Update assessment_date if it was previously null and now we have it
        if assessment_date is not None and existing.assessment_date != assessment_date:
            existing.assessment_date = assessment_date
        return existing

    assessment = Assessment(
        case_id=case_id,
        ordinal=ordinal,
        assessment_date=assessment_date,
    )
    db.add(assessment)
    db.flush()
    return assessment