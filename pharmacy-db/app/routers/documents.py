from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.document import Document
from app.schemas.document import (
    DocumentCreate,
    DocumentRead,
    DocumentUpdate,
    ProcessingStatus,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _existing_document_response(existing: Document) -> Response:
    """Build a 200 response carrying an already-existing document.

    FastAPI ignores Response.status_code if the function returns the
    response_model directly, so we serialize manually and return a Response.
    """
    body = DocumentRead.model_validate(existing).model_dump_json()
    return Response(content=body, status_code=200, media_type="application/json")


@router.get("", response_model=list[DocumentRead])
def list_documents(
    processing_status: ProcessingStatus | None = Query(default=None),
    document_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """List documents, with optional filters by status and type."""
    query = db.query(Document)
    if processing_status is not None:
        query = query.filter(Document.processing_status == processing_status)
    if document_type is not None:
        query = query.filter(Document.document_type == document_type)
    return query.order_by(Document.created_at.desc()).all()


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "Document with this hash already exists; existing record returned."},
    },
)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)):
    """Register a new document.

    Idempotent on `file_hash`: if a document with the same hash already
    exists, returns the existing record with a 200 (not 201). This matches
    the loader's idempotency guarantee — re-running ingestion on the same
    PDF is a no-op.
    """
    existing = db.query(Document).filter(Document.file_hash == payload.file_hash).one_or_none()
    if existing is not None:
        return _existing_document_response(existing)

    document = Document(**payload.model_dump())
    db.add(document)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent insert won the race. Fetch and return the existing one.
        db.rollback()
        existing = db.query(Document).filter(Document.file_hash == payload.file_hash).one()
        return _existing_document_response(existing)
    db.refresh(document)
    return document


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: UUID, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return document


@router.get("/by-hash/{file_hash:path}", response_model=DocumentRead)
def get_document_by_hash(file_hash: str, db: Session = Depends(get_db)):
    """Look up a document by its file hash.

    Useful for the loader: 'do I already have this PDF ingested?' before
    going through the full upload + extraction pipeline.
    """
    document = db.query(Document).filter(Document.file_hash == file_hash).one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return document


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: UUID,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(document, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Update would violate a uniqueness or integrity constraint",
        )
    db.refresh(document)
    return document