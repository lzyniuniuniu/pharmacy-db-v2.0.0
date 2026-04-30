from datetime import date
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.case import Case


class Assessment(Base, UUIDMixin, TimestampMixin):
    """A single visit/assessment within a case.

    A case may have multiple assessments — typically one per visit date.
    The extractor assigns ordinals based on chronological order within
    the case; the unique constraint on (case_id, ordinal) prevents
    duplicate ingestion from creating two 'first' assessments.
    """

    __tablename__ = "assessments"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    assessment_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    case: Mapped[Case] = relationship()

    __table_args__ = (
        UniqueConstraint("case_id", "ordinal", name="uq_assessment_ordinal_per_case"),
    )