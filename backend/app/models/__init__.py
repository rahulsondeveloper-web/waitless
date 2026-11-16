"""Import every model module here so Alembic autogenerate sees all tables."""

from app.models.base import Base
from app.models.platform import AuditLog, IdempotencyKey, OutboxEvent

__all__ = ["AuditLog", "Base", "IdempotencyKey", "OutboxEvent"]
