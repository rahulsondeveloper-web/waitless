"""Support tickets: public contact form (Phase 4), restaurants asking for help, Super Admin desk (Phase 11)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
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
    # Phase 11: support desk
    priority: Mapped[str] = mapped_column(String(10), default="normal", server_default="normal")
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'closed')", name="status"),
        CheckConstraint(
            "topic IN ('general', 'restaurant_signup', 'customer', 'partnership', 'other', 'billing', 'technical',"
            " 'complaint')",
            name="topic",
        ),
        CheckConstraint("source IN ('contact_form', 'restaurant', 'admin')", name="source"),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="priority"),
    )
