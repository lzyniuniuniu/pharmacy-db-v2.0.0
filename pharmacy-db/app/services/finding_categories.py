from uuid import UUID

from sqlalchemy.orm import Session

from app.models.finding_category import FindingCategory


def get_or_create_category(
    db: Session,
    regulatory_body_id: UUID,
    full_path: str,
) -> FindingCategory:
    """Return the FindingCategory matching (regulatory_body_id, full_path),
    creating it if it doesn't exist.

    Does NOT commit — the caller is responsible for committing or rolling back.
    This is intentional: when called from the loader, many find-or-creates
    happen within one logical transaction (one ingested PDF), and the caller
    decides when to commit.
    """
    full_path = full_path.strip()
    existing = (
        db.query(FindingCategory)
        .filter(
            FindingCategory.regulatory_body_id == regulatory_body_id,
            FindingCategory.full_path == full_path,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing

    category = FindingCategory(
        regulatory_body_id=regulatory_body_id,
        full_path=full_path,
    )
    db.add(category)
    db.flush()  # populate the UUID; do NOT commit
    return category