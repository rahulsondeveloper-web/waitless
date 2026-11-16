"""ASGI entry point.

    uvicorn app.main:app --reload

`app` is the Socket.IO ASGI app wrapping the FastAPI app (`api`), so REST and real-time share one port.
"""

import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware
from app.core.redis import close_redis
from app.websocket.server import create_socket_server

log = logging.getLogger("waitless")

# Windows' registry often lacks this mapping; without it /media serves WebP as application/octet-stream,
# which browsers reject when X-Content-Type-Options: nosniff is set.
mimetypes.add_type("image/webp", ".webp")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info("Starting %s %s (%s)", settings.app_name, settings.app_version, settings.environment)
    yield
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="WaitLess — multi-tenant restaurant SaaS platform API.",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(api_router, prefix=settings.api_prefix)

    settings.media_root.mkdir(parents=True, exist_ok=True)
    app.mount(settings.media_url, StaticFiles(directory=settings.media_root), name="media")
    return app


api = create_app()
sio = create_socket_server()
app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")
