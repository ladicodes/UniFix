"""Email verification and password reset (PostgreSQL, email backend replaced by a recording test double)."""

from __future__ import annotations

import httpx

from app.core.clock import FrozenClock
from tests.support import API, RecordingEmailSender, login, refresh_with, register


async def test_registration_sends_verification_email_and_confirm_verifies(
    client: httpx.AsyncClient, email_outbox: RecordingEmailSender, unique_email: str
) -> None:
    account = await register(client, email=unique_email)
    token = email_outbox.token_for(unique_email, "/verify-email")
    confirmed = await client.post(f"{API}/auth/verify-email/confirm", json={"token": token})
    assert confirmed.status_code == 200
    assert confirmed.json()["email_verified"] is True
    me = await client.get(f"{API}/auth/me", headers=account.headers)
    assert me.json()["email_verified"] is True
    reused = await client.post(f"{API}/auth/verify-email/confirm", json={"token": token})
    assert reused.status_code == 400
    assert reused.json()["code"] == "TOKEN_INVALID"


async def test_verification_link_expires(
    client: httpx.AsyncClient, email_outbox: RecordingEmailSender, clock: FrozenClock, unique_email: str
) -> None:
    await register(client, email=unique_email)
    token = email_outbox.token_for(unique_email, "/verify-email")
    clock.advance(24 * 3600 + 1)
    assert (await client.post(f"{API}/auth/verify-email/confirm", json={"token": token})).status_code == 400


async def test_resend_invalidates_previous_link_and_is_noop_once_verified(
    client: httpx.AsyncClient, email_outbox: RecordingEmailSender, unique_email: str
) -> None:
    account = await register(client, email=unique_email)
    first = email_outbox.token_for(unique_email, "/verify-email")
    resend = await client.post(f"{API}/auth/verify-email/request", headers=account.headers)
    assert resend.status_code == 202
    second = email_outbox.token_for(unique_email, "/verify-email")
    assert second != first
    assert (await client.post(f"{API}/auth/verify-email/confirm", json={"token": first})).status_code == 400
    assert (await client.post(f"{API}/auth/verify-email/confirm", json={"token": second})).status_code == 200
    sent_before = len(email_outbox.sent)
    assert (await client.post(f"{API}/auth/verify-email/request", headers=account.headers)).status_code == 202
    assert len(email_outbox.sent) == sent_before


async def test_invalid_token_format_is_validation_error(client: httpx.AsyncClient) -> None:
    response = await client.post(f"{API}/auth/verify-email/confirm", json={"token": "short"})
    assert response.status_code == 422


async def test_password_reset_does_not_reveal_account_existence(
    client: httpx.AsyncClient, email_outbox: RecordingEmailSender
) -> None:
    response = await client.post(f"{API}/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert response.status_code == 202
    assert email_outbox.sent == []


async def test_password_reset_flow_revokes_all_sessions(
    client: httpx.AsyncClient, email_outbox: RecordingEmailSender, unique_email: str
) -> None:
    account = await register(client, email=unique_email)
    assert (
        await client.post(f"{API}/auth/password-reset/request", json={"email": unique_email})
    ).status_code == 202
    token = email_outbox.token_for(unique_email, "/reset-password")
    confirmed = await client.post(
        f"{API}/auth/password-reset/confirm", json={"token": token, "new_password": "my new long password"}
    )
    assert confirmed.status_code == 204
    assert (await client.get(f"{API}/auth/me", headers=account.headers)).status_code == 401
    assert (await refresh_with(client, account.refresh_cookie)).status_code == 401
    assert (await login(client, unique_email)).status_code == 401
    assert (await login(client, unique_email, "my new long password")).status_code == 200
    reused = await client.post(
        f"{API}/auth/password-reset/confirm", json={"token": token, "new_password": "yet another password"}
    )
    assert reused.status_code == 400


async def test_new_reset_request_invalidates_older_link(
    client: httpx.AsyncClient, email_outbox: RecordingEmailSender, unique_email: str
) -> None:
    await register(client, email=unique_email)
    await client.post(f"{API}/auth/password-reset/request", json={"email": unique_email})
    old = email_outbox.token_for(unique_email, "/reset-password")
    await client.post(f"{API}/auth/password-reset/request", json={"email": unique_email})
    response = await client.post(
        f"{API}/auth/password-reset/confirm", json={"token": old, "new_password": "my new long password"}
    )
    assert response.status_code == 400
