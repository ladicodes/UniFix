"""Refresh rotation, reuse detection, race grace, logout, session management (PostgreSQL)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.clock import FrozenClock
from app.core.container import Services
from app.main import create_app
from tests.support import (
    API,
    API_BASE_URL,
    COOKIE_HEADERS,
    login,
    refresh_cookie_value,
    refresh_with,
    register,
)


async def test_refresh_rotates_cookie_and_issues_new_access_token(client: httpx.AsyncClient) -> None:
    account = await register(client)
    response = await refresh_with(client, account.refresh_cookie)
    assert response.status_code == 200
    new_cookie = refresh_cookie_value(response)
    assert new_cookie != account.refresh_cookie
    new_access = response.json()["access_token"]
    assert (
        await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    ).status_code == 200


async def test_refresh_without_cookie_is_401_and_clears_cookie(client: httpx.AsyncClient) -> None:
    client.cookies.clear()
    response = await client.post(f"{API}/auth/refresh", headers=COOKIE_HEADERS)
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_MISSING"
    assert (
        "Max-Age=0" in response.headers["set-cookie"] or "max-age=0" in response.headers["set-cookie"].lower()
    )


async def test_refresh_reuse_after_grace_revokes_the_whole_session(
    client: httpx.AsyncClient, clock: FrozenClock
) -> None:
    account = await register(client)
    rotated = await refresh_with(client, account.refresh_cookie)
    newest_cookie = refresh_cookie_value(rotated)
    newest_access = rotated.json()["access_token"]
    clock.advance(31)  # beyond the 30 s race grace

    replay = await refresh_with(client, account.refresh_cookie)
    assert replay.status_code == 401
    assert replay.json()["code"] == "REFRESH_REUSED"

    # The legitimate successor and the session's access tokens are now dead too.
    assert (await refresh_with(client, newest_cookie)).status_code == 401
    me = await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {newest_access}"})
    assert me.status_code == 401
    assert me.json()["code"] == "SESSION_REVOKED"


async def test_refresh_race_within_grace_returns_409_and_keeps_session(client: httpx.AsyncClient) -> None:
    account = await register(client)
    first = await refresh_with(client, account.refresh_cookie)
    assert first.status_code == 200
    race = await refresh_with(client, account.refresh_cookie)
    assert race.status_code == 409
    assert race.json()["code"] == "REFRESH_RACE"
    assert "set-cookie" not in race.headers  # the browser keeps the newer cookie
    assert (await refresh_with(client, refresh_cookie_value(first))).status_code == 200


@pytest.mark.concurrency
async def test_concurrent_refreshes_with_same_cookie_yield_one_rotation(services: Services) -> None:
    """Two refreshes racing on separate connections: exactly one rotates, the other gets REFRESH_RACE."""
    app = create_app(services.settings, services=services)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=API_BASE_URL) as setup:
        account = await register(setup)

    async def attempt() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=API_BASE_URL) as http:
            return await http.post(
                f"{API}/auth/refresh",
                headers={**COOKIE_HEADERS, "Cookie": f"__Secure-unifix_rt={account.refresh_cookie}"},
            )

    results = await asyncio.gather(*(attempt() for _ in range(4)))
    statuses = sorted(response.status_code for response in results)
    assert statuses == [200, 409, 409, 409]


async def test_refresh_token_idle_expiry(client: httpx.AsyncClient, clock: FrozenClock) -> None:
    account = await register(client)
    clock.advance(14 * 24 * 3600 + 1)
    response = await refresh_with(client, account.refresh_cookie)
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_EXPIRED"


async def test_session_absolute_expiry(client: httpx.AsyncClient, clock: FrozenClock) -> None:
    account = await register(client)
    cookie = account.refresh_cookie
    for _ in range(3):  # keep refreshing inside the idle window ...
        clock.advance(10 * 24 * 3600)
        response = await refresh_with(client, cookie)
        if response.status_code != 200:
            break
        cookie = refresh_cookie_value(response)
    # ... but the family's 30-day absolute lifetime still ends it.
    assert response.status_code == 401


async def test_logout_revokes_session_and_clears_cookie(client: httpx.AsyncClient) -> None:
    account = await register(client)
    response = await client.post(
        f"{API}/auth/logout",
        headers={**COOKIE_HEADERS, "Cookie": f"__Secure-unifix_rt={account.refresh_cookie}"},
    )
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert (await client.get(f"{API}/auth/me", headers=account.headers)).status_code == 401
    assert (await refresh_with(client, account.refresh_cookie)).status_code == 401


async def test_logout_with_only_bearer_and_logout_is_idempotent(client: httpx.AsyncClient) -> None:
    account = await register(client)
    client.cookies.clear()
    first = await client.post(f"{API}/auth/logout", headers={**COOKIE_HEADERS, **account.headers})
    assert first.status_code == 204
    again = await client.post(f"{API}/auth/logout", headers={**COOKIE_HEADERS, **account.headers})
    assert again.status_code == 204  # an already-revoked bearer is ignored, not an error
    assert (await client.get(f"{API}/auth/me", headers=account.headers)).status_code == 401


async def test_logout_all_ends_every_session(client: httpx.AsyncClient) -> None:
    account = await register(client)
    second = await login(client, account.email)
    second_token = second.json()["access_token"]
    response = await client.post(f"{API}/auth/logout-all", headers=account.headers)
    assert response.status_code == 204
    for token in (account.access_token, second_token):
        assert (
            await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
        ).status_code == 401


async def test_list_and_revoke_individual_sessions(client: httpx.AsyncClient) -> None:
    account = await register(client)
    other = await login(client, account.email)
    other_token = other.json()["access_token"]

    listed = await client.get(f"{API}/auth/sessions", headers=account.headers)
    assert listed.status_code == 200
    sessions = listed.json()
    assert len(sessions) == 2
    assert sum(item["current"] for item in sessions) == 1
    assert all(
        set(item) == {"id", "created_at", "last_used_at", "user_agent", "ip_hint", "current"}
        for item in sessions
    )
    other_id = next(item["id"] for item in sessions if not item["current"])

    revoked = await client.delete(f"{API}/auth/sessions/{other_id}", headers=account.headers)
    assert revoked.status_code == 204
    assert (
        await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {other_token}"})
    ).status_code == 401
    assert (await client.get(f"{API}/auth/me", headers=account.headers)).status_code == 200
    assert len((await client.get(f"{API}/auth/sessions", headers=account.headers)).json()) == 1


async def test_cannot_list_or_revoke_another_users_sessions(client: httpx.AsyncClient) -> None:
    alice = await register(client)
    bob = await register(client)
    bob_sessions = (await client.get(f"{API}/auth/sessions", headers=bob.headers)).json()
    assert len(bob_sessions) == 1
    attempt = await client.delete(f"{API}/auth/sessions/{bob_sessions[0]['id']}", headers=alice.headers)
    assert attempt.status_code == 404
    assert (await client.get(f"{API}/auth/me", headers=bob.headers)).status_code == 200


async def test_change_password_revokes_other_sessions_only(client: httpx.AsyncClient) -> None:
    account = await register(client)
    other_token = (await login(client, account.email)).json()["access_token"]
    wrong = await client.post(
        f"{API}/auth/change-password",
        json={"current_password": "not my password", "new_password": "a brand new password"},
        headers=account.headers,
    )
    assert wrong.status_code == 400
    assert wrong.json()["code"] == "CURRENT_PASSWORD_INCORRECT"
    changed = await client.post(
        f"{API}/auth/change-password",
        json={"current_password": "correct horse battery staple", "new_password": "a brand new password"},
        headers=account.headers,
    )
    assert changed.status_code == 204
    assert (await client.get(f"{API}/auth/me", headers=account.headers)).status_code == 200
    assert (
        await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {other_token}"})
    ).status_code == 401
    assert (await login(client, account.email)).status_code == 401
    assert (await login(client, account.email, "a brand new password")).status_code == 200
