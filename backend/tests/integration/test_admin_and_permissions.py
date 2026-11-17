"""Role permissions, admin status management, suspension enforcement and audit logging (PostgreSQL)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.container import Services
from app.modules.users import service as users_service
from tests.support import API, PASSWORD, Account, login, refresh_with, register


async def _admin(client: httpx.AsyncClient, services: Services) -> Account:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    async with services.session_factory() as session:
        await users_service.create_admin(session, services, email=email, name="Ops Admin", password=PASSWORD)
    response = await login(client, email)
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["role"] == "ADMIN"
    return Account(
        id=uuid.UUID(data["user"]["id"]), email=email, access_token=data["access_token"], refresh_cookie=""
    )


@pytest.mark.parametrize("role", ["CUSTOMER", "PROFESSIONAL"])
async def test_non_admins_cannot_change_user_status(client: httpx.AsyncClient, role: str) -> None:
    actor = await register(client, role=role)
    target = await register(client)
    response = await client.patch(
        f"{API}/admin/users/{target.id}/status",
        json={"status": "SUSPENDED", "reason": "testing permissions"},
        headers=actor.headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ROLE_FORBIDDEN"


async def test_admin_route_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.patch(
        f"{API}/admin/users/{uuid.uuid4()}/status", json={"status": "SUSPENDED", "reason": "anonymous"}
    )
    assert response.status_code == 401


async def test_suspension_revokes_sessions_and_blocks_login(
    client: httpx.AsyncClient, services: Services
) -> None:
    admin = await _admin(client, services)
    target = await register(client)
    response = await client.patch(
        f"{API}/admin/users/{target.id}/status",
        json={"status": "SUSPENDED", "reason": "Reported for fraud"},
        headers=admin.headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUSPENDED"
    assert (await client.get(f"{API}/auth/me", headers=target.headers)).status_code == 401
    assert (await refresh_with(client, target.refresh_cookie)).status_code == 401
    blocked = await login(client, target.email)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "ACCOUNT_NOT_ACTIVE"

    reactivated = await client.patch(
        f"{API}/admin/users/{target.id}/status",
        json={"status": "ACTIVE", "reason": "Appeal accepted"},
        headers=admin.headers,
    )
    assert reactivated.status_code == 200
    assert (await login(client, target.email)).status_code == 200

    async with services.session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT actor_type, data->>'to' FROM audit_logs "
                    "WHERE action = 'admin.user_status_changed' ORDER BY id"
                )
            )
        ).all()
    assert [tuple(row) for row in rows] == [("ADMIN", "SUSPENDED"), ("ADMIN", "ACTIVE")]


async def test_admin_cannot_change_own_status_and_unknown_user_is_404(
    client: httpx.AsyncClient, services: Services
) -> None:
    admin = await _admin(client, services)
    own = await client.patch(
        f"{API}/admin/users/{admin.id}/status",
        json={"status": "SUSPENDED", "reason": "oops"},
        headers=admin.headers,
    )
    assert own.status_code == 403
    missing = await client.patch(
        f"{API}/admin/users/{uuid.uuid4()}/status",
        json={"status": "SUSPENDED", "reason": "unknown"},
        headers=admin.headers,
    )
    assert missing.status_code == 404


async def test_login_and_register_are_audited(client: httpx.AsyncClient, services: Services) -> None:
    account = await register(client)
    await login(client, account.email)
    async with services.session_factory() as session:
        actions = (
            (
                await session.execute(
                    text("SELECT action FROM audit_logs WHERE actor_user_id = :u ORDER BY id"),
                    {"u": account.id},
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["auth.register", "auth.login"]


async def test_audit_log_is_append_only(client: httpx.AsyncClient, services: Services) -> None:
    await register(client)
    async with services.engine.connect() as connection:
        with pytest.raises(DBAPIError, match="append-only"):
            await connection.execute(text("UPDATE audit_logs SET action = 'tampered'"))
        await connection.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await connection.execute(text("DELETE FROM audit_logs"))
        await connection.rollback()


async def test_health_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    ready = await client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok"}
