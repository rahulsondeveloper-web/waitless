"""Guest service at the table: calling the waiter, reviews after paying, and signed-in guests of a visit.

- **ServiceRequest**: "Water / Tissue paper / Bill / Help" from the guest's phone. Open until a waiter or
  manager marks it done. One call per visit every 2 minutes (enforced in the service).
- **Review**: 1–5 stars and a comment, once per paid visit. The owner can hide it from the public page.
- **TableSessionGuest**: a signed-in customer who joined the visit (QR or order ID) — so its invoices show
  under their "My orders" without the order ID / PIN.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin

REQUEST_KINDS = ("water", "tissue", "bill", "help")
REQUEST_STATUSES = ("open", "done")


class ServiceRequest(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "service_requests"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(8))
    table_labels: Mapped[str] = mapped_column(String(80), default="", server_default="")  # snapshot for the alert
    guest_name: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(5), default="open", server_default="open")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "table_session_id"], ["table_sessions.tenant_id", "table_sessions.id"], ondelete="CASCADE"
        ),
        CheckConstraint(f"kind IN {REQUEST_KINDS}", name="kind"),
        CheckConstraint(f"status IN {REQUEST_STATUSES}", name="status"),
        Index("ix_service_requests_open", "tenant_id", "branch_id", postgresql_where="status = 'open'"),
        Index("ix_service_requests_session", "table_session_id", "created_at"),
    )


class Review(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "reviews"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    guest_name: Mapped[str] = mapped_column(String(60), default="", server_default="")
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "table_session_id"], ["table_sessions.tenant_id", "table_sessions.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("table_session_id", name="uq_reviews_session"),  # one review per visit
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating"),
        CheckConstraint("char_length(comment) <= 1000", name="comment_length"),
        Index("ix_reviews_public", "tenant_id", "created_at", postgresql_where="hidden = false"),
    )


class TableSessionGuest(Base):
    __tablename__ = "table_session_guests"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    table_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "table_session_id"], ["table_sessions.tenant_id", "table_sessions.id"], ondelete="CASCADE"
        ),
        Index("ix_table_session_guests_user", "user_id"),
    )
