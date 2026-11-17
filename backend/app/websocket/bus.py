"""Emit real-time events after a successful commit (PRD §24 "persist before broadcasting").

Rooms (docs/01 §6):
    t:{tenant}:b:{branch}:staff   — staff of one branch (table board, later queue/orders)
"""

import logging
import uuid
from typing import Any

import socketio

log = logging.getLogger(__name__)
NAMESPACE = "/rt"
_server: socketio.AsyncServer | None = None


def set_server(server: socketio.AsyncServer) -> None:
    global _server
    _server = server


def branch_staff_room(tenant_id: uuid.UUID, branch_id: uuid.UUID) -> str:
    return f"t:{tenant_id}:b:{branch_id}:staff"


async def emit(event: str, data: dict[str, Any], room: str) -> None:
    """Best effort: a failed broadcast never fails the request (clients also refresh on reconnect)."""
    if _server is None:
        return
    try:
        await _server.emit(event, data, room=room, namespace=NAMESPACE)
    except Exception:
        log.warning("Socket emit failed: %s → %s", event, room, exc_info=True)
