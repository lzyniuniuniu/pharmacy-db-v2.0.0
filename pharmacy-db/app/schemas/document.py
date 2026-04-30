from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ProcessingStatus = Literal["pending", "processing", "done", "failed"]


class DocumentCreate(BaseModel):
    document_type: str
    file_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    file_name: str
    file_path: str | None = None
    file_size_bytes: int | None = None
    mime_type: str | None = None
    page_count: int | None = None
    report_generated_at: datetime | None = None
    processing_status: ProcessingStatus = "pending"
    extraction_metadata: dict[str, Any] | None = None


class DocumentUpdate(BaseModel):
    file_path: str | None = None
    processing_status: ProcessingStatus | None = None
    processing_error: str | None = None
    extraction_metadata: dict[str, Any] | None = None
    # Note: file_hash, file_name, file_size_bytes, page_count are NOT updatable.
    # Those are properties of the file itself; if they change, it's a different
    # document (different hash) and should be a new row.


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_type: str
    file_hash: str
    file_name: str
    file_path: str | None
    file_size_bytes: int | None
    mime_type: str | None
    page_count: int | None
    report_generated_at: datetime | None
    processing_status: ProcessingStatus
    processing_error: str | None
    extraction_metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime