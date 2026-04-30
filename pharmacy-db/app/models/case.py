from datetime import date
from uuid import UUID

from sqlalchemy import Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.inspector import Inspector
from app.models.pharmacy import Pharmacy
from app.models.regulatory_body import RegulatoryBody


class Case(Base, UUIDMixin, TimestampMixin):
    """A regulatory case — the open file a regulator keeps on a pharmacy.

    Identified by case_number within a regulatory body. Has one pharmacy,
    optionally one inspector (the consultant), and zero-or-more documents
    (PDF case summaries — the most recent is canonical).
    """

    __tablename__ = "cases"

    # The stable identifier from the regulator (e.g., "PP0002449").
    case_number: Mapped[str] = mapped_column(String(50), nullable=False)

    regulatory_body_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulatory_bodies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pharmacy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pharmacies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    consultant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inspectors.id", ondelete="RESTRICT"),
        nullable=True,
    )

    case_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    case_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    case_closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Snapshot of the licensee at the time of the case. Denormalized
    # because licensees change and we want to record the historical truth.
    licensee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    licensee_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Workflow state for the consultant assignment.
    # "confirmed" — taken from the source document
    # "unknown" — no consultant info in the document, awaiting supervisor
    # "supervisor_assigned" — supervisor manually assigned a consultant
    consultant_assignment_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unknown"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    regulatory_body: Mapped[RegulatoryBody] = relationship()
    pharmacy: Mapped[Pharmacy | None] = relationship()
    consultant: Mapped[Inspector | None] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "regulatory_body_id",
            "case_number",
            name="uq_case_number_per_body",
        ),
    )