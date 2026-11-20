"""FastAPI dependencies: services, DB session, authentication, roles and CSRF protection."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.errors import Forbidden, Unauthorized
from app.core.ratelimit import rate_limit_key
from app.modules.auth import service as auth_service
from app.modules.auth.context import AuthContext
from app.modules.chat.hub import ConversationHub
from app.modules.stellar.context import StellarContext
from app.modules.users.models import Role

_bearer = HTTPBearer(
    auto_error=False, description="Access token from /auth/login, /auth/register or /auth/refresh"
)


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_session(services: ServicesDep) -> AsyncIterator[AsyncSession]:
    async with services.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def optional_caller(
    session: SessionDep,
    services: ServicesDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    return await auth_service.authenticate(session, services, credentials.credentials)


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def current_caller(
    request: Request,
    services: ServicesDep,
    caller: Annotated[AuthContext | None, Depends(optional_caller)],
) -> AuthContext:
    if caller is None:
        raise Unauthorized("Authentication is required.", code="AUTH_REQUIRED")
    if request.method not in _SAFE_METHODS:
        await services.rate_limiter.hit(
            bucket="user_writes",
            key=rate_limit_key(str(caller.user_id)),
            limit=services.settings.user_write_rate_limit_per_minute,
            window=timedelta(minutes=1),
            now=services.clock.now(),
        )
    return caller


CallerDep = Annotated[AuthContext, Depends(current_caller)]
OptionalCallerDep = Annotated[AuthContext | None, Depends(optional_caller)]


def require_role(*roles: Role) -> Callable[[AuthContext], Coroutine[Any, Any, AuthContext]]:
    allowed = frozenset(role.value for role in roles)

    async def dependency(caller: CallerDep) -> AuthContext:
        if caller.user.role not in allowed:
            raise Forbidden("Your account type cannot perform this action.", code="ROLE_FORBIDDEN")
        return caller

    return dependency


AdminDep = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]


async def require_cookie_csrf(
    request: Request,
    services: ServicesDep,
    x_csrf_protection: Annotated[
        str | None,
        Header(
            alias="X-CSRF-Protection",
            description="Must be `1`. Required on routes that read or set the refresh cookie.",
        ),
    ] = None,
) -> None:
    """CSRF defence for cookie routes: allowlisted Origin + custom header (forces CORS preflight).

    Combined with SameSite=Strict on the cookie itself. See API_CONTRACT §4.2.
    """
    origin = request.headers.get("origin")
    if origin is None or origin.lower().rstrip("/") not in services.settings.cors_origins:
        raise Forbidden("Request origin is not allowed.", code="CSRF_REJECTED")
    if x_csrf_protection != "1":
        raise Forbidden("Missing CSRF protection header.", code="CSRF_REJECTED")


CsrfDep = Depends(require_cookie_csrf)


def get_hub(request: Request) -> ConversationHub:
    hub: ConversationHub = request.app.state.chat_hub
    return hub


HubDep = Annotated[ConversationHub, Depends(get_hub)]


def get_stellar(request: Request) -> StellarContext:
    stellar: StellarContext = request.app.state.stellar
    return stellar


StellarDep = Annotated[StellarContext, Depends(get_stellar)]
