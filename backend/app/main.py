"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v1 import router as v1_router
from app.core.config import API_PREFIX, Settings, get_settings
from app.core.container import Services, build_services
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.modules.chat import service as chat_service
from app.modules.chat.hub import ConversationHub
from app.modules.quotes import service as quotes_service

CORS_ALLOWED_HEADERS = [
    "Authorization",
    "Content-Type",
    "Idempotency-Key",
    "X-Request-ID",
    "X-CSRF-Protection",
]
CORS_EXPOSED_HEADERS = ["X-Total-Count", "X-Next-Offset", "X-Request-ID", "Retry-After"]


def create_app(settings: Settings | None = None, *, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    services = services or build_services(settings)
    configure_logging(settings.log_level, json_output=settings.log_json)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await services.engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        summary="UniFix marketplace API",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.services = services
    app.state.chat_hub = ConversationHub()
    chat_service.register_quotes_lookup(quotes_service.conversation_quotes_hook(services))
    register_error_handlers(app)

    # Order: CORS must wrap everything so even error responses carry CORS headers for allowed origins.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=CORS_ALLOWED_HEADERS,
        expose_headers=CORS_EXPOSED_HEADERS,
        max_age=600,
    )

    app.include_router(health.router)
    app.include_router(v1_router, prefix=API_PREFIX)
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory app.main:app_factory``."""
    return create_app()
