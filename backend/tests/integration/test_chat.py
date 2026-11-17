"""Conversations, persisted messages, read receipts, attachments and reports over REST (PostgreSQL)."""

from __future__ import annotations

import uuid

import httpx

from app.core.clock import FrozenClock
from app.core.container import Services
from tests.support import (
    API,
    Account,
    image_bytes,
    open_conversation,
    register,
    register_professional,
    send,
    upload,
)


async def _pair(client: httpx.AsyncClient) -> tuple[Account, Account, str, str]:
    pro, professional_id = await register_professional(client)
    customer = await register(client, name="Ada Customer")
    conversation_id = await open_conversation(client, customer, professional_id)
    return customer, pro, professional_id, conversation_id


async def test_open_conversation_is_idempotent_and_customer_only(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    pro, professional_id = await register_professional(client)
    customer = await register(client)
    first = await client.post(
        f"{API}/conversations", json={"professional_id": professional_id}, headers=customer.headers
    )
    assert first.status_code == 201
    again = await client.post(
        f"{API}/conversations", json={"professional_id": professional_id}, headers=customer.headers
    )
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    by_pro = await client.post(
        f"{API}/conversations", json={"professional_id": professional_id}, headers=pro.headers
    )
    assert by_pro.status_code == 403
    missing = await client.post(
        f"{API}/conversations", json={"professional_id": str(uuid.uuid4())}, headers=customer.headers
    )
    assert missing.status_code == 404
    camel = await client.post(
        f"{API}/conversations", json={"professionalId": professional_id}, headers=customer.headers
    )
    assert camel.status_code == 422


async def test_unlisted_professional_cannot_be_contacted(client: httpx.AsyncClient, seeded: Services) -> None:
    pro, professional_id = await register_professional(client)
    await client.patch(
        f"{API}/professionals/{professional_id}", json={"is_listed": False}, headers=pro.headers
    )
    customer = await register(client)
    response = await client.post(
        f"{API}/conversations", json={"professional_id": professional_id}, headers=customer.headers
    )
    assert response.status_code == 404


async def test_messages_are_persisted_ordered_and_deduplicated(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    customer, pro, _, conversation_id = await _pair(client)
    client_id = str(uuid.uuid4())
    first = await send(
        client, customer, conversation_id, "Hi, my screen is cracked", client_message_id=client_id
    )
    assert first.status_code == 201
    retry = await send(
        client, customer, conversation_id, "Hi, my screen is cracked", client_message_id=client_id
    )
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    await send(client, pro, conversation_id, "I can fix it today")
    await send(client, customer, conversation_id, "Great")

    detail = await client.get(f"{API}/conversations/{conversation_id}", headers=customer.headers)
    assert detail.status_code == 200
    bodies = [message["body"] for message in detail.json()["messages"]]
    assert bodies == ["Hi, my screen is cracked", "I can fix it today", "Great"]
    assert detail.json()["professional"]["name"] == "Tunde Bakare"
    assert "email" not in detail.json()["customer"]
    assert detail.json()["conversation"]["last_message_preview"] == "Great"

    empty = await send(client, customer, conversation_id, "   ")
    assert empty.status_code == 422


async def test_history_cursors_support_paging_and_reconnect_catch_up(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    customer, _, _, conversation_id = await _pair(client)
    ids = [(await send(client, customer, conversation_id, f"m{i}")).json()["id"] for i in range(6)]
    older = await client.get(
        f"{API}/conversations/{conversation_id}/messages",
        params={"before": ids[4], "limit": 2},
        headers=customer.headers,
    )
    assert [m["body"] for m in older.json()] == ["m2", "m3"]
    missed = await client.get(
        f"{API}/conversations/{conversation_id}/messages", params={"after": ids[2]}, headers=customer.headers
    )
    assert [m["body"] for m in missed.json()] == ["m3", "m4", "m5"]
    _, _, _, other_conversation = await _pair(client)
    bad = await client.get(
        f"{API}/conversations/{conversation_id}/messages", params={"after": ids[0]}, headers=customer.headers
    )
    assert bad.status_code == 200
    foreign_cursor = await client.get(
        f"{API}/conversations/{other_conversation}/messages",
        params={"after": ids[0]},
        headers=(await register(client)).headers,
    )
    assert foreign_cursor.status_code == 404


async def test_non_members_cannot_access_anything(client: httpx.AsyncClient, seeded: Services) -> None:
    customer, _, _, conversation_id = await _pair(client)
    message_id = (await send(client, customer, conversation_id, "private")).json()["id"]
    outsider = await register(client)
    other_pro, _ = await register_professional(client, name="Other Pro")
    for stranger in (outsider, other_pro):
        headers = stranger.headers
        assert (
            await client.get(f"{API}/conversations/{conversation_id}", headers=headers)
        ).status_code == 404
        assert (
            await client.get(f"{API}/conversations/{conversation_id}/messages", headers=headers)
        ).status_code == 404
        assert (await send(client, stranger, conversation_id, "intrusion")).status_code == 404
        read = await client.post(
            f"{API}/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_id},
            headers=headers,
        )
        assert read.status_code == 404
        report = await client.post(
            f"{API}/conversations/{conversation_id}/report", json={"reason": "spam"}, headers=headers
        )
        assert report.status_code == 404
        tickets = await client.post(
            f"{API}/ws/tickets", json={"conversation_id": conversation_id}, headers=headers
        )
        assert tickets.status_code == 404
        call = await client.post(
            f"{API}/calls/sessions", json={"conversation_id": conversation_id}, headers=headers
        )
        assert call.status_code == 404
        assert conversation_id not in {
            c["conversation"]["id"]
            for c in (await client.get(f"{API}/conversations", headers=headers)).json()
        }
    assert (await client.get(f"{API}/conversations/{conversation_id}")).status_code == 401


async def test_read_receipts_and_unread_state(client: httpx.AsyncClient, seeded: Services) -> None:
    customer, pro, _, conversation_id = await _pair(client)
    sent = (await send(client, customer, conversation_id, "Are you free?")).json()
    assert sent["read_at"] is None
    pro_view = (await client.get(f"{API}/conversations", headers=pro.headers)).json()[0]
    assert pro_view["unread"] is True
    assert pro_view["conversation"]["unread_for"] == [str(pro.id)]
    assert (await client.get(f"{API}/conversations", headers=customer.headers)).json()[0]["unread"] is False

    marked = await client.post(
        f"{API}/conversations/{conversation_id}/read",
        json={"last_read_message_id": sent["id"]},
        headers=pro.headers,
    )
    assert marked.status_code == 204
    assert (await client.get(f"{API}/conversations", headers=pro.headers)).json()[0]["unread"] is False
    messages = (
        await client.get(f"{API}/conversations/{conversation_id}/messages", headers=customer.headers)
    ).json()
    assert messages[0]["read_at"] is not None


async def test_attachments_are_private_to_members(client: httpx.AsyncClient, seeded: Services) -> None:
    customer, pro, _, conversation_id = await _pair(client)
    photo = (
        await upload(client, customer, "MESSAGE_ATTACHMENT", image_bytes("JPEG"), filename="a.jpg")
    ).json()
    sent = await send(client, customer, conversation_id, "", attachment_file_id=photo["id"])
    assert sent.status_code == 201
    assert sent.json()["kind"] == "IMAGE"
    assert sent.json()["attachment"]["id"] == photo["id"]
    assert (await client.get(photo["url"], headers=pro.headers)).status_code == 200  # other member
    outsider = await register(client)
    assert (await client.get(photo["url"], headers=outsider.headers)).status_code == 404
    assert (await client.get(photo["url"])).status_code == 404
    pros_photo = (await upload(client, pro, "MESSAGE_ATTACHMENT")).json()
    stolen = await send(client, customer, conversation_id, "", attachment_file_id=pros_photo["id"])
    assert stolen.status_code == 400


async def test_reports(client: httpx.AsyncClient, seeded: Services) -> None:
    customer, pro, _, conversation_id = await _pair(client)
    message_id = (await send(client, pro, conversation_id, "pay me outside the app")).json()["id"]
    report = await client.post(
        f"{API}/conversations/{conversation_id}/report",
        json={"reason": "off_platform_payment", "message_id": message_id},
        headers=customer.headers,
    )
    assert report.status_code == 201
    assert report.json()["target_type"] == "MESSAGE"
    duplicate = await client.post(
        f"{API}/conversations/{conversation_id}/report",
        json={"reason": "off_platform_payment", "message_id": message_id},
        headers=customer.headers,
    )
    assert duplicate.status_code == 409
    _, _, _, other = await _pair(client)
    wrong = await client.post(
        f"{API}/conversations/{conversation_id}/report",
        json={"reason": "spam", "message_id": str(uuid.uuid4())},
        headers=customer.headers,
    )
    assert wrong.status_code == 400
    assert other


async def test_response_time_metric(client: httpx.AsyncClient, seeded: Services, clock: FrozenClock) -> None:
    customer, pro, professional_id, conversation_id = await _pair(client)
    await send(client, customer, conversation_id, "Hello?")
    clock.advance(7 * 60)
    await send(client, pro, conversation_id, "Hi! Yes I can help")
    await send(client, pro, conversation_id, "Second reply does not change the metric")
    profile = (await client.get(f"{API}/professionals/{professional_id}")).json()
    assert profile["response_minutes"] == 7


async def test_ticket_requires_auth(client: httpx.AsyncClient, seeded: Services) -> None:
    _, _, _, conversation_id = await _pair(client)
    assert (
        await client.post(f"{API}/ws/tickets", json={"conversation_id": conversation_id})
    ).status_code == 401
