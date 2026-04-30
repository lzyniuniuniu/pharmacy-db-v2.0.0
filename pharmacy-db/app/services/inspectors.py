from uuid import UUID

from sqlalchemy.orm import Session

from app.models.inspector import Inspector


def get_or_create_inspector(
    db: Session,
    *,
    regulatory_body_id: UUID,
    full_name: str | None,
    email: str | None,
    role: str | None = None,
) -> Inspector | None:
    """Find an inspector by (regulatory_body_id, email) when email is
    present; otherwise create a new stub inspector. Returns None if
    no identifying info at all (caller decides what to do)."""
    if email is None and full_name is None:
        return None

    if email is not None:
        existing = (
            db.query(Inspector)
            .filter_by(regulatory_body_id=regulatory_body_id, email=email)
            .one_or_none()
        )
        if existing is not None:
            # Refresh fields from the new extraction
            if full_name is not None and existing.full_name != full_name:
                existing.full_name = full_name
            if role is not None and existing.role != role:
                existing.role = role
            return existing

    # No email or no match by email: create a new inspector.
    # Note: multiple inspectors with NULL email can coexist (Postgres
    # treats NULLs as distinct in unique constraints).
    inspector = Inspector(
        regulatory_body_id=regulatory_body_id,
        full_name=full_name,
        email=email,
        role=role,
    )
    db.add(inspector)
    db.flush()
    return inspector