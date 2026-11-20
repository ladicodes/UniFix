"""Authorization matrix: every route in the live OpenAPI schema, for every actor type.

New routes are covered automatically. A route is public only if it is listed in PUBLIC below;
everything else must refuse anonymous callers, and every admin-tagged route must refuse
customers and professionals with ROLE_FORBIDDEN.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import httpx
import pytest

from app.core.container import Services
from tests.support import API, Account, create_admin_account, register, register_professional

# (method, path) pairs that anonymous callers may use.
PUBLIC = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/password-reset/request"),
    ("POST", "/api/v1/auth/password-reset/confirm"),
    ("POST", "/api/v1/auth/verify-email/confirm"),
    ("GET", "/api/v1/campuses"),
    ("GET", "/api/v1/categories"),
    ("GET", "/api/v1/professionals"),
    ("GET", "/api/v1/professionals/{professional_id}"),
    ("GET", "/api/v1/professionals/{professional_id}/reviews"),
    ("GET", "/api/v1/files/{file_id}"),  # signed URL; the signature is the credential
    ("GET", "/health"),
    ("GET", "/ready"),
}


def _operations(client: httpx.AsyncClient) -> list[tuple[str, str, list[str]]]:
    app: Any = client._transport.app  # type: ignore[attr-defined]  # ASGITransport
    schema = app.openapi()
    return [
        (method.upper(), path, list(op.get("tags", [])))
        for path, ops in sorted(schema["paths"].items())
        for method, op in ops.items()
    ]


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)


async def _call(client: httpx.AsyncClient, method: str, path: str, account: Account | None) -> httpx.Response:
    headers = account.headers if account else {}
    kwargs: dict[str, Any] = {"headers": headers}
    if method in {"POST", "PATCH", "PUT"}:
        kwargs["json"] = {}
    return await client.request(method, _url(path), **kwargs)


async def test_matrix_covers_the_new_issue_8_routes(client: httpx.AsyncClient) -> None:
    paths = {path for _, path, _ in _operations(client)}
    for expected in (
        f"{API}/notifications",
        f"{API}/notifications/read",
        f"{API}/notifications/unread-count",
        f"{API}/admin/users",
        f"{API}/admin/users/{{user_id}}",
        f"{API}/admin/bookings",
        f"{API}/admin/escrows",
        f"{API}/admin/chain-transactions",
        f"{API}/admin/service-requests",
        f"{API}/admin/reports",
        f"{API}/admin/reports/{{report_id}}/resolve",
        f"{API}/admin/audit-logs",
        f"{API}/admin/ops/status",
    ):
        assert expected in paths


async def test_anonymous_callers_reach_only_public_routes(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    failures = []
    for method, path, _ in _operations(client):
        if (method, path) in PUBLIC:
            continue
        response = await _call(client, method, path, None)
        code = (
            response.json().get("code")
            if response.headers.get("content-type", "").startswith("application/json")
            else None
        )
        if response.status_code == 401 or (response.status_code == 403 and code == "CSRF_REJECTED"):
            continue
        failures.append((method, path, response.status_code, code))
    assert failures == []


@pytest.mark.parametrize("role", ["CUSTOMER", "PROFESSIONAL"])
async def test_non_admins_are_refused_on_every_admin_route(
    client: httpx.AsyncClient, seeded: Services, role: str
) -> None:
    actor = (await register_professional(client))[0] if role == "PROFESSIONAL" else await register(client)
    failures = []
    for method, path, tags in _operations(client):
        if "admin" not in tags:
            continue
        response = await _call(client, method, path, actor)
        if response.status_code != 403 or response.json().get("code") != "ROLE_FORBIDDEN":
            failures.append((method, path, response.status_code))
    assert failures == []


async def test_admins_pass_the_role_check_on_every_admin_route(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    admin = await create_admin_account(client, seeded)
    failures = []
    for method, path, tags in _operations(client):
        if "admin" not in tags:
            continue
        response = await _call(client, method, path, admin)
        if response.status_code in {401, 403} or response.status_code >= 500:
            failures.append((method, path, response.status_code, response.text[:120]))
    assert failures == []


async def test_signed_in_users_never_get_a_server_error(client: httpx.AsyncClient, seeded: Services) -> None:
    """Unknown ids and empty bodies produce 4xx, never 5xx, for every role on every route."""
    customer = await register(client)
    professional, _ = await register_professional(client)
    admin = await create_admin_account(client, seeded)
    failures = []
    for method, path, _ in _operations(client):
        for account in (customer, professional, admin):
            response = await _call(client, method, path, account)
            if response.status_code >= 500 and response.status_code != 503:  # 503 = escrow not configured
                failures.append((method, path, account.email, response.status_code))
    assert failures == []
