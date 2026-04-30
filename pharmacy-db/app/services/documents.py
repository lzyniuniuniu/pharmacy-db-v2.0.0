from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.document import Document


def get_or_create_document(
    db: Session,
    *,
    file_hash: str,
    file_name: str,
    document_type: str = "case_summary",
    file_path: str | None = None,
    file_size_bytes: int | None = None,
    mime_type: str | None = None,
    page_count: int | None = None,
    report_generated_at: datetime | None = None,
    extraction_metadata: dict[str, Any] | None = None,
) -> Document:
    """Find a document by file_hash, creating if missing. Updates mutable
    fields if the document already exists with stale values."""
    existing = db.query(Document).filter_by(file_hash=file_hash).one_or_none()
    if existing is not None:
        # Refresh fields that might have changed (e.g., page_count once
        # extraction completes, or extraction_metadata after re-processing)
        if extraction_metadata is not None:
            existing.extraction_metadata = extraction_metadata
        if page_count is not None and existing.page_count != page_count:
            existing.page_count = page_count
        if file_path is not None and existing.file_path != file_path:
            existing.file_path = file_path
        return existing

    document = Document(
        document_type=document_type,
        file_hash=file_hash,
        file_name=file_name,
        file_path=file_path,
        file_size_bytes=file_size_bytes,
        mime_type=mime_type,
        page_count=page_count,
        report_generated_at=report_generated_at,
        extraction_metadata=extraction_metadata,
        processing_status="done",  # the loader is the result of completed extraction
    )
    db.add(document)
    db.flush()
    return document