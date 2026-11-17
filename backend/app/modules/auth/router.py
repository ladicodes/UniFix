from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CallerDep, CsrfDep, ServicesDep, SessionDep
from app.api.presenters import user_out
from app.core.container import Services
from app.core.email import deliver
from app.core.errors import Forbidden, Unauthorized, error_responses
from app.modules.auth import service
from app.modules.auth.context import AuthContext
from app.modules.auth.cookies import (
    clear_refresh_cookie,
    clear_refresh_cookie_header,
    read_refresh_cookie,
    set_refresh_cookie,
)
from app.modules.auth.schemas import (
    AuthResponse,
    ChangePasswordIn,
    LoginIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RegisterIn,
    SessionOut,
    TokenIn,
)
from app.modules.auth.service import AuthResult, PendingEmail
from app.modules.auth.sessions import ip_hint
from app.modules.professionals import service as professionals
from app.modules.users.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


async def _auth_response(
    response: Response, session: AsyncSession, services: Services, result: AuthResult
) -> AuthResponse:
    set_refresh_cookie(
        response,
        services.settings,
        result.refresh_token,
        expires_at=result.refresh_expires_at,
        now=services.clock.now(),
    )
    return AuthResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=await user_out(session, result.user),
    )


def _send_later(tasks: BackgroundTasks, services: Services, pending: PendingEmail | None) -> None:
    if pending is not None:
        tasks.add_task(deliver, services.email, pending.message)


async def _lenient_caller(
    session: SessionDep,
    services: ServicesDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext | None:
    """Logout must work with an expired or revoked access token, so auth errors are ignored here."""
    if credentials is None:
        return None
    try:
        return await service.authenticate(session, services, credentials.credentials)
    except (Unauthorized, Forbidden):
        return None


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=[CsrfDep],
    responses=error_responses(403, 409, 422, 429),
    summary="Create a customer or professional account and start a session",
)
async def register(
    data: RegisterIn,
    response: Response,
    tasks: BackgroundTasks,
    session: SessionDep,
    services: ServicesDep,
) -> AuthResponse:
    steps = [professionals.onboarding_step(data.professional)] if data.professional else []
    result, verification_email = await service.register(session, services, data, extra_steps=steps)
    _send_later(tasks, services, verification_email)
    return await _auth_response(response, session, services, result)


@router.post(
    "/login",
    dependencies=[CsrfDep],
    responses=error_responses(401, 403, 422, 429),
    summary="Sign in; sets the HttpOnly refresh cookie",
)
async def login(
    data: LoginIn, response: Response, session: SessionDep, services: ServicesDep
) -> AuthResponse:
    return await _auth_response(response, session, services, await service.login(session, services, data))


@router.post(
    "/refresh",
    dependencies=[CsrfDep],
    responses=error_responses(401, 403, 409, 429),
    summary="Rotate the refresh cookie and issue a new access token",
    description=(
        "Reads the refresh cookie. A reused (already rotated) token revokes the session. "
        "`409 REFRESH_RACE` means another tab refreshed first: retry once after ~300 ms."
    ),
)
async def refresh(
    request: Request, response: Response, session: SessionDep, services: ServicesDep
) -> AuthResponse:
    try:
        result = await service.refresh(session, services, read_refresh_cookie(request, services.settings))
    except Unauthorized as exc:
        exc.headers["Set-Cookie"] = clear_refresh_cookie_header(services.settings)
        raise
    return await _auth_response(response, session, services, result)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[CsrfDep],
    responses=error_responses(403),
    summary="End this session and clear the refresh cookie",
)
async def logout(
    request: Request,
    session: SessionDep,
    services: ServicesDep,
    caller: Annotated[AuthContext | None, Depends(_lenient_caller)],
) -> Response:
    await service.logout(
        session, services, raw_refresh_token=read_refresh_cookie(request, services.settings), bearer=caller
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, services.settings)
    return response


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403),
    summary="End every session of the current user",
)
async def logout_all(caller: CallerDep, session: SessionDep, services: ServicesDep) -> Response:
    await service.logout_all(session, services, caller)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, services.settings)
    return response


@router.get(
    "/sessions", responses=error_responses(401, 403), summary="List the current user's active sessions"
)
async def list_sessions(caller: CallerDep, session: SessionDep, services: ServicesDep) -> list[SessionOut]:
    rows = await service.list_sessions(session, services, caller)
    return [
        SessionOut(
            id=family.id,
            created_at=family.created_at,
            last_used_at=family.last_used_at,
            user_agent=family.user_agent,
            ip_hint=ip_hint(family.ip),
            current=current,
        )
        for family, current in rows
    ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404),
    summary="Revoke one of the current user's sessions",
)
async def revoke_session(
    session_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> Response:
    await service.revoke_session(session, services, caller, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 401, 403, 422, 429),
    summary="Change password; other sessions are revoked",
)
async def change_password(
    data: ChangePasswordIn, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> Response:
    await service.change_password(session, services, caller, data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/verify-email/request",
    status_code=status.HTTP_202_ACCEPTED,
    responses=error_responses(401, 403, 429),
    summary="Send (or resend) the email verification link",
)
async def request_email_verification(
    caller: CallerDep, tasks: BackgroundTasks, session: SessionDep, services: ServicesDep
) -> Response:
    _send_later(tasks, services, await service.request_email_verification(session, services, caller))
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/verify-email/confirm",
    responses=error_responses(400, 422, 429),
    summary="Confirm an email address with the token from the verification link",
)
async def confirm_email_verification(data: TokenIn, session: SessionDep, services: ServicesDep) -> UserOut:
    return await user_out(session, await service.confirm_email_verification(session, services, data.token))


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    responses=error_responses(422, 429),
    summary="Email a password-reset link (always 202, whether or not the account exists)",
)
async def request_password_reset(
    data: PasswordResetRequestIn, tasks: BackgroundTasks, session: SessionDep, services: ServicesDep
) -> Response:
    _send_later(tasks, services, await service.request_password_reset(session, services, data.email))
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 422, 429),
    summary="Set a new password with a reset token; all sessions are revoked",
)
async def confirm_password_reset(
    data: PasswordResetConfirmIn, session: SessionDep, services: ServicesDep
) -> Response:
    await service.confirm_password_reset(session, services, data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
