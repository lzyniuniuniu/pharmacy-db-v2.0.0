from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.regulatory_body import RegulatoryBody

class Pharmacy(Base, UUIDMixin, TimestampMixin):    
    """A licensed pharmacy under a regulatory body."""

    __tablename__ = "pharmacies"

    regulatory_body_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulatory_bodies.id", ondelete="RESTRICT"),
    )
    license_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    regulatory_body: Mapped[RegulatoryBody] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "regulatory_body_id", 
            "license_number", 
            name="uq_pharmacy_license_per_body",
        ),
    ) 