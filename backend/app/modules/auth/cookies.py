"""Refresh-token cookie handling (HttpOnly, SameSite=Strict, path-scoped to /api/v1/auth)."""

from __future__ import annotations

from datetime import datetime

from fastapi import Request, Response

from app.core.config import REFRESH_COOKIE_PATH, Settings


def set_refresh_cookie(
    response: Response, settings: Settings, raw_token: str, *, expires_at: datetime, now: datetime
) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_token,
        max_age=max(0, int((expires_at - now).total_seconds())),
        path=REFRESH_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=REFRESH_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie_header(settings: Settings) -> str:
    """The Set-Cookie value that clears the cookie, for attaching to error responses."""
    response = Response()
    clear_refresh_cookie(response, settings)
    return response.headers["set-cookie"]


def read_refresh_cookie(request: Request, settings: Settings) -> str | None:
    return request.cookies.get(settings.refresh_cookie_name)
