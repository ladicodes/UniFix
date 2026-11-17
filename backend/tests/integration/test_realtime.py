"""WebSocket ticket authentication, event delivery and call signaling against a real uvicorn server."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from app.core.clock import FrozenClock
from app.core.container import Services
from app.modules.chat import ws as chat_ws
from tests.support import (
    ALLOWED_ORIGIN,
    API,
    COOKIE_HEADERS,
    Account,
    open_conversation,
    register,
    register_professional,
    send,
    ticket,
)


@pytest.fixture
async def http(live_server: str) -> Any:
    async with httpx.AsyncClient(base_url=f"http://{live_server}") as client:
        yield client


async def _pair(http: httpx.AsyncClient) -> tuple[Account, Account, str]:
    pro, professional_id = await register_professional(http)
    customer = await register(http, name="Ada Customer")
    return customer, pro, await open_conversation(http, customer, professional_id)


def _url(live_server: str, conversation_id: str, query: str) -> str:
    return f"ws://{live_server}{API}/ws/conversations/{conversation_id}?{query}"


async def _receive(socket: ClientConnection, wait: float = 3.0) -> dict[str, Any]:
    return dict(json.loads(await asyncio.wait_for(socket.recv(), wait)))


async def _drain(socket: ClientConnection) -> None:
    while True:
        await asyncio.wait_for(socket.recv(), 3)


async def _expect_close(url: str, code: int, origin: str = ALLOWED_ORIGIN) -> None:
    async with connect(url, origin=origin) as socket:
        with pytest.raises(ConnectionClosed) as closed:
            await asyncio.wait_for(socket.recv(), 3)
    assert closed.value.rcvd is not None
    assert closed.value.rcvd.code == code


async def test_messages_are_delivered_to_both_members(
    http: httpx.AsyncClient, live_server: str, seeded: Services
) -> None:
    customer, pro, conversation_id = await _pair(http)
    customer_url = _url(
        live_server, conversation_id, f"ticket={await ticket(http, customer, conversation_id)}"
    )
    pro_url = _url(live_server, conversation_id, f"ticket={await ticket(http, pro, conversation_id)}")
    async with (
        connect(customer_url, origin=ALLOWED_ORIGIN) as a,
        connect(pro_url, origin=ALLOWED_ORIGIN) as b,
    ):
        sent = (await send(http, customer, conversation_id, "Screen cracked, can you help?")).json()
        for socket in (a, b):
            event = await _receive(socket)
            assert event["type"] == "MESSAGE_CREATED"
            assert event["data"]["id"] == sent["id"]
            assert event["data"]["body"] == "Screen cracked, can you help?"

        await a.send(json.dumps({"type": "PING"}))
        assert (await _receive(a))["type"] == "PONG"
        await a.send(json.dumps({"type": "TYPING"}))
        typing = await _receive(b)
        assert typing == {"type": "TYPING", "data": {"user_id": str(customer.id)}}

        await b.send(json.dumps({"type": "READ", "last_read_message_id": sent["id"]}))
        for socket in (a, b):
            event = await _receive(socket)
            assert event["type"] == "MESSAGE_READ"
            assert event["data"]["user_id"] == str(pro.id)

        await a.send(json.dumps({"type": "NOPE"}))
        assert (await _receive(a))["data"]["code"] == "UNKNOWN_TYPE"
        await a.send("not json")
        assert (await _receive(a))["data"]["code"] == "INVALID_FRAME"


async def test_ticket_rules(
    http: httpx.AsyncClient, live_server: str, seeded: Services, clock: FrozenClock
) -> None:
    customer, _, conversation_id = await _pair(http)
    _, _, other_conversation = await _pair(http)

    used = await ticket(http, customer, conversation_id)
    async with connect(_url(live_server, conversation_id, f"ticket={used}"), origin=ALLOWED_ORIGIN) as socket:
        await socket.send(json.dumps({"type": "PING"}))
        assert (await _receive(socket))["type"] == "PONG"
    await _expect_close(_url(live_server, conversation_id, f"ticket={used}"), 4401)  # single use

    expired = await ticket(http, customer, conversation_id)
    clock.advance(31)
    await _expect_close(_url(live_server, conversation_id, f"ticket={expired}"), 4401)

    wrong_scope = await ticket(http, customer, conversation_id)
    await _expect_close(_url(live_server, other_conversation, f"ticket={wrong_scope}"), 4403)

    foreign_origin = await ticket(http, customer, conversation_id)
    await _expect_close(
        _url(live_server, conversation_id, f"ticket={foreign_origin}"), 4403, origin="https://evil.example"
    )

    await _expect_close(_url(live_server, conversation_id, f"token={customer.access_token}"), 4401)
    await _expect_close(_url(live_server, conversation_id, "ticket=made-up-ticket-value-xxxxxxxxxxxxx"), 4401)
    await _expect_close(_url(live_server, conversation_id, ""), 4401)


async def test_revoked_session_closes_open_socket(
    http: httpx.AsyncClient, live_server: str, seeded: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_ws, "REVALIDATE_SECONDS", 0.2)
    customer, _, conversation_id = await _pair(http)
    raw = await ticket(http, customer, conversation_id)
    async with connect(_url(live_server, conversation_id, f"ticket={raw}"), origin=ALLOWED_ORIGIN) as socket:
        logout = await http.post(f"{API}/auth/logout", headers={**COOKIE_HEADERS, **customer.headers})
        assert logout.status_code == 204
        with pytest.raises(ConnectionClosed) as closed:
            await asyncio.wait_for(socket.recv(), 3)
    assert closed.value.rcvd is not None
    assert closed.value.rcvd.code == 4401


async def test_ticket_issued_then_session_revoked_is_rejected(
    http: httpx.AsyncClient, live_server: str, seeded: Services
) -> None:
    customer, _, conversation_id = await _pair(http)
    raw = await ticket(http, customer, conversation_id)
    await http.post(f"{API}/auth/logout-all", headers=customer.headers)
    await _expect_close(_url(live_server, conversation_id, f"ticket={raw}"), 4401)


async def test_inbound_flood_is_cut_off(http: httpx.AsyncClient, live_server: str, seeded: Services) -> None:
    customer, _, conversation_id = await _pair(http)
    raw = await ticket(http, customer, conversation_id)
    async with connect(_url(live_server, conversation_id, f"ticket={raw}"), origin=ALLOWED_ORIGIN) as socket:
        for _ in range(chat_ws.INBOUND_LIMIT + 5):
            await socket.send(json.dumps({"type": "TYPING"}))
        with pytest.raises(ConnectionClosed) as closed:
            await _drain(socket)
    assert closed.value.rcvd is not None
    assert closed.value.rcvd.code == 4429


async def test_reconnect_catches_up_from_history(
    http: httpx.AsyncClient, live_server: str, seeded: Services
) -> None:
    customer, pro, conversation_id = await _pair(http)
    raw = await ticket(http, customer, conversation_id)
    async with connect(_url(live_server, conversation_id, f"ticket={raw}"), origin=ALLOWED_ORIGIN) as socket:
        first = (await send(http, pro, conversation_id, "one")).json()
        assert (await _receive(socket))["data"]["id"] == first["id"]
    for body in ("two", "three"):  # sent while the customer is offline
        await send(http, pro, conversation_id, body)
    missed = await http.get(
        f"{API}/conversations/{conversation_id}/messages",
        params={"after": first["id"]},
        headers=customer.headers,
    )
    assert [m["body"] for m in missed.json()] == ["two", "three"]


async def test_call_signaling_is_relayed_only_within_the_session(
    http: httpx.AsyncClient, live_server: str, seeded: Services
) -> None:
    customer, pro, conversation_id = await _pair(http)
    outsider = await register(http)
    forbidden = await http.post(
        f"{API}/calls/sessions", json={"conversation_id": conversation_id}, headers=outsider.headers
    )
    assert forbidden.status_code == 404

    started = await http.post(
        f"{API}/calls/sessions", json={"conversation_id": conversation_id}, headers=customer.headers
    )
    assert started.status_code == 201
    call = started.json()
    assert call["status"] == "RINGING"
    assert call["ice_servers"][0]["urls"]
    busy = await http.post(
        f"{API}/calls/sessions", json={"conversation_id": conversation_id}, headers=pro.headers
    )
    assert busy.status_code == 409

    customer_url = _url(
        live_server, conversation_id, f"ticket={await ticket(http, customer, conversation_id)}"
    )
    pro_url = _url(live_server, conversation_id, f"ticket={await ticket(http, pro, conversation_id)}")
    async with (
        connect(customer_url, origin=ALLOWED_ORIGIN) as caller,
        connect(pro_url, origin=ALLOWED_ORIGIN) as callee,
    ):
        await callee.send(
            json.dumps({"type": "CALL_OFFER", "session_id": call["session_id"], "payload": {"sdp": "x"}})
        )
        assert (await _receive(callee))["data"]["code"] == "INVALID_SIGNAL"  # only the caller offers

        offer = {"type": "CALL_OFFER", "session_id": call["session_id"], "payload": {"sdp": "v=0 offer"}}
        await caller.send(json.dumps(offer))
        relayed = await _receive(callee)
        assert relayed["type"] == "CALL_OFFER"
        assert relayed["data"] == {
            "session_id": call["session_id"],
            "from": str(customer.id),
            "payload": {"sdp": "v=0 offer"},
        }

        await callee.send(
            json.dumps(
                {"type": "CALL_ANSWER", "session_id": call["session_id"], "payload": {"sdp": "answer"}}
            )
        )
        assert (await _receive(caller))["type"] == "CALL_ANSWER"
        await caller.send(
            json.dumps({"type": "CALL_ICE", "session_id": call["session_id"], "payload": {"candidate": "c"}})
        )
        assert (await _receive(callee))["type"] == "CALL_ICE"

        ended = await http.post(
            f"{API}/calls/sessions/{call['session_id']}/end", json={}, headers=pro.headers
        )
        assert ended.json()["status"] == "ENDED"
        assert (await _receive(caller))["type"] == "CALL_END"

        late = {"type": "CALL_ICE", "session_id": call["session_id"], "payload": {}}
        await caller.send(json.dumps(late))
        assert (await _receive(caller))["data"]["code"] == "CALL_NOT_ACTIVE"
