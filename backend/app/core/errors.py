"""Application error hierarchy and the single error envelope used by every response."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id

logger = logging.getLogger(__name__)


class FieldError(BaseModel):
    field: str
    message: str


class ErrorResponse(BaseModel):
    """Error envelope. ``detail`` is always a human-readable string."""

    detail: str
    code: str
    request_id: str | None = None
    errors: list[FieldError] | None = None


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"
    default_detail = "The request could not be processed."

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.detail = detail or self.default_detail
        if code is not None:
            self.code = code
        self.headers = headers or {}
        super().__init__(self.detail)


class BadRequest(AppError):
    pass


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"
    default_detail = "Authentication is required."

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        super().__init__(detail, code=code, headers={"WWW-Authenticate": "Bearer"})


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"
    default_detail = "You do not have permission to perform this action."


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"
    default_detail = "The requested resource was not found."


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"
    default_detail = "The request conflicts with the current state of the resource."


class PayloadTooLarge(AppError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"
    default_detail = "The uploaded content is too large."


class UnsupportedMediaType(AppError):
    status_code = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    default_detail = "The uploaded content type is not supported."


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    default_detail = "Too many requests. Please try again later."

    def __init__(self, retry_after_seconds: int, detail: str | None = None) -> None:
        super().__init__(detail, headers={"Retry-After": str(max(1, retry_after_seconds))})


class BadGateway(AppError):
    """An upstream dependency (e.g. Stellar RPC) returned an error. No state was changed."""

    status_code = 502
    code = "UPSTREAM_ERROR"
    default_detail = "An upstream service returned an error. Nothing was changed; please retry."


class ServiceUnavailable(AppError):
    """An upstream dependency is unreachable or a feature is not configured. No state was changed."""

    status_code = 503
    code = "SERVICE_UNAVAILABLE"
    default_detail = "The service is temporarily unavailable. Nothing was changed; please retry."


def _envelope(
    status_code: int,
    detail: str,
    code: str,
    *,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(detail=detail, code=code, request_id=current_request_id(), errors=errors)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body, exclude_none=True),
        headers=headers,
    )


def _field_path(location: tuple[Any, ...] | list[Any]) -> str:
    parts = [str(part) for part in location if part not in {"body", "query", "path", "header", "cookie"}]
    return ".".join(parts) or str(location[0] if location else "request")


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _envelope(exc.status_code, exc.detail, exc.code, headers=exc.headers)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        FieldError(field=_field_path(err.get("loc", ())), message=str(err.get("msg", "Invalid value")))
        for err in exc.errors()
    ]
    return _envelope(422, "Validation failed.", "VALIDATION_FAILED", errors=errors)


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED", 403: "FORBIDDEN"}
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return _envelope(
        exc.status_code,
        detail,
        codes.get(exc.status_code, "HTTP_ERROR"),
        headers=dict(exc.headers) if exc.headers else None,
    )


async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return _envelope(500, "An unexpected error occurred.", "INTERNAL_ERROR")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected)


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses=`` entries documenting the error envelope for the given codes."""
    descriptions = {
        400: "Malformed request",
        401: "Missing, invalid or expired credentials",
        403: "Not allowed",
        404: "Not found or not visible to the caller",
        409: "Conflicts with current state",
        413: "Payload too large",
        415: "Unsupported media type",
        422: "Validation failed",
        429: "Rate limited",
        502: "Upstream (Stellar) error; nothing changed",
        503: "Upstream unavailable or feature not configured; nothing changed",
    }
    return {
        code: {"model": ErrorResponse, "description": descriptions.get(code, "Error")}
        for code in status_codes
    }
