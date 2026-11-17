"""Customer notifications (PRD §25). Phase 6: in-app (Socket.IO, room u:{user}) + server log.

SMS / WhatsApp / e-mail providers plug in here later (decision D28); the call sites stay the same.
"""

import logging
import uuid

from app.websocket.bus import emit

log = logging.getLogger("waitless.notify")


def user_room(user_id: uuid.UUID) -> str:
    return f"u:{user_id}"


async def notify_guest(
    *,
    user_id: uuid.UUID | None,
    phone: str | None,
    event: str,
    title: str,
    body: str,
    link: str | None = None,
) -> None:
    masked = (phone[:-4] + "****") if phone else "-"
    log.info("notify %s to %s: %s — %s", event, masked, title, body)
    if user_id is not None:
        await emit("notification", {"event": event, "title": title, "body": body, "link": link}, user_room(user_id))
