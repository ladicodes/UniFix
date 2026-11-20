"""Quotes, immutable agreements, bookings, the state machine and idempotency (PostgreSQL)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.clock import FrozenClock
from app.core.container import Services
from app.main import create_app
from tests.support import (
    API,
    API_BASE_URL,
    Account,
    RecordingEmailSender,
    category_id,
    create_admin_account,
    open_conversation,
    quote_payload,
    register,
    register_professional,
    relogin,
    verify_email,
)


async def _setup(client: httpx.AsyncClient, outbox: RecordingEmailSender) -> tuple[Account, Account, str]:
    pro, professional_id = await register_professional(client)
    await verify_email(client, outbox, pro)
    customer = await register(client, name="Ada Customer")
    return customer, pro, await open_conversation(client, customer, professional_id)


async def _quote(
    client: httpx.AsyncClient, pro: Account, conversation_id: str, **overrides: object
) -> dict[str, object]:
    response = await client.post(
        f"{API}/quotes", json=quote_payload(conversation_id, **overrides), headers=pro.headers
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_quote_requires_verified_email_and_membership(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    pro, professional_id = await register_professional(client)
    customer = await register(client)
    conversation_id = await open_conversation(client, customer, professional_id)
    unverified = await client.post(f"{API}/quotes", json=quote_payload(conversation_id), headers=pro.headers)
    assert unverified.status_code == 403
    assert unverified.json()["code"] == "EMAIL_NOT_VERIFIED"
    await verify_email(client, email_outbox, pro)
    by_customer = await client.post(
        f"{API}/quotes", json=quote_payload(conversation_id), headers=customer.headers
    )
    assert by_customer.status_code == 403
    stranger, _ = await register_professional(client, name="Stranger Pro")
    await verify_email(client, email_outbox, stranger)
    assert (
        await client.post(f"{API}/quotes", json=quote_payload(conversation_id), headers=stranger.headers)
    ).status_code == 404


async def test_quote_amounts_and_validation(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    _, pro, conversation_id = await _setup(client, email_outbox)
    quote = await _quote(client, pro, conversation_id)
    assert (quote["labour_minor"], quote["materials_minor"], quote["total_minor"]) == (
        2_500_000,
        1_000_000,
        3_500_000,
    )
    assert quote["status"] == "PENDING"
    assert quote["version"] == 1
    for bad in (
        {"labour_minor": 0, "materials_minor": 0},
        {"labour_minor": 1.5},
        {"milestones": [{"title": "Half", "percent": 50}]},
        {"total_minor": 1},
        {"labourMinor": 10},
    ):
        response = await client.post(
            f"{API}/quotes", json=quote_payload(conversation_id, **bad), headers=pro.headers
        )
        assert response.status_code == 422, bad
    past = await client.post(
        f"{API}/quotes",
        json=quote_payload(conversation_id, completion_date="2020-01-01"),
        headers=pro.headers,
    )
    assert past.status_code == 400


async def test_new_quote_supersedes_pending_one(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    customer, pro, conversation_id = await _setup(client, email_outbox)
    first = await _quote(client, pro, conversation_id)
    second = await _quote(client, pro, conversation_id, labour_minor=3_000_000)
    assert second["version"] == 2
    detail = (await client.get(f"{API}/conversations/{conversation_id}", headers=customer.headers)).json()
    statuses = {q["id"]: q["status"] for q in detail["quotes"]}
    assert statuses == {first["id"]: "SUPERSEDED", second["id"]: "PENDING"}
    assert [m["kind"] for m in detail["messages"]] == ["QUOTE", "QUOTE"]
    assert detail["messages"][1]["quote_id"] == second["id"]
    stale = await client.post(f"{API}/quotes/{first['id']}/accept", json={}, headers=customer.headers)
    assert stale.status_code == 409


async def test_accept_creates_booking_with_verifiable_agreement(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    customer, pro, conversation_id = await _setup(client, email_outbox)
    quote = await _quote(client, pro, conversation_id)
    accepted = await client.post(
        f"{API}/quotes/{quote['id']}/accept",
        json={"service_address": "Room 214, Moremi Hall"},
        headers=customer.headers,
    )
    assert accepted.status_code == 201, accepted.text
    bundle = accepted.json()
    booking = bundle["booking"]
    assert booking["status"] == "PENDING_PAYMENT"
    assert booking["amount_minor"] == quote["total_minor"]
    assert booking["address"] == "Room 214, Moremi Hall"
    assert bundle["quote"]["status"] == "ACCEPTED"
    assert bundle["quote"]["agreement_hash"] == booking["agreement_hash"]
    assert bundle["allowed_actions"] == ["CANCEL", "FUND"]
    assert bundle["escrow"] is None
    assert [event["label"] for event in booking["timeline"]] == ["Quote accepted"]

    proof = (await client.get(f"{API}/bookings/{booking['id']}/agreement", headers=pro.headers)).json()
    assert (
        hashlib.sha256(proof["agreement_json"].encode()).hexdigest()
        == proof["agreement_hash"]
        == booking["agreement_hash"]
    )
    document = json.loads(proof["agreement_json"])
    assert document["booking_id"] == booking["id"]
    assert document["total_minor"] == 3_500_000
    assert document["schema"] == "unifix.agreement.v1"

    pro_view = (await client.get(f"{API}/bookings/{booking['id']}", headers=pro.headers)).json()
    assert pro_view["booking"]["address"] is None  # revealed only after funding
    assert pro_view["allowed_actions"] == ["CANCEL"]
    conversation = (
        await client.get(f"{API}/conversations/{conversation_id}", headers=customer.headers)
    ).json()
    assert conversation["conversation"]["booking_id"] == booking["id"]
    assert conversation["messages"][-1]["kind"] == "SYSTEM"
    assert conversation["messages"][-1]["sender_id"] is None

    again = await client.post(f"{API}/quotes/{quote['id']}/accept", json={}, headers=customer.headers)
    assert again.status_code == 409
    blocked = await client.post(f"{API}/quotes", json=quote_payload(conversation_id), headers=pro.headers)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ACTIVE_BOOKING_EXISTS"


async def test_idempotency_key_replays_and_rejects_misuse(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    customer, pro, conversation_id = await _setup(client, email_outbox)
    quote = await _quote(client, pro, conversation_id)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    first = await client.post(
        f"{API}/quotes/{quote['id']}/accept", json={}, headers={**customer.headers, **key}
    )
    replay = await client.post(
        f"{API}/quotes/{quote['id']}/accept", json={}, headers={**customer.headers, **key}
    )
    assert first.status_code == replay.status_code == 201
    assert replay.headers["idempotent-replayed"] == "true"
    assert replay.json()["booking"]["id"] == first.json()["booking"]["id"]
    different_body = await client.post(
        f"{API}/quotes/{quote['id']}/accept",
        json={"service_address": "Elsewhere"},
        headers={**customer.headers, **key},
    )
    assert different_body.status_code == 409
    assert different_body.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    bad = await client.post(
        f"{API}/quotes/{quote['id']}/accept", json={}, headers={**customer.headers, "Idempotency-Key": "x"}
    )
    assert bad.status_code == 400
    async with seeded.session_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM bookings")) == 1


async def test_failed_request_releases_its_idempotency_key(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    customer, _, _ = await _setup(client, email_outbox)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    missing = await client.post(
        f"{API}/quotes/{uuid.uuid4()}/accept", json={}, headers={**customer.headers, **key}
    )
    assert missing.status_code == 404
    async with seeded.session_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM idempotency_keys")) == 0


@pytest.mark.concurrency
async def test_concurrent_accepts_create_exactly_one_booking(
    services: Services, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    app = create_app(services.settings, services=services)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=API_BASE_URL) as setup:
        customer, pro, conversation_id = await _setup(setup, email_outbox)
        quote = await _quote(setup, pro, conversation_id)

    async def accept() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=API_BASE_URL) as http:
            return await http.post(f"{API}/quotes/{quote['id']}/accept", json={}, headers=customer.headers)

    results = await asyncio.gather(*(accept() for _ in range(6)))
    assert sorted(r.status_code for r in results) == [201, 409, 409, 409, 409, 409]
    async with services.session_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM bookings")) == 1
        assert await session.scalar(text("SELECT count(*) FROM agreements")) == 1


@pytest.mark.concurrency
async def test_competing_quotes_on_one_request_yield_one_booking(
    services: Services, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    app = create_app(services.settings, services=services)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=API_BASE_URL) as setup:
        customer = await register(setup)
        request = (
            await setup.post(
                f"{API}/service-requests",
                json={"category_id": await category_id(setup, "phone-repair"), "title": "Broken screen",
                      "description": "Needs replacing quickly please"},
                headers=customer.headers,
            )
        ).json()  # fmt: skip
        quotes = []
        for name in ("Pro One", "Pro Two"):
            pro, _ = await register_professional(setup, name=name)
            await verify_email(setup, email_outbox, pro)
            conversation = (
                await setup.post(
                    f"{API}/service-requests/{request['id']}/respond",
                    json={"message": "Me!"},
                    headers=pro.headers,
                )
            ).json()
            quotes.append(await _quote(setup, pro, conversation["id"]))

    async def accept(quote_id: object) -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=API_BASE_URL) as http:
            return await http.post(f"{API}/quotes/{quote_id}/accept", json={}, headers=customer.headers)

    results = await asyncio.gather(*(accept(q["id"]) for q in quotes))
    assert sorted(r.status_code for r in results) == [201, 409]
    async with services.session_factory() as session:
        statuses = sorted((await session.execute(text("SELECT status FROM quotes"))).scalars().all())
        assert statuses == ["ACCEPTED", "REJECTED"]
        assert await session.scalar(text("SELECT status FROM service_requests")) == "BOOKED"


async def test_reject_and_withdraw(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    customer, pro, conversation_id = await _setup(client, email_outbox)
    first = await _quote(client, pro, conversation_id)
    assert (
        await client.post(f"{API}/quotes/{first['id']}/reject", json={}, headers=pro.headers)
    ).status_code == 404
    rejected = await client.post(
        f"{API}/quotes/{first['id']}/reject", json={"reason": "Too pricey"}, headers=customer.headers
    )
    assert rejected.json()["status"] == "REJECTED"
    second = await _quote(client, pro, conversation_id)
    assert (
        await client.post(f"{API}/quotes/{second['id']}/withdraw", headers=customer.headers)
    ).status_code == 404
    assert (await client.post(f"{API}/quotes/{second['id']}/withdraw", headers=pro.headers)).json()[
        "status"
    ] == "WITHDRAWN"
    assert (
        await client.post(f"{API}/quotes/{second['id']}/accept", json={}, headers=customer.headers)
    ).status_code == 409


async def test_expired_quote_cannot_be_accepted(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender, clock: FrozenClock
) -> None:
    customer, pro, conversation_id = await _setup(client, email_outbox)
    quote = await _quote(client, pro, conversation_id)
    clock.advance(8 * 24 * 3600)
    customer = await relogin(client, customer)
    response = await client.post(f"{API}/quotes/{quote['id']}/accept", json={}, headers=customer.headers)
    assert response.status_code == 409
    assert response.json()["code"] == "QUOTE_EXPIRED"


async def test_booking_state_rules_and_cancellation(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    customer, pro, conversation_id = await _setup(client, email_outbox)
    quote = await _quote(client, pro, conversation_id)
    booking = (
        await client.post(f"{API}/quotes/{quote['id']}/accept", json={}, headers=customer.headers)
    ).json()["booking"]
    start = await client.post(f"{API}/bookings/{booking['id']}/start", headers=pro.headers)
    assert start.status_code == 409
    assert start.json()["code"] == "BOOKING_INVALID_TRANSITION"  # unfunded bookings cannot start
    outsider = await register(client)
    assert (await client.get(f"{API}/bookings/{booking['id']}", headers=outsider.headers)).status_code == 404
    assert (
        await client.post(
            f"{API}/bookings/{booking['id']}/cancel", json={"reason": "nope"}, headers=outsider.headers
        )
    ).status_code == 404
    admin = await create_admin_account(client, seeded)
    assert (await client.get(f"{API}/bookings/{booking['id']}", headers=admin.headers)).status_code == 200

    cancelled = await client.post(
        f"{API}/bookings/{booking['id']}/cancel", json={"reason": "Changed my mind"}, headers=pro.headers
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["booking"]["status"] == "CANCELLED"
    assert body["allowed_actions"] == []
    assert [e["label"] for e in body["booking"]["timeline"]] == ["Quote accepted", "Booking cancelled"]
    again = await client.post(
        f"{API}/bookings/{booking['id']}/cancel", json={"reason": "again"}, headers=customer.headers
    )
    assert again.status_code == 409
    # After cancellation the conversation can carry a new quote and booking.
    assert (
        await client.post(f"{API}/quotes", json=quote_payload(conversation_id), headers=pro.headers)
    ).status_code == 201


async def test_unpaid_booking_expires_after_payment_window(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender, clock: FrozenClock
) -> None:
    customer, pro, conversation_id = await _setup(client, email_outbox)
    quote = await _quote(client, pro, conversation_id)
    booking = (
        await client.post(f"{API}/quotes/{quote['id']}/accept", json={}, headers=customer.headers)
    ).json()["booking"]
    clock.advance(7 * 24 * 3600 + 1)
    customer = await relogin(client, customer)
    expired = (await client.get(f"{API}/bookings/{booking['id']}", headers=customer.headers)).json()[
        "booking"
    ]
    assert expired["status"] == "CANCELLED"
    assert expired["timeline"][-1]["actor"] == "SYSTEM"


async def test_list_bookings_by_role(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    customer, pro, conversation_id = await _setup(client, email_outbox)
    quote = await _quote(client, pro, conversation_id)
    await client.post(f"{API}/quotes/{quote['id']}/accept", json={}, headers=customer.headers)
    for account in (customer, pro):
        listed = await client.get(f"{API}/bookings", headers=account.headers)
        assert len(listed.json()) == 1
        assert listed.headers["x-total-count"] == "1"
    assert (
        await client.get(f"{API}/bookings", params={"role": "PROFESSIONAL"}, headers=customer.headers)
    ).json() == []
    assert (
        len(
            (
                await client.get(f"{API}/bookings", params={"status": "PENDING_PAYMENT"}, headers=pro.headers)
            ).json()
        )
        == 1
    )


async def test_database_enforces_immutability(
    client: httpx.AsyncClient, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    customer, pro, conversation_id = await _setup(client, email_outbox)
    pending = await _quote(client, pro, conversation_id)
    async with seeded.engine.connect() as connection:
        with pytest.raises(DBAPIError, match="immutable"):
            await connection.execute(
                text("UPDATE quotes SET labour_minor = 1 WHERE id = :id"), {"id": pending["id"]}
            )
        await connection.rollback()
    await client.post(f"{API}/quotes/{pending['id']}/accept", json={}, headers=customer.headers)
    async with seeded.engine.connect() as connection:
        for statement in (
            "UPDATE quotes SET status = 'PENDING' WHERE id = :id",
            "UPDATE quotes SET title = 'changed' WHERE id = :id",
            "DELETE FROM quotes WHERE id = :id",
        ):
            with pytest.raises(DBAPIError, match=r"no longer change|never deleted"):
                await connection.execute(text(statement), {"id": pending["id"]})
            await connection.rollback()
        for statement in (
            "UPDATE agreements SET total_minor = 1",
            "DELETE FROM agreements",
            "DELETE FROM booking_events",
        ):
            with pytest.raises(DBAPIError, match="append-only"):
                await connection.execute(text(statement))
            await connection.rollback()
        with pytest.raises(DBAPIError, match="hash_matches_document"):
            await connection.execute(
                text(
                    "INSERT INTO agreements (id, booking_id, quote_id, customer_id, professional_id, "
                    "canonical_json, agreement_hash, total_minor, currency, accepted_by, accepted_at) "
                    "SELECT gen_random_uuid(), gen_random_uuid(), q.id, q.customer_id, q.professional_id, "
                    "'{}', repeat('0', 64), 1, 'NGN', q.customer_id, now() FROM quotes q LIMIT 1"
                )
            )
        await connection.rollback()


async def test_no_route_can_set_a_booking_status(client: httpx.AsyncClient, seeded: Services) -> None:
    """Direct booking mutations are only start (FUNDED -> IN_PROGRESS) and pre-payment cancel. The
    payment routes only prepare or submit chain transactions; financial states come from the
    reconciler (tests/integration/test_payments.py)."""
    paths = create_app(seeded.settings, services=seeded).openapi()["paths"]
    booking_operations = {
        (method.upper(), path)
        for path, item in paths.items()
        if path.startswith(f"{API}/bookings")
        for method in item
    }
    assert booking_operations == {
        ("GET", f"{API}/bookings"),
        ("GET", f"{API}/bookings/{{booking_id}}"),
        ("GET", f"{API}/bookings/{{booking_id}}/agreement"),
        ("POST", f"{API}/bookings/{{booking_id}}/start"),
        ("POST", f"{API}/bookings/{{booking_id}}/cancel"),
        ("POST", f"{API}/bookings/{{booking_id}}/escrow"),
        ("POST", f"{API}/bookings/{{booking_id}}/completion"),
        ("POST", f"{API}/bookings/{{booking_id}}/completion/submit"),
        ("GET", f"{API}/bookings/{{booking_id}}/completion"),
        ("POST", f"{API}/bookings/{{booking_id}}/cancellation-requests"),
        ("GET", f"{API}/bookings/{{booking_id}}/receipts"),
        ("POST", f"{API}/bookings/{{booking_id}}/reviews"),
    }
    assert (
        await client.patch(f"{API}/bookings/{uuid.uuid4()}", json={"status": "FUNDED"})
    ).status_code == 405
