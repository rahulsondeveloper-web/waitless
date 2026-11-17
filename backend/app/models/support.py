"""Support tickets. Phase 4 = public contact form; Phase 11 adds the Super Admin support desk and notes."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin


class SupportTicket(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "support_tickets"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(20), default="contact_form", server_default="contact_form")
    topic: Mapped[str] = mapped_column(String(30), default="general", server_default="general")
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")

    __table_args__ = (
        CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'closed')", name="status"),
        CheckConstraint("topic IN ('general', 'restaurant_signup', 'customer', 'partnership', 'other')", name="topic"),
    )
