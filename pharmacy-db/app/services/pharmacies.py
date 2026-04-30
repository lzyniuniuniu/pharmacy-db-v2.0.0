from uuid import UUID

from sqlalchemy.orm import Session

from app.models.pharmacy import Pharmacy


def get_or_create_pharmacy(
    db: Session,
    *,
    regulatory_body_id: UUID,
    license_number: str | None,
    name: str | None,
) -> Pharmacy | None:
    """Find a pharmacy by (regulatory_body_id, license_number), creating
    if missing. Returns None if both license_number and name are missing
    (no way to identify or describe the pharmacy)."""
    if license_number is None and name is None:
        return None

    if license_number is not None:
        existing = (
            db.query(Pharmacy)
            .filter_by(regulatory_body_id=regulatory_body_id, license_number=license_number)
            .one_or_none()
        )
        if existing is not None:
            # Update the name if we have a better one now
            if name is not None and existing.name != name:
                existing.name = name
            return existing

    pharmacy = Pharmacy(
        regulatory_body_id=regulatory_body_id,
        license_number=license_number,
        name=name,
    )
    db.add(pharmacy)
    db.flush()
    return pharmacy