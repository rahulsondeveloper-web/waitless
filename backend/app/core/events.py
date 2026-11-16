"""Transactional outbox: record an event inside the caller's transaction.

The dispatcher (worker job `dispatch_outbox`, Phase 2+) broadcasts committed events to Socket.IO
and notification channels, so nothing is announced that was later rolled back.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import OutboxEvent


def record_event(
    session: AsyncSession,
    event: str,
    payload: dict[str, Any],
    *,
    tenant_id: uuid.UUID | None = None,
    room: str | None = None,
) -> OutboxEvent:
    row = OutboxEvent(event=event, payload=payload, tenant_id=tenant_id, room=room)
    session.add(row)
    return row
