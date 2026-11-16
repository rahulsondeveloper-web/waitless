"""Cross-cutting platform tables: transactional outbox, idempotency keys, audit log."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class OutboxEvent(UUIDPkMixin, CreatedAtMixin, Base):
    """Domain event written in the same transaction as the business change, broadcast after commit.

    Guarantees PRD §24 "persist business state before broadcasting updates".
    """

    __tablename__ = "outbox_events"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    event: Mapped[str] = mapped_column(String(100))  # e.g. "order.accepted"
    room: Mapped[str | None] = mapped_column(String(200))  # Socket.IO room, if broadcast
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    __table_args__ = (
        Index("ix_outbox_events_pending", "created_at", postgresql_where="dispatched_at IS NULL"),
    )


class IdempotencyKey(UUIDPkMixin, CreatedAtMixin, Base):
    """Stores the first response for an Idempotency-Key so retries return the same result."""

    __tablename__ = "idempotency_keys"

    scope: Mapped[str] = mapped_column(String(200))  # e.g. "user:<id>:POST /orders"
    key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("scope", "key"),)


class AuditLog(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_logs"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(100))  # e.g. "restaurant.suspend"
    entity: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(String(64))
