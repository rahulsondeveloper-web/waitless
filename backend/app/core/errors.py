"""One error envelope for the whole API:

    { "error": { "code": "TABLE_ALREADY_ASSIGNED", "message": "...", "details": {...} } }
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class AppError(Exception):
    """Raise from services; mapped to an HTTP response by the handler below."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        error_body("VALIDATION_ERROR", "Request validation failed.", {"errors": jsonable_encoder(exc.errors())}),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED", 403: "FORBIDDEN"}.get(
        exc.status_code, "HTTP_ERROR"
    )
    return JSONResponse(
        error_body(code, str(exc.detail)), status_code=exc.status_code, headers=getattr(exc, "headers", None)
    )


async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error", exc_info=exc)
    return JSONResponse(
        error_body("INTERNAL_ERROR", "Something went wrong. Please try again."),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled)
