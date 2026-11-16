"""Socket.IO server (namespace /rt). Redis manager lets several API/worker processes emit to the same rooms."""

import logging
from datetime import UTC, datetime

import socketio

from app.core.config import get_settings

log = logging.getLogger(__name__)
NAMESPACE = "/rt"


def _client_manager() -> socketio.AsyncManager | None:
    settings = get_settings()
    if settings.redis_enabled:
        return socketio.AsyncRedisManager(settings.redis_url)
    return None  # in-memory, single process


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
        # Phase 2: verify JWT / table-session token from `auth` and reject otherwise.
        log.info("socket connected sid=%s", sid)
        await sio.emit("server.hello", {"server_time": datetime.now(UTC).isoformat()}, to=sid, namespace=NAMESPACE)

    @sio.event(namespace=NAMESPACE)
    async def disconnect(sid: str, *args: object) -> None:
        log.info("socket disconnected sid=%s", sid)

    @sio.on("time.sync", namespace=NAMESPACE)
    async def time_sync(sid: str, _data: object = None) -> dict[str, str]:
        """Clients use this to correct clock skew for the serving timer (PRD §14)."""
        return {"server_time": datetime.now(UTC).isoformat()}

    return sio


def create_emitter() -> socketio.AsyncRedisManager | None:
    """Write-only manager for the worker process to emit events to clients connected to the API."""
    settings = get_settings()
    if not settings.redis_enabled:
        return None
    return socketio.AsyncRedisManager(settings.redis_url, write_only=True)
