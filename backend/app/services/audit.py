import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_var
from app.models.platform import AuditLog


def write_audit(
    session: AsyncSession,
    *,
    action: str,
    entity: str,
    entity_id: uuid.UUID | str | None = None,
    tenant_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    diff: dict[str, Any] | None = None,
    reason: str | None = None,
    ip: str | None = None,
) -> None:
    """Append an audit row in the caller's transaction (PRD §26)."""
    session.add(
        AuditLog(
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id else None,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            diff=diff,
            reason=reason,
            ip=ip,
            request_id=request_id_var.get(),
        )
    )
