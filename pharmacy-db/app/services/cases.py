from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.case import Case


def get_or_create_case(
    db: Session,
    *,
    regulatory_body_id: UUID,
    case_number: str,
    pharmacy_id: UUID | None = None,
    consultant_id: UUID | None = None,
    case_type: str | None = None,
    case_state: str | None = None,
    case_closed_date: date | None = None,
    licensee_name: str | None = None,
    licensee_email: str | None = None,
    consultant_assignment_status: str = "unknown",
) -> Case:
    """Find a case by (regulatory_body_id, case_number), creating if missing.
    On match, updates mutable fields from the new extraction (a re-extracted
    PDF reflects the current state of the case)."""
    existing = (
        db.query(Case)
        .filter_by(regulatory_body_id=regulatory_body_id, case_number=case_number)
        .one_or_none()
    )
    if existing is not None:
        # Mutable fields: update from new extraction if values differ.
        # Identity (case_number, regulatory_body_id) is never changed.
        # FKs are updated because the extractor may have resolved them now.
        if pharmacy_id is not None:
            existing.pharmacy_id = pharmacy_id
        if consultant_id is not None:
            existing.consultant_id = consultant_id
        if case_type is not None:
            existing.case_type = case_type
        if case_state is not None:
            existing.case_state = case_state
        if case_closed_date is not None:
            existing.case_closed_date = case_closed_date
        if licensee_name is not None:
            existing.licensee_name = licensee_name
        if licensee_email is not None:
            existing.licensee_email = licensee_email
        if consultant_assignment_status != "unknown":
            existing.consultant_assignment_status = consultant_assignment_status
        return existing

    case = Case(
        regulatory_body_id=regulatory_body_id,
        case_number=case_number,
        pharmacy_id=pharmacy_id,
        consultant_id=consultant_id,
        case_type=case_type,
        case_state=case_state,
        case_closed_date=case_closed_date,
        licensee_name=licensee_name,
        licensee_email=licensee_email,
        consultant_assignment_status=consultant_assignment_status,
    )
    db.add(case)
    db.flush()
    return case