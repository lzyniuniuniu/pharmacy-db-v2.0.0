from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.case import Case


class Document(Base, UUIDMixin, TimestampMixin):
    """An ingested source file (typically a PDF case summary).

    Identified uniquely by file_hash. Re-uploading the same file is a no-op.
    """

    __tablename__ = "documents"

    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # "case_summary" for now; later "regulation", "sop", etc.

    file_hash: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    # SHA-256 hash of file contents, prefixed: "sha256:abc123..."

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Local path or S3 URI. Nullable because we may register a hash before
    # the file is moved to its final location.

    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    report_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When the source system generated this PDF (from the page footer).
    # Distinct from `created_at`, which is when WE ingested it.

    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    # "pending" | "processing" | "done" | "failed"

    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Free-form JSON: extractor version, validation warnings, etc.

    case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
    )

    case: Mapped["Case | None"] = relationship()