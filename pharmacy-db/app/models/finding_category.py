from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.regulatory_body import RegulatoryBody


class FindingCategory(Base, UUIDMixin, TimestampMixin):
    """A finding category from a regulator's controlled vocabulary.

    Categories are stored as their full path string (e.g.,
    'Operations : Injections') and scoped to a regulatory body — different
    regulators have different vocabularies even for similar concepts.
    """

    __tablename__ = "finding_categories"

    regulatory_body_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulatory_bodies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    full_path: Mapped[str] = mapped_column(String(255), nullable=False)

    regulatory_body: Mapped[RegulatoryBody] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "regulatory_body_id",
            "full_path",
            name="uq_category_path_per_body",
        ),
    )

    @property
    def parent(self) -> str | None:
        """The portion before ' : ' in the full path, or None."""
        if " : " in self.full_path:
            return self.full_path.split(" : ", 1)[0].strip()
        return None

    @property
    def child(self) -> str | None:
        """The portion after ' : ' in the full path, or None."""
        if " : " in self.full_path:
            return self.full_path.split(" : ", 1)[1].strip()
        return None