"""Registration, login, access tokens, lockout and the error envelope (PostgreSQL)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy import select, text

from app.core.clock import FrozenClock
from app.core.container import Services
from app.main import create_app
from app.modules.users.models import User
from tests.support import API, API_BASE_URL, COOKIE_HEADERS, PASSWORD, login, register


async def test_register_customer_returns_access_token_and_sets_refresh_cookie(
    client: httpx.AsyncClient, unique_email: str
) -> None:
    response = await client.post(
        f"{API}/auth/register",
        json={
            "name": "Ada Obi",
            "email": unique_email,
            "password": PASSWORD,
            "role": "CUSTOMER",
            "country": "NG",
        },
        headers=COOKIE_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 900
    assert body["user"]["role"] == "CUSTOMER"
    assert body["user"]["email_verified"] is False
    assert "refresh" not in response.text.lower().replace("set-cookie", "")  # never in the body
    assert response.headers["cache-control"] == "no-store"


async def test_register_professional(client: httpx.AsyncClient) -> None:
    account = await register(client, role="PROFESSIONAL")
    me = await client.get(f"{API}/auth/me", headers=account.headers)
    assert me.status_code == 200
    assert me.json()["role"] == "PROFESSIONAL"


async def test_register_rejects_admin_role_unknown_fields_and_camel_case(
    client: httpx.AsyncClient, unique_email: str
) -> None:
    base = {"name": "Ada", "email": unique_email, "password": PASSWORD, "country": "NG"}
    admin = await client.post(f"{API}/auth/register", json={**base, "role": "ADMIN"}, headers=COOKIE_HEADERS)
    assert admin.status_code == 422
    camel = await client.post(
        f"{API}/auth/register", json={**base, "role": "CUSTOMER", "campusId": "x"}, headers=COOKIE_HEADERS
    )
    assert camel.status_code == 422
    assert camel.json()["code"] == "VALIDATION_FAILED"
    assert camel.json()["errors"][0]["field"] == "campusId"
    professional_object = await client.post(
        f"{API}/auth/register",
        json={**base, "role": "PROFESSIONAL", "professional": {"headline": "x"}},
        headers=COOKIE_HEADERS,
    )
    assert professional_object.status_code == 422


async def test_register_validates_password_length_without_trimming(
    client: httpx.AsyncClient, unique_email: str
) -> None:
    body = {"name": "Ada", "email": unique_email, "role": "CUSTOMER", "country": "NG"}
    short = await client.post(
        f"{API}/auth/register", json={**body, "password": "short"}, headers=COOKIE_HEADERS
    )
    assert short.status_code == 422
    spaced = "  spaced password  "
    ok = await client.post(f"{API}/auth/register", json={**body, "password": spaced}, headers=COOKIE_HEADERS)
    assert ok.status_code == 201
    assert (await login(client, unique_email, spaced)).status_code == 200
    assert (await login(client, unique_email, spaced.strip())).status_code == 401


async def test_duplicate_email_is_rejected_case_insensitively(
    client: httpx.AsyncClient, unique_email: str
) -> None:
    await register(client, email=unique_email)
    response = await client.post(
        f"{API}/auth/register",
        json={
            "name": "Other",
            "email": unique_email.upper(),
            "password": PASSWORD,
            "role": "CUSTOMER",
            "country": "NG",
        },
        headers=COOKIE_HEADERS,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_TAKEN"


async def test_password_is_stored_as_argon2id_hash(
    client: httpx.AsyncClient, services: Services, unique_email: str
) -> None:
    await register(client, email=unique_email)
    async with services.session_factory() as session:
        user = (await session.execute(select(User).where(User.email == unique_email))).scalar_one()
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


async def test_login_success_and_generic_failures(client: httpx.AsyncClient, unique_email: str) -> None:
    await register(client, email=unique_email)
    ok = await login(client, unique_email.upper())
    assert ok.status_code == 200
    wrong_password = await login(client, unique_email, "not the password")
    unknown_email = await login(client, "nobody@example.com", "not the password")
    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_CREDENTIALS"
        assert response.json()["detail"] == "Email or password is incorrect."


async def test_lockout_after_repeated_failures_applies_to_unknown_emails_too(
    client: httpx.AsyncClient, unique_email: str
) -> None:
    await register(client, email=unique_email)
    for target in (unique_email, "ghost@example.com"):
        for _ in range(5):
            assert (await login(client, target, "wrong password!")).status_code == 401
        locked = await login(client, target, PASSWORD)
        assert locked.status_code == 429
        assert locked.json()["code"] == "RATE_LIMITED"
        assert int(locked.headers["retry-after"]) > 0


async def test_lockout_expires(client: httpx.AsyncClient, clock: FrozenClock, unique_email: str) -> None:
    await register(client, email=unique_email)
    for _ in range(5):
        await login(client, unique_email, "wrong password!")
    assert (await login(client, unique_email)).status_code == 429
    clock.advance(901)
    assert (await login(client, unique_email)).status_code == 200


async def test_failed_login_is_audited_even_though_request_fails(
    client: httpx.AsyncClient, services: Services, unique_email: str
) -> None:
    await register(client, email=unique_email)
    await login(client, unique_email, "wrong password!")
    async with services.session_factory() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM audit_logs WHERE action = 'auth.login_failed'")
        )
    assert count == 1


async def test_ip_rate_limit_on_auth_routes(client: httpx.AsyncClient, services: Services) -> None:
    services.settings.auth_ip_rate_limit_per_minute = 3
    for _ in range(3):
        await login(client, "someone@example.com", "whatever password")
    limited = await login(client, "someone@example.com", "whatever password")
    assert limited.status_code == 429


async def test_me_requires_valid_access_token(client: httpx.AsyncClient, clock: FrozenClock) -> None:
    account = await register(client)
    assert (await client.get(f"{API}/auth/me")).status_code == 401
    missing = await client.get(f"{API}/auth/me")
    assert missing.json()["code"] == "AUTH_REQUIRED"
    assert missing.headers["www-authenticate"] == "Bearer"
    tampered = account.access_token[:-2] + ("AA" if account.access_token[-2:] != "AA" else "BB")
    assert (
        await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    ).status_code == 401
    assert (await client.get(f"{API}/auth/me", headers=account.headers)).status_code == 200
    clock.advance(900 + 6)  # 15 minutes + leeway
    expired = await client.get(f"{API}/auth/me", headers=account.headers)
    assert expired.status_code == 401
    assert expired.json()["code"] == "TOKEN_INVALID"


async def test_update_me_and_phone_uniqueness(client: httpx.AsyncClient) -> None:
    first = await register(client)
    second = await register(client)
    updated = await client.patch(
        f"{API}/auth/me",
        json={"name": "  Chidi Okafor ", "city": "Lagos", "phone": "+2348012345678"},
        headers=first.headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Chidi Okafor"
    assert updated.json()["phone"] == "+2348012345678"
    taken = await client.patch(f"{API}/auth/me", json={"phone": "+2348012345678"}, headers=second.headers)
    assert taken.status_code == 409
    assert taken.json()["code"] == "PHONE_TAKEN"
    invalid = await client.patch(f"{API}/auth/me", json={"phone": "08012345678"}, headers=second.headers)
    assert invalid.status_code == 422


async def test_error_envelope_includes_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/auth/me", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["x-request-id"] == "trace-abc-123"
    assert response.json()["request_id"] == "trace-abc-123"
    not_found = await client.get(f"{API}/nope")
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "NOT_FOUND"


async def test_security_headers_present(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.concurrency
async def test_concurrent_registrations_with_same_email_create_one_account(
    services: Services, unique_email: str
) -> None:
    app = create_app(services.settings, services=services)
    body = {
        "name": "Ada Obi",
        "email": unique_email,
        "password": PASSWORD,
        "role": "CUSTOMER",
        "country": "NG",
    }

    async def attempt() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=API_BASE_URL) as http:
            return await http.post(f"{API}/auth/register", json=body, headers=COOKIE_HEADERS)

    results = await asyncio.gather(*(attempt() for _ in range(5)))
    assert sorted(response.status_code for response in results) == [201, 409, 409, 409, 409]
    assert all(r.json()["code"] == "EMAIL_TAKEN" for r in results if r.status_code == 409)


async def test_timestamps_are_returned_in_utc(client: httpx.AsyncClient) -> None:
    account = await register(client)
    created_at = (await client.get(f"{API}/auth/me", headers=account.headers)).json()["created_at"]
    assert created_at.endswith(("+00:00", "Z"))
