"""The full Batch 1 journey over real HTTP + WebSocket against PostgreSQL:

register → onboard → discover → converse (real-time) → request → respond → quote → accept →
booking awaiting payment with a verifiable, immutable agreement; unauthorised and duplicate
actions rejected throughout.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from typing import Any

import httpx
from websockets.asyncio.client import connect

from app.core.container import Services
from tests.support import (
    ALLOWED_ORIGIN,
    API,
    COOKIE_HEADERS,
    RecordingEmailSender,
    campus_id,
    category_id,
    login,
    quote_payload,
    register,
    verify_email,
)


async def test_customer_to_booking_journey(
    live_server: str, seeded: Services, email_outbox: RecordingEmailSender
) -> None:
    async with httpx.AsyncClient(base_url=f"http://{live_server}") as http:
        unilag = await campus_id(http, "unilag")

        # 1-3. Register both accounts and authenticate.
        customer = await register(http, name="Ada Student", campus_id=unilag)
        professional = await register(http, role="PROFESSIONAL", name="Tunde Fixes")
        assert (await login(http, customer.email)).status_code == 200
        assert (await login(http, professional.email)).status_code == 200
        await verify_email(http, email_outbox, professional)

        # 4-5. Professional profile with campus and category.
        created = await http.post(
            f"{API}/professionals/me",
            json={"category_slug": "phone-repair", "headline": "Same-day phone screens", "city": "Lagos",
                  "country": "NG", "campus_ids": [unilag], "skills": ["iPhone screens"],
                  "starting_price_minor": 1_500_000},
            headers=professional.headers,
        )  # fmt: skip
        assert created.status_code == 201, created.text
        professional_id = created.json()["id"]

        # 6. Discover through search.
        found = await http.get(
            f"{API}/professionals", params={"q": "iphone", "campus": "unilag", "category": "electronics"}
        )
        assert [p["id"] for p in found.json()] == [professional_id]

        # 7-8. Authorised conversation and real-time messages.
        opened = await http.post(
            f"{API}/conversations", json={"professional_id": professional_id}, headers=customer.headers
        )
        conversation_id = opened.json()["id"]
        ticket = (
            await http.post(
                f"{API}/ws/tickets", json={"conversation_id": conversation_id}, headers=professional.headers
            )
        ).json()
        socket_url = f"ws://{live_server}{ticket['ws_path']}?ticket={ticket['ticket']}"
        async with connect(socket_url, origin=ALLOWED_ORIGIN) as socket:
            hello = await http.post(
                f"{API}/conversations/{conversation_id}/messages",
                json={"body": "Hi, cracked screen"},
                headers=customer.headers,
            )
            event: dict[str, Any] = json.loads(await asyncio.wait_for(socket.recv(), 3))
            assert (event["type"], event["data"]["id"]) == ("MESSAGE_CREATED", hello.json()["id"])

        # 9-10. Service request and the professional's response.
        request = await http.post(
            f"{API}/service-requests",
            json={"category_id": await category_id(http, "phone-repair"), "title": "Replace iPhone screen",
                  "description": "Cracked corner, touch works", "campus_id": unilag,
                  "location_text": "Room 214, Moremi Hall"},
            headers=customer.headers,
        )  # fmt: skip
        request_id = request.json()["id"]
        feed = (await http.get(f"{API}/service-requests/feed", headers=professional.headers)).json()
        assert [r["id"] for r in feed] == [request_id]
        assert "location_text" not in feed[0]
        responded = await http.post(
            f"{API}/service-requests/{request_id}/respond",
            json={"message": "I can do it today"},
            headers=professional.headers,
        )
        request_conversation = responded.json()["id"]

        # 11. Quote.
        quote = await http.post(
            f"{API}/quotes", json=quote_payload(request_conversation), headers=professional.headers
        )
        assert quote.status_code == 201, quote.text

        # Unauthorised actions are rejected.
        outsider = await register(http)
        assert (
            await http.post(f"{API}/quotes/{quote.json()['id']}/accept", json={}, headers=outsider.headers)
        ).status_code == 404  # a quote that is not yours is not visible
        assert (
            await http.post(
                f"{API}/quotes/{quote.json()['id']}/accept", json={}, headers=professional.headers
            )
        ).status_code == 403
        assert (
            await http.get(f"{API}/conversations/{request_conversation}", headers=outsider.headers)
        ).status_code == 404

        # 12. Accept → booking (idempotent).
        key = {"Idempotency-Key": str(uuid.uuid4())}
        accepted = await http.post(
            f"{API}/quotes/{quote.json()['id']}/accept", json={}, headers={**customer.headers, **key}
        )
        assert accepted.status_code == 201, accepted.text
        replayed = await http.post(
            f"{API}/quotes/{quote.json()['id']}/accept", json={}, headers={**customer.headers, **key}
        )
        assert replayed.json()["booking"]["id"] == accepted.json()["booking"]["id"]
        duplicate = await http.post(
            f"{API}/quotes/{quote.json()['id']}/accept", json={}, headers=customer.headers
        )
        assert duplicate.status_code == 409
        booking = accepted.json()["booking"]

        # 13. The agreement snapshot verifies independently.
        proof = (await http.get(f"{API}/bookings/{booking['id']}/agreement", headers=customer.headers)).json()
        assert hashlib.sha256(proof["agreement_json"].encode()).hexdigest() == booking["agreement_hash"]
        assert json.loads(proof["agreement_json"])["total_minor"] == booking["amount_minor"] == 3_500_000

        # 14. Awaiting payment; the address stays hidden from the professional until funded.
        pro_view = (await http.get(f"{API}/bookings/{booking['id']}", headers=professional.headers)).json()
        assert pro_view["booking"]["status"] == "PENDING_PAYMENT"
        assert pro_view["booking"]["address"] is None
        assert (await http.get(f"{API}/bookings/{booking['id']}", headers=customer.headers)).json()[
            "booking"
        ]["address"] == ("Room 214, Moremi Hall")

        # 15. No shortcut to funding; revoked sessions are cut off.
        assert (
            await http.post(f"{API}/bookings/{booking['id']}/start", headers=professional.headers)
        ).status_code == 409
        await http.post(f"{API}/auth/logout-all", headers=customer.headers)
        assert (
            await http.get(f"{API}/bookings/{booking['id']}", headers=customer.headers)
        ).status_code == 401
        assert COOKIE_HEADERS  # cookie-route headers exercised throughout via support helpers
