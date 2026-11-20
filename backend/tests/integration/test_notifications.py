"""In-app notifications: one parametrised case per event, plus the owner-only API.

Each scenario drives the real HTTP API (and the in-memory chain double) up to the event, then the
test checks that the expected recipient got exactly that notification type.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.clock import FrozenClock
from app.core.container import Services
from app.modules.notifications.models import Notification
from app.modules.payments.reconciler import Reconciler
from tests.chain import FakeChain
from tests.integration.test_disputes_reviews import _arbiter, _complete, _disputed, _resolve
from tests.support import (
    API,
    PDF_BYTES,
    Account,
    Deal,
    RecordingEmailSender,
    chain_action,
    create_admin_account,
    fund,
    make_deal,
    open_conversation,
    quote_payload,
    register,
    register_professional,
    send,
    sign,
    upload,
    verify_email,
)


async def _types(services: Services, user_id: uuid.UUID) -> list[str]:
    async with services.session_factory() as session:
        rows = await session.execute(
            select(Notification.type).where(Notification.user_id == user_id).order_by(Notification.created_at)
        )
        return list(rows.scalars().all())


@pytest.fixture
def ctx(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
) -> dict[str, Any]:
    return {
        "client": client,
        "services": seeded,
        "chain": chain,
        "reconciler": reconciler,
        "outbox": email_outbox,
        "clock": clock,
    }


Scenario = Callable[[dict[str, Any]], Awaitable[dict[str, uuid.UUID]]]


def _people(deal: Deal, **extra: uuid.UUID) -> dict[str, uuid.UUID]:
    return {"customer": deal.customer.id, "professional": deal.professional.id, **extra}


async def _pending(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    deal = await make_deal(c["client"], c["chain"], c["outbox"])
    return _people(deal)


async def _message(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    deal = await make_deal(c["client"], c["chain"], c["outbox"])
    sent = await send(c["client"], deal.professional, deal.conversation_id, "On my way")
    assert sent.status_code in {200, 201}, sent.text
    return _people(deal)


async def _rejected(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    client = c["client"]
    customer = await register(client)
    professional, professional_id = await register_professional(client)
    await verify_email(client, c["outbox"], customer)
    await verify_email(client, c["outbox"], professional)
    conversation = await open_conversation(client, customer, professional_id)
    created = await client.post(
        f"{API}/quotes", json=quote_payload(conversation), headers=professional.headers
    )
    assert created.status_code == 201, created.text
    quote = created.json()
    rejected = await client.post(
        f"{API}/quotes/{quote['id']}/reject", json={"reason": "Too pricey"}, headers=customer.headers
    )
    assert rejected.status_code == 200, rejected.text
    return {"customer": customer.id, "professional": professional.id}


async def _cancelled(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    deal = await make_deal(c["client"], c["chain"], c["outbox"])
    cancelled = await c["client"].post(
        f"{API}/bookings/{deal.booking_id}/cancel",
        json={"reason": "Changed my mind"},
        headers=deal.customer.headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    return _people(deal)


async def _released(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    client, chain, reconciler = c["client"], c["chain"], c["reconciler"]
    deal = await make_deal(client, chain, c["outbox"])
    bundle = await fund(client, chain, reconciler, deal)
    assert (
        await client.post(f"{API}/bookings/{deal.booking_id}/start", headers=deal.professional.headers)
    ).status_code == 200
    await _complete(client, chain, reconciler, deal)
    await chain_action(
        client,
        chain,
        reconciler,
        f"/escrows/{bundle['escrow']['id']}/release",
        deal.customer,
        deal.customer_wallet,
    )
    reviewed = await client.post(
        f"{API}/bookings/{deal.booking_id}/reviews",
        json={
            "ratings": {"quality": 5, "punctuality": 4, "communication": 5, "professionalism": 5, "value": 4},
            "comment": "Great job",
        },
        headers=deal.customer.headers,
    )
    assert reviewed.status_code == 201, reviewed.text
    return _people(deal)


async def _refunded(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    client, chain, reconciler = c["client"], c["chain"], c["reconciler"]
    deal = await make_deal(client, chain, c["outbox"])
    bundle = await fund(client, chain, reconciler, deal)
    await chain_action(
        client,
        chain,
        reconciler,
        f"/escrows/{bundle['escrow']['id']}/refund",
        deal.professional,
        deal.professional_wallet,
    )
    return _people(deal)


async def _cancellation_declined(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    client, chain, reconciler = c["client"], c["chain"], c["reconciler"]
    deal = await make_deal(client, chain, c["outbox"])
    await fund(client, chain, reconciler, deal)
    request = await client.post(
        f"{API}/bookings/{deal.booking_id}/cancellation-requests",
        json={"reason": "Not needed"},
        headers=deal.customer.headers,
    )
    assert request.status_code == 201, request.text
    declined = await client.post(
        f"{API}/cancellation-requests/{request.json()['id']}/decline",
        json={"reason": "Parts ordered"},
        headers=deal.professional.headers,
    )
    assert declined.status_code == 200, declined.text
    return _people(deal)


async def _refund_deadline(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    client, chain, reconciler, clock = c["client"], c["chain"], c["reconciler"], c["clock"]
    deal = await make_deal(client, chain, c["outbox"])
    bundle = await fund(client, chain, reconciler, deal)
    clock.advance(bundle["escrow"]["refund_after"] - int(clock.now().timestamp()) - 23 * 3600)
    await reconciler.tick()
    await reconciler.tick()  # sent once only
    return _people(deal)


async def _review_deadline(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    client, chain, reconciler, clock = c["client"], c["chain"], c["reconciler"], c["clock"]
    deal = await make_deal(client, chain, c["outbox"])
    await fund(client, chain, reconciler, deal)
    await _complete(client, chain, reconciler, deal)
    clock.advance(c["services"].settings.escrow_review_window_seconds - 23 * 3600)
    await reconciler.tick()
    return _people(deal)


async def _dispute_locked(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    admin = await create_admin_account(c["client"], c["services"])
    deal, _ = await _disputed(c["client"], c["chain"], c["reconciler"], c["outbox"])
    return _people(deal, admin=admin.id)


async def _dispute_resolved(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    deal, view = await _disputed(c["client"], c["chain"], c["reconciler"], c["outbox"])
    admin = await _arbiter(c["client"], c["services"], c["chain"])
    await _resolve(
        c["client"], c["chain"], c["reconciler"], admin, view["dispute"]["id"],
        {"outcome": "SPLIT", "split_bps_to_professional": 5000, "note": "Half the work was done"},
    )  # fmt: skip
    return _people(deal, admin=admin.id)


async def _dispute_evidence_reminder(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    admin = await create_admin_account(c["client"], c["services"])
    deal, _ = await _disputed(c["client"], c["chain"], c["reconciler"], c["outbox"])
    c["clock"].advance(49 * 3600)  # evidence closes at lock + 72 h
    await c["reconciler"].tick()
    await c["reconciler"].tick()
    return _people(deal, admin=admin.id)


async def _dispute_decision_reminder(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    admin = await create_admin_account(c["client"], c["services"])
    deal, _ = await _disputed(c["client"], c["chain"], c["reconciler"], c["outbox"])
    c["clock"].advance(6 * 86_400 + 3600)  # decision due at lock + 7 days
    await c["reconciler"].tick()
    return _people(deal, admin=admin.id)


async def _dispute_escalated(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    admin = await create_admin_account(c["client"], c["services"])
    deal, _ = await _disputed(c["client"], c["chain"], c["reconciler"], c["outbox"])
    c["clock"].advance(7 * 86_400 + 60)
    await c["reconciler"].tick()
    return _people(deal, admin=admin.id)


async def _verification(decision: str) -> Scenario:
    async def scenario(c: dict[str, Any]) -> dict[str, uuid.UUID]:
        client = c["client"]
        pro, _ = await register_professional(client)
        admin = await create_admin_account(client, c["services"])
        document = (await upload(client, pro, "VERIFICATION_DOCUMENT", PDF_BYTES, filename="nin.pdf")).json()
        await client.post(
            f"{API}/professionals/me/verifications",
            json={"type": "IDENTITY", "file_ids": [document["id"]], "note": "NIN slip"},
            headers=pro.headers,
        )
        item = (await client.get(f"{API}/admin/verifications", headers=admin.headers)).json()[0]
        body: dict[str, Any] = {"decision": decision}
        if decision == "REJECTED":
            body["reason"] = "The document is unreadable"
        decided = await client.post(
            f"{API}/admin/verifications/{item['id']}/decision", json=body, headers=admin.headers
        )
        assert decided.status_code == 200, decided.text
        return {"professional": pro.id}

    return scenario


async def _suspended(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    client = c["client"]
    user = await register(client)
    admin = await create_admin_account(client, c["services"])
    changed = await client.patch(
        f"{API}/admin/users/{user.id}/status",
        json={"status": "SUSPENDED", "reason": "Spam reports"},
        headers=admin.headers,
    )
    assert changed.status_code == 200, changed.text
    return {"customer": user.id}


async def _chain_verification_failed(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    client, chain, reconciler = c["client"], c["chain"], c["reconciler"]
    admin = await create_admin_account(client, c["services"])
    deal = await make_deal(client, chain, c["outbox"])
    prepared = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    await client.post(
        f"{API}/escrows/{prepared['escrow']['id']}/funding",
        json={"signed_xdr": sign(prepared["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    chain.close_ledger()
    key = bytes.fromhex(prepared["escrow"]["escrow_id_hex"])
    chain.escrows[key] = replace(chain.escrows[key], terms_hash="00" * 32)
    await reconciler.tick()
    await reconciler.full_sweep()  # re-seeing the conflict does not alert again
    return _people(deal, admin=admin.id)


async def _verified(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    return await (await _verification("VERIFIED"))(c)


async def _verification_rejected(c: dict[str, Any]) -> dict[str, uuid.UUID]:
    return await (await _verification("REJECTED"))(c)


# (event, scenario, recipient, notification type, expected count for that recipient)
EVENTS: list[tuple[str, Scenario, str, str, int]] = [
    ("new message", _message, "customer", "MESSAGE_RECEIVED", 1),
    ("new quote", _pending, "customer", "QUOTE_RECEIVED", 1),
    ("quote accepted", _pending, "professional", "QUOTE_ACCEPTED", 1),
    ("quote rejected", _rejected, "professional", "QUOTE_REJECTED", 1),
    ("booking cancelled", _cancelled, "professional", "BOOKING_CANCELLED", 1),
    ("booking funded (professional)", _released, "professional", "BOOKING_FUNDED", 1),
    ("booking funded (customer)", _released, "customer", "BOOKING_FUNDED", 1),
    ("job started", _released, "customer", "JOB_STARTED", 1),
    ("completion submitted", _released, "customer", "COMPLETION_SUBMITTED", 1),
    ("payment released", _released, "professional", "PAYMENT_RELEASED", 1),
    ("review received", _released, "professional", "REVIEW_RECEIVED", 1),
    ("refund", _refunded, "customer", "PAYMENT_REFUNDED", 1),
    ("cancellation requested", _cancellation_declined, "professional", "CANCELLATION_REQUESTED", 1),
    ("cancellation declined", _cancellation_declined, "customer", "CANCELLATION_DECLINED", 1),
    ("refund deadline approaching", _refund_deadline, "professional", "DEADLINE_APPROACHING", 1),
    ("review deadline approaching", _review_deadline, "customer", "DEADLINE_APPROACHING", 1),
    ("dispute opened", _dispute_locked, "professional", "DISPUTE_OPENED", 1),
    ("dispute locked", _dispute_locked, "customer", "DISPUTE_LOCKED", 1),
    ("dispute locked (admin)", _dispute_locked, "admin", "DISPUTE_LOCKED", 1),
    ("dispute resolved", _dispute_resolved, "professional", "DISPUTE_RESOLVED", 1),
    ("dispute evidence reminder", _dispute_evidence_reminder, "customer", "DISPUTE_SLA_REMINDER", 1),
    ("dispute decision reminder", _dispute_decision_reminder, "admin", "DISPUTE_SLA_REMINDER", 1),
    ("dispute escalated", _dispute_escalated, "admin", "DISPUTE_ESCALATED", 1),
    ("verification approved", _verified, "professional", "VERIFICATION_APPROVED", 1),
    ("verification rejected", _verification_rejected, "professional", "VERIFICATION_REJECTED", 1),
    ("account suspended", _suspended, "customer", "ACCOUNT_SUSPENDED", 1),
    ("escrow failed verification", _chain_verification_failed, "admin", "CHAIN_VERIFICATION_FAILED", 1),
]


@pytest.mark.parametrize(
    ("scenario", "recipient", "kind", "count"),
    [pytest.param(s, r, k, n, id=name) for name, s, r, k, n in EVENTS],
)
async def test_notification_for_event(
    ctx: dict[str, Any], scenario: Scenario, recipient: str, kind: str, count: int
) -> None:
    people = await scenario(ctx)
    received = await _types(ctx["services"], people[recipient])
    assert received.count(kind) == count, received


async def test_actor_is_not_notified_of_their_own_action(ctx: dict[str, Any]) -> None:
    people = await _cancelled(ctx)
    assert "BOOKING_CANCELLED" not in await _types(ctx["services"], people["customer"])
    people = await _dispute_locked(ctx)
    assert "DISPUTE_OPENED" not in await _types(ctx["services"], people["customer"])  # the opener


async def test_busy_chat_collapses_into_one_unread_notice(ctx: dict[str, Any]) -> None:
    client = ctx["client"]
    deal = await make_deal(client, ctx["chain"], ctx["outbox"])
    for body in ("one", "two", "three"):
        await send(client, deal.professional, deal.conversation_id, body)
    assert (await _types(ctx["services"], deal.customer.id)).count("MESSAGE_RECEIVED") == 1
    await client.post(f"{API}/notifications/read", json={}, headers=deal.customer.headers)
    await send(client, deal.professional, deal.conversation_id, "four")
    assert (await _types(ctx["services"], deal.customer.id)).count("MESSAGE_RECEIVED") == 2


async def test_list_read_and_unread_count_are_owner_only(ctx: dict[str, Any]) -> None:
    client = ctx["client"]
    deal = await make_deal(client, ctx["chain"], ctx["outbox"])
    customer: Account = deal.customer
    count = await client.get(f"{API}/notifications/unread-count", headers=customer.headers)
    assert count.json() == {"count": 1}  # the quote
    listed = await client.get(f"{API}/notifications", headers=customer.headers)
    assert listed.status_code == 200
    assert listed.headers["X-Total-Count"] == "1"
    item = listed.json()[0]
    assert set(item) == {"id", "user_id", "type", "title", "body", "href", "created_at", "read_at"}
    assert item["type"] == "QUOTE_RECEIVED"
    assert item["href"] == f"/messages/{deal.conversation_id}"
    assert item["user_id"] == str(customer.id)

    # The professional cannot see or mark the customer's notification.
    pro_list = (await client.get(f"{API}/notifications", headers=deal.professional.headers)).json()
    assert item["id"] not in {n["id"] for n in pro_list}
    await client.post(
        f"{API}/notifications/read", json={"ids": [item["id"]]}, headers=deal.professional.headers
    )
    assert (await client.get(f"{API}/notifications/unread-count", headers=customer.headers)).json()[
        "count"
    ] == 1

    marked = await client.post(
        f"{API}/notifications/read", json={"ids": [item["id"]]}, headers=customer.headers
    )
    assert marked.status_code == 204
    assert (await client.get(f"{API}/notifications/unread-count", headers=customer.headers)).json()[
        "count"
    ] == 0
    assert (await client.get(f"{API}/notifications?unread=true", headers=customer.headers)).json() == []
    assert (await client.get(f"{API}/notifications?unread=false", headers=customer.headers)).json()[0][
        "read_at"
    ]

    assert (await client.get(f"{API}/notifications")).status_code == 401
    assert (
        await client.post(f"{API}/notifications/read", json={"ids": []}, headers=customer.headers)
    ).status_code == 422
    assert (
        await client.post(f"{API}/notifications/read", json={"idz": []}, headers=customer.headers)
    ).status_code == 422


async def test_notifications_commit_with_their_event(ctx: dict[str, Any]) -> None:
    """A rejected action (here: a second cancellation request) leaves no notification behind."""
    client, chain, reconciler = ctx["client"], ctx["chain"], ctx["reconciler"]
    deal = await make_deal(client, chain, ctx["outbox"])
    await fund(client, chain, reconciler, deal)
    path = f"{API}/bookings/{deal.booking_id}/cancellation-requests"
    assert (
        await client.post(path, json={"reason": "Not needed"}, headers=deal.customer.headers)
    ).status_code == 201
    assert (
        await client.post(path, json={"reason": "Again"}, headers=deal.customer.headers)
    ).status_code == 409
    assert (await _types(ctx["services"], deal.professional.id)).count("CANCELLATION_REQUESTED") == 1
