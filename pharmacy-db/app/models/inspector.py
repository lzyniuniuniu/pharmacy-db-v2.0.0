from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.regulatory_body import RegulatoryBody


class Inspector(Base, UUIDMixin, TimestampMixin):
    """A regulator-side person who inspects pharmacies (e.g., a Pharmacy
    Practice Consultant at ACP)."""

    __tablename__ = "inspectors"

    regulatory_body_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulatory_bodies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)

    regulatory_body: Mapped[RegulatoryBody] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "regulatory_body_id",
            "email",
            name="uq_inspector_email_per_body",
        ),
    )