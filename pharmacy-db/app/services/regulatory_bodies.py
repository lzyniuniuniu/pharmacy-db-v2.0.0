from sqlalchemy.orm import Session

from app.models.regulatory_body import RegulatoryBody


def get_or_create_regulatory_body(
    db: Session,
    *,
    name: str,
    short_name: str,
    jurisdiction: str | None = None,
) -> RegulatoryBody:
    """Find a regulatory body by short_name, creating it if missing.

    Does not commit; the caller controls the transaction.
    """
    existing = db.query(RegulatoryBody).filter_by(short_name=short_name).one_or_none()
    if existing is not None:
        return existing

    body = RegulatoryBody(name=name, short_name=short_name, jurisdiction=jurisdiction)
    db.add(body)
    db.flush()
    return body