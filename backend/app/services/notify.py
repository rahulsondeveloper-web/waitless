"""Customer notifications (PRD §25): in-app (Socket.IO, room u:{user}) plus WhatsApp / SMS to the guest's phone
through `app.integrations.messaging` (Phase 12; logged only with the console provider).
"""

import logging
import uuid

from app.core.config import get_settings
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
    from app.services.platform import render  # Super Admin wording / switched-off events (Phase 11)

    rendered = await render(event, title, body)
    if rendered is None:
        log.info("notify %s skipped (switched off)", event)
        return
    title, body = rendered
    masked = (phone[:-4] + "****") if phone else "-"
    log.info("notify %s to %s: %s — %s", event, masked, title, body)
    if phone:  # WhatsApp / SMS in the background (Phase 12 providers; the log in development)
        from app.integrations.messaging import fire, send_text

        text = f"{title}. {body}" + (f" {get_settings().public_base_url.rstrip('/')}{link}" if link else "")
        fire(send_text(phone, text))
    if user_id is not None:
        await emit("notification", {"event": event, "title": title, "body": body, "link": link}, user_room(user_id))
