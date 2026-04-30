from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

class RegulatoryBody(Base, UUIDMixin, TimestampMixin):
    """A regulatory authority (e.g., Alberta College of Pharmacy)"""

    __tablename__ = "regulatory_bodies"

    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    short_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    jurisdiction: Mapped[str | None] = mapped_column(String, nullable=True)