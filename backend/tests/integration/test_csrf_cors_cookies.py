"""Cookie attributes per environment, CSRF/Origin enforcement and CORS (PostgreSQL)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text

from app.core.container import Services, build_services
from app.main import create_app
from tests.conftest import make_settings
from tests.support import ALLOWED_ORIGIN, API, PASSWORD, RecordingEmailSender, register


def _cookie_attributes(set_cookie: str) -> dict[str, str]:
    parts = [part.strip() for part in set_cookie.split(";")]
    attributes = {"__name__": parts[0].split("=", 1)[0]}
    for part in parts[1:]:
        key, _, value = part.partition("=")
        attributes[key.lower()] = value
    return attributes


async def test_production_like_cookie_attributes(client: httpx.AsyncClient, unique_email: str) -> None:
    response = await client.post(
        f"{API}/auth/register",
        json={
            "name": "Ada",
            "email": unique_email,
            "password": PASSWORD,
            "role": "CUSTOMER",
            "country": "NG",
        },
        headers={"Origin": ALLOWED_ORIGIN, "X-CSRF-Protection": "1"},
    )
    attributes = _cookie_attributes(response.headers["set-cookie"])
    assert attributes["__name__"] == "__Secure-unifix_rt"
    assert "httponly" in attributes
    assert "secure" in attributes
    assert attributes["samesite"].lower() == "strict"
    assert attributes["path"] == "/api/v1/auth"
    assert "domain" not in attributes  # host-only
    assert int(attributes["max-age"]) == 30 * 24 * 3600


@pytest.fixture
async def dev_client(migrated_database: str, table_names: list[str]) -> AsyncIterator[httpx.AsyncClient]:
    settings = make_settings(migrated_database, cookie_secure=False, cors_origins=["http://localhost:3000"])
    services: Services = build_services(settings)
    services.email = RecordingEmailSender()
    app = create_app(settings, services=services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    ) as http:
        yield http
    async with services.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
    await services.engine.dispose()


async def test_development_cookie_is_not_secure_and_has_no_prefix(dev_client: httpx.AsyncClient) -> None:
    response = await dev_client.post(
        f"{API}/auth/register",
        json={
            "name": "Ada",
            "email": "dev@example.com",
            "password": PASSWORD,
            "role": "CUSTOMER",
            "country": "NG",
        },
        headers={"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"},
    )
    assert response.status_code == 201
    attributes = _cookie_attributes(response.headers["set-cookie"])
    assert attributes["__name__"] == "unifix_rt"
    assert "secure" not in attributes
    assert "httponly" in attributes
    assert attributes["samesite"].lower() == "strict"


@pytest.mark.parametrize(
    ("headers", "label"),
    [
        ({"X-CSRF-Protection": "1"}, "missing origin"),
        ({"Origin": "https://evil.example", "X-CSRF-Protection": "1"}, "foreign origin"),
        ({"Origin": ALLOWED_ORIGIN}, "missing csrf header"),
        ({"Origin": ALLOWED_ORIGIN, "X-CSRF-Protection": "true"}, "wrong csrf header value"),
    ],
)
async def test_cookie_routes_reject_csrf(
    client: httpx.AsyncClient, headers: dict[str, str], label: str
) -> None:
    account = await register(client)
    cookie = {"Cookie": f"__Secure-unifix_rt={account.refresh_cookie}"}
    for path, body in (
        ("/auth/refresh", None),
        ("/auth/logout", None),
        ("/auth/login", {"email": account.email, "password": PASSWORD}),
        (
            "/auth/register",
            {
                "name": "X Y",
                "email": "csrf@example.com",
                "password": PASSWORD,
                "role": "CUSTOMER",
                "country": "NG",
            },
        ),
    ):
        client.cookies.clear()
        response = await client.post(f"{API}{path}", json=body, headers={**headers, **cookie})
        assert response.status_code == 403, (label, path)
        assert response.json()["code"] == "CSRF_REJECTED", (label, path)
    # The session survived every rejected attempt.
    assert (await client.get(f"{API}/auth/me", headers=account.headers)).status_code == 200


async def test_cors_preflight_allows_configured_origin_with_credentials(client: httpx.AsyncClient) -> None:
    response = await client.options(
        f"{API}/auth/refresh",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-protection, content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "x-csrf-protection" in response.headers["access-control-allow-headers"].lower()


async def test_cors_rejects_foreign_origin(client: httpx.AsyncClient) -> None:
    preflight = await client.options(
        f"{API}/auth/refresh",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-protection",
        },
    )
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    simple = await client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


async def test_cors_exposes_pagination_and_request_id_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": ALLOWED_ORIGIN})
    exposed = response.headers["access-control-expose-headers"].lower()
    for header in ("x-total-count", "x-next-offset", "x-request-id", "retry-after"):
        assert header in exposed
