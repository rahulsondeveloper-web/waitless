"""Socket.IO server (namespace /rt). Redis manager lets several API/worker processes emit to the same rooms.

Authentication (PRD §24 "authorize every connection and subscription"):
- Anyone may connect (public pages use time sync); the access token, when given, is verified on connect.
- Joining a room is checked against the database every time: tenant membership + branch access.
"""

import logging
import re
import uuid
from datetime import UTC, datetime

import socketio

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.core.security import decode_access_token, decode_table_token
from app.models import Branch
from app.services.access import load_tenant_context
from app.services.notify import user_room
from app.services.orders import table_session_room
from app.services.storefront_cache import storefront_room
from app.websocket.bus import NAMESPACE, branch_queue_room, branch_staff_room, set_server

log = logging.getLogger(__name__)

# Staff rooms are open to anyone who may see the branch's live operations.
STAFF_ROOM_PERMISSIONS = ("tables.operate", "queue.manage", "orders.view", "kitchen.operate")


def _client_manager() -> socketio.AsyncManager | None:
    settings = get_settings()
    if settings.redis_enabled:
        return socketio.AsyncRedisManager(settings.redis_url)
    return None  # in-memory, single process


_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,59}$")


def _slug(value: object) -> str | None:
    s = str(value or "").strip().lower()
    return s if _SLUG.match(s) else None


async def authorize_branch_room(user_id: uuid.UUID, tenant_id: uuid.UUID, branch_id: uuid.UUID) -> bool:
    async with get_sessionmaker()() as session:
        ctx = await load_tenant_context(session, user_id, tenant_id)
        if ctx is None or ctx.tenant_status not in ("pending", "active"):
            return False
        branch = await session.get(Branch, branch_id)  # RLS: other tenants' branches are invisible
        if branch is None:
            return False
        return any(ctx.can_act_in_branch(p, branch_id) for p in STAFF_ROOM_PERMISSIONS)


def create_socket_server() -> socketio.AsyncServer:
    settings = get_settings()
    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins=settings.cors_origins,
        client_manager=_client_manager(),
        logger=False,
        engineio_logger=False,
    )

    @sio.event(namespace=NAMESPACE)
    async def connect(sid: str, environ: dict, auth: dict | None = None) -> None:
        identity: dict = {"user_id": None, "tenant_id": None}
        token = (auth or {}).get("token")
        if token:
            try:
                claims = decode_access_token(str(token))
            except AppError as exc:
                raise socketio.exceptions.ConnectionRefusedError(exc.code) from exc
            identity = {"user_id": str(claims.user_id), "tenant_id": str(claims.tenant_id or "") or None}
        await sio.save_session(sid, identity, namespace=NAMESPACE)
        await sio.emit("server.hello", {"server_time": datetime.now(UTC).isoformat()}, to=sid, namespace=NAMESPACE)

    @sio.event(namespace=NAMESPACE)
    async def disconnect(sid: str, *args: object) -> None:
        log.debug("socket disconnected sid=%s", sid)

    @sio.on("time.sync", namespace=NAMESPACE)
    async def time_sync(sid: str, _data: object = None) -> dict[str, str]:
        """Clients use this to correct clock skew for the serving timer (PRD §14)."""
        return {"server_time": datetime.now(UTC).isoformat()}

    @sio.on("subscribe", namespace=NAMESPACE)
    async def subscribe(sid: str, data: dict | None = None) -> dict:
        """Rooms: branch_staff (staff of a branch), user (my own notifications), branch_queue and
        storefront (public)."""
        identity = await sio.get_session(sid, namespace=NAMESPACE)
        data = data or {}
        kind = data.get("kind")
        if kind == "storefront":
            # Public: only ever says "this restaurant's public pages changed" (no data at all).
            slug = _slug(data.get("slug"))
            if slug is None:
                return {"ok": False, "error": "INVALID_SLUG"}
            room = storefront_room(slug)
            await sio.enter_room(sid, room, namespace=NAMESPACE)
            return {"ok": True, "room": room}
        if kind == "branch_queue":
            # Public: only says "the queue changed" (no personal data); clients then refetch their token.
            try:
                room = branch_queue_room(uuid.UUID(str(data.get("tenant_id"))), uuid.UUID(str(data.get("branch_id"))))
            except ValueError:
                return {"ok": False, "error": "INVALID_BRANCH"}
            await sio.enter_room(sid, room, namespace=NAMESPACE)
            return {"ok": True, "room": room}
        if kind == "table_session":
            # Guests at a table: authorised by their table token (code + PIN), no account needed.
            try:
                claims = decode_table_token(str(data.get("token") or ""))
            except AppError:
                return {"ok": False, "error": "TABLE_TOKEN_INVALID"}
            room = table_session_room(claims.tenant_id, claims.session_id)
            await sio.enter_room(sid, room, namespace=NAMESPACE)
            return {"ok": True, "room": room}
        if not identity.get("user_id"):
            return {"ok": False, "error": "NOT_AUTHENTICATED"}
        if kind == "user":
            room = user_room(uuid.UUID(identity["user_id"]))  # always the caller's own room
            await sio.enter_room(sid, room, namespace=NAMESPACE)
            return {"ok": True, "room": room}
        if kind != "branch_staff":
            return {"ok": False, "error": "UNKNOWN_ROOM"}
        if not identity.get("tenant_id"):
            return {"ok": False, "error": "NOT_AUTHENTICATED"}
        try:
            branch_id = uuid.UUID(str(data.get("branch_id")))
        except ValueError:
            return {"ok": False, "error": "INVALID_BRANCH"}
        tenant_id = uuid.UUID(identity["tenant_id"])
        if not await authorize_branch_room(uuid.UUID(identity["user_id"]), tenant_id, branch_id):
            return {"ok": False, "error": "FORBIDDEN"}
        room = branch_staff_room(tenant_id, branch_id)
        await sio.enter_room(sid, room, namespace=NAMESPACE)
        return {"ok": True, "room": room}

    @sio.on("unsubscribe", namespace=NAMESPACE)
    async def unsubscribe(sid: str, data: dict | None = None) -> dict:
        identity = await sio.get_session(sid, namespace=NAMESPACE)
        data = data or {}
        try:
            if data.get("kind") == "storefront":
                slug = _slug(data.get("slug"))
                if slug is None:
                    return {"ok": False}
                room = storefront_room(slug)
            elif data.get("kind") == "branch_queue":
                room = branch_queue_room(uuid.UUID(str(data.get("tenant_id"))), uuid.UUID(str(data.get("branch_id"))))
            elif data.get("kind") == "table_session":
                claims = decode_table_token(str(data.get("token") or ""))
                room = table_session_room(claims.tenant_id, claims.session_id)
            elif data.get("kind") == "user":
                room = user_room(uuid.UUID(identity["user_id"]))
            else:
                room = branch_staff_room(uuid.UUID(identity["tenant_id"]), uuid.UUID(str(data.get("branch_id"))))
        except (ValueError, TypeError, KeyError, AppError):
            return {"ok": False}
        await sio.leave_room(sid, room, namespace=NAMESPACE)
        return {"ok": True}

    set_server(sio)
    return sio


def create_emitter() -> socketio.AsyncRedisManager | None:
    """Write-only manager for the worker process to emit events to clients connected to the API."""
    settings = get_settings()
    if not settings.redis_enabled:
        return None
    return socketio.AsyncRedisManager(settings.redis_url, write_only=True)
