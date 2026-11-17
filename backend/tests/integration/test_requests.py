"""Service requests: creation, the professional feed, privacy, responses and cancellation (PostgreSQL)."""

from __future__ import annotations

import uuid

import httpx

from app.core.clock import FrozenClock
from app.core.container import Services
from tests.support import (
    API,
    Account,
    campus_id,
    category_id,
    image_bytes,
    register,
    register_professional,
    relogin,
    upload,
)

PRIVATE = {"location_text", "latitude", "longitude", "target_professional_id", "conversation_ids"}


async def _request(client: httpx.AsyncClient, customer: Account, **overrides: object) -> dict[str, object]:
    body = {
        "category_id": await category_id(client, "phone-repair"),
        "title": "Cracked iPhone 13 screen",
        "description": "Dropped it this morning; touch still works.",
        "campus_id": await campus_id(client, "unilag"),
        "location_text": "Room 214, Moremi Hall",
        "latitude": "6.517400",
        "longitude": "3.391200",
        **overrides,
    }
    response = await client.post(f"{API}/service-requests", json=body, headers=customer.headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_customer_creates_request_with_private_media(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    customer = await register(client)
    photo = (
        await upload(client, customer, "REQUEST_MEDIA", image_bytes("JPEG"), filename="crack.jpg")
    ).json()
    created = await _request(client, customer, media_file_ids=[photo["id"]])
    assert created["status"] == "OPEN"
    assert created["location_text"] == "Room 214, Moremi Hall"
    assert created["media"][0]["id"] == photo["id"]  # type: ignore[index]
    mine = (await client.get(f"{API}/service-requests/mine", headers=customer.headers)).json()
    assert [item["id"] for item in mine] == [created["id"]]


async def test_only_customers_create_and_inputs_are_validated(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    pro, _ = await register_professional(client)
    body = {
        "category_id": await category_id(client, "phone-repair"),
        "title": "X title",
        "description": "long enough text",
    }
    assert (await client.post(f"{API}/service-requests", json=body, headers=pro.headers)).status_code == 403
    customer = await register(client)
    unknown = await client.post(
        f"{API}/service-requests", json={**body, "category_id": str(uuid.uuid4())}, headers=customer.headers
    )
    assert unknown.status_code == 400
    other = await register(client)
    foreign_photo = (await upload(client, other, "REQUEST_MEDIA")).json()
    stolen = await client.post(
        f"{API}/service-requests",
        json={**body, "media_file_ids": [foreign_photo["id"]]},
        headers=customer.headers,
    )
    assert stolen.status_code == 400


async def test_feed_matches_category_and_campus_and_hides_location(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    unilag, ui = await campus_id(client, "unilag"), await campus_id(client, "ui")
    phone_pro, _ = await register_professional(client, campus_ids=[unilag])
    elsewhere_pro, _ = await register_professional(client, name="UI Pro", campus_ids=[ui])
    laundry_pro, _ = await register_professional(
        client, name="Laundry Pro", category_slug="laundry", campus_ids=[unilag]
    )
    customer = await register(client)
    request = await _request(client, customer)

    feed = (await client.get(f"{API}/service-requests/feed", headers=phone_pro.headers)).json()
    assert [item["id"] for item in feed] == [request["id"]]
    assert PRIVATE.isdisjoint(feed[0])
    assert feed[0]["campus"]["short_name"] == "UNILAG"
    assert (await client.get(f"{API}/service-requests/feed", headers=elsewhere_pro.headers)).json() == []
    assert (await client.get(f"{API}/service-requests/feed", headers=laundry_pro.headers)).json() == []
    assert (await client.get(f"{API}/service-requests/feed", headers=customer.headers)).status_code == 403

    detail = await client.get(f"{API}/service-requests/{request['id']}", headers=phone_pro.headers)
    assert detail.status_code == 200
    assert PRIVATE.isdisjoint(detail.json())
    assert (
        await client.get(f"{API}/service-requests/{request['id']}", headers=elsewhere_pro.headers)
    ).status_code == 404
    assert (
        await client.get(f"{API}/service-requests/{request['id']}", headers=(await register(client)).headers)
    ).status_code == 404


async def test_parent_category_professional_sees_sub_category_requests(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    pro, _ = await register_professional(client, category_slug="electronics")
    customer = await register(client)
    request = await _request(client, customer, campus_id=None)
    assert [
        r["id"] for r in (await client.get(f"{API}/service-requests/feed", headers=pro.headers)).json()
    ] == [request["id"]]


async def test_targeted_requests_and_media_visibility(client: httpx.AsyncClient, seeded: Services) -> None:
    target, target_id = await register_professional(client)
    other, _ = await register_professional(client, name="Other Pro")
    customer = await register(client)
    photo = (await upload(client, customer, "REQUEST_MEDIA")).json()
    request = await _request(
        client, customer, campus_id=None, target_professional_id=target_id, media_file_ids=[photo["id"]]
    )
    assert [
        r["id"] for r in (await client.get(f"{API}/service-requests/feed", headers=target.headers)).json()
    ] == [request["id"]]
    assert (await client.get(f"{API}/service-requests/feed", headers=other.headers)).json() == []
    assert (await client.get(photo["url"], headers=target.headers)).status_code == 200
    assert (await client.get(photo["url"], headers=other.headers)).status_code == 404


async def test_expired_requests_leave_the_feed(
    client: httpx.AsyncClient, seeded: Services, clock: FrozenClock
) -> None:
    pro, _ = await register_professional(client)
    customer = await register(client)
    request = await _request(client, customer, campus_id=None)
    clock.advance(15 * 24 * 3600)
    pro = await relogin(client, pro)  # access tokens last 15 minutes
    customer = await relogin(client, customer)
    assert (await client.get(f"{API}/service-requests/feed", headers=pro.headers)).json() == []
    mine = (await client.get(f"{API}/service-requests/mine", headers=customer.headers)).json()
    assert mine[0]["status"] == "EXPIRED"
    respond = await client.post(
        f"{API}/service-requests/{request['id']}/respond", json={"message": "Hi"}, headers=pro.headers
    )
    assert respond.status_code == 409


async def test_respond_opens_a_linked_conversation_once(client: httpx.AsyncClient, seeded: Services) -> None:
    pro, professional_id = await register_professional(client)
    customer = await register(client)
    request = await _request(client, customer, campus_id=None)
    first = await client.post(
        f"{API}/service-requests/{request['id']}/respond",
        json={"message": "I can fix this today"},
        headers=pro.headers,
    )
    assert first.status_code == 201
    conversation = first.json()
    assert conversation["service_request_id"] == request["id"]
    assert conversation["professional_id"] == professional_id
    again = await client.post(
        f"{API}/service-requests/{request['id']}/respond", json={"message": "again"}, headers=pro.headers
    )
    assert again.status_code == 200
    assert again.json()["id"] == conversation["id"]
    customer_view = await client.get(f"{API}/conversations/{conversation['id']}", headers=customer.headers)
    assert customer_view.json()["messages"][0]["body"] == "I can fix this today"
    feed = (await client.get(f"{API}/service-requests/feed", headers=pro.headers)).json()
    assert feed[0]["responded"] is True
    owner = (await client.get(f"{API}/service-requests/{request['id']}", headers=customer.headers)).json()
    assert owner["conversation_ids"] == [conversation["id"]]


async def test_cancel_request(client: httpx.AsyncClient, seeded: Services) -> None:
    pro, _ = await register_professional(client)
    customer = await register(client)
    request = await _request(client, customer, campus_id=None)
    other = await register(client)
    assert (
        await client.post(f"{API}/service-requests/{request['id']}/cancel", headers=other.headers)
    ).status_code == 404
    cancelled = await client.post(f"{API}/service-requests/{request['id']}/cancel", headers=customer.headers)
    assert cancelled.json()["status"] == "CANCELLED"
    assert (await client.get(f"{API}/service-requests/feed", headers=pro.headers)).json() == []
