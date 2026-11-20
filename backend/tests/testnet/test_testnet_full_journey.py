"""The PRD definition of done on real TESTNET, through the HTTP API only (Issue 8).

customer signs up -> professional verified by an admin -> service request -> quote -> accept ->
fund -> communicate -> complete -> confirm -> release -> review -> rating updates -> the admin
sees the whole transaction. Negative paths run against the same live deployment.

Run: ``UNIFIX_TESTNET=1 uv run pytest -m testnet -s tests/testnet/test_testnet_full_journey.py``
(or ``uv run python -m scripts.e2e_testnet``, which also writes the tx-hash report).
"""

from __future__ import annotations

import pytest

from tests.support import (
    API,
    PDF_BYTES,
    category_id,
    create_admin_account,
    quote_payload,
    register,
    register_professional,
    send,
    sign,
    upload,
)
from tests.support import verify_email as confirm_email
from tests.testnet.conftest import Testnet
from tests.testnet.test_testnet_e2e import _act, _link, _save, _wait_status

pytestmark = pytest.mark.testnet


async def test_testnet_prd_definition_of_done(testnet: Testnet) -> None:
    t = testnet
    client = t.client
    admin = await create_admin_account(client, t.services)

    # Sign-up and a professional verified by an admin.
    customer = await register(client, name="Amaka Obi")
    professional, professional_id = await register_professional(client, name="Kunle Ade")
    await confirm_email(client, t.outbox, customer)
    await confirm_email(client, t.outbox, professional)
    document = (
        await upload(client, professional, "VERIFICATION_DOCUMENT", PDF_BYTES, filename="id.pdf")
    ).json()
    submitted = await client.post(
        f"{API}/professionals/me/verifications",
        json={"type": "IDENTITY", "file_ids": [document["id"]], "note": "NIN slip"},
        headers=professional.headers,
    )
    assert submitted.status_code == 200, submitted.text
    item = (await client.get(f"{API}/admin/verifications", headers=admin.headers)).json()[0]
    decided = await client.post(
        f"{API}/admin/verifications/{item['id']}/decision",
        json={"decision": "VERIFIED"},
        headers=admin.headers,
    )
    assert decided.status_code == 200, decided.text
    await _link(t, customer, t.keys["customer"])
    await _link(t, professional, t.keys["professional"])

    # Request -> the professional responds -> quote -> accept.
    request = await client.post(
        f"{API}/service-requests",
        json={
            "category_id": await category_id(client, "phone-repair"),
            "title": "Cracked phone screen",
            "description": "Screen cracked; touch still works.",
            "location_text": "Room 214, Moremi Hall",
        },
        headers=customer.headers,
    )
    assert request.status_code == 201, request.text
    conversation = await client.post(
        f"{API}/service-requests/{request.json()['id']}/respond",
        json={"message": "I can fix this today"},
        headers=professional.headers,
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    quote = await client.post(
        f"{API}/quotes",
        json=quote_payload(conversation_id, labour_minor=150_000, materials_minor=15_000),
        headers=professional.headers,
    )
    assert quote.status_code == 201, quote.text
    accepted = await client.post(
        f"{API}/quotes/{quote.json()['id']}/accept",
        json={"service_address": "Room 214"},
        headers=customer.headers,
    )
    assert accepted.status_code == 201, accepted.text
    deal = {
        "customer": customer,
        "professional": professional,
        "booking_id": accepted.json()["booking"]["id"],
    }
    booking_id = deal["booking_id"]

    # Unauthorized calls: a stranger cannot see or fund the booking.
    stranger = await register(client)
    assert (await client.get(f"{API}/bookings/{booking_id}", headers=stranger.headers)).status_code == 404
    assert (
        await client.post(f"{API}/bookings/{booking_id}/escrow", json={}, headers=stranger.headers)
    ).status_code == 404
    # Invalid transition: work cannot start before funding.
    early = await client.post(f"{API}/bookings/{booking_id}/start", headers=professional.headers)
    assert early.status_code == 409

    # Fund (and a duplicate funding attempt is refused).
    prepared = await client.post(f"{API}/bookings/{booking_id}/escrow", json={}, headers=customer.headers)
    assert prepared.status_code == 200, prepared.text
    escrow = prepared.json()["escrow"]
    signed = sign(prepared.json()["unsigned_xdr"], t.keys["customer"])
    funded_tx = await client.post(
        f"{API}/escrows/{escrow['id']}/funding", json={"signed_xdr": signed}, headers=customer.headers
    )
    assert funded_tx.status_code == 200, funded_tx.text
    t.log.append({"step": "fund", "tx": prepared.json()["tx_hash"]})
    print(f"  fund                             {prepared.json()['tx_hash']}")
    await _wait_status(t, deal, "FUNDED")
    again = await client.post(f"{API}/bookings/{booking_id}/escrow", json={}, headers=customer.headers)
    assert again.status_code == 409, again.text

    # Communicate, start, complete (signed on-chain), confirm and release.
    assert (await send(client, customer, conversation_id, "See you at 3pm")).status_code in {200, 201}
    assert (
        await client.post(f"{API}/bookings/{booking_id}/start", headers=professional.headers)
    ).status_code == 200
    await _act(
        t, "submit_completion", f"/bookings/{booking_id}/completion", professional, t.keys["professional"],
        {"notes": "Screen replaced and tested"}, submit=f"/bookings/{booking_id}/completion/submit",
    )  # fmt: skip
    await _wait_status(t, deal, "COMPLETION_SUBMITTED")
    await _act(t, "release (confirm)", f"/escrows/{escrow['id']}/release", customer, t.keys["customer"], {})
    done = await _wait_status(t, deal, "COMPLETED")
    assert done["escrow"]["settled_by"] == "CUSTOMER"
    # Retrying a settled release is refused.
    retry = await client.post(f"{API}/escrows/{escrow['id']}/release", json={}, headers=customer.headers)
    assert retry.status_code == 409

    # Review -> rating updates (and a duplicate review is refused).
    review = {
        "ratings": {"quality": 5, "punctuality": 4, "communication": 5, "professionalism": 5, "value": 4},
        "comment": "Fast and careful.",
    }
    created = await client.post(f"{API}/bookings/{booking_id}/reviews", json=review, headers=customer.headers)
    assert created.status_code == 201, created.text
    duplicate = await client.post(
        f"{API}/bookings/{booking_id}/reviews", json=review, headers=customer.headers
    )
    assert duplicate.status_code == 409
    profile = (await client.get(f"{API}/professionals/{professional_id}")).json()
    assert (profile["review_count"], profile["completed_jobs"], profile["verification_status"]) == (
        1,
        1,
        "VERIFIED",
    )
    assert profile["rating"] == pytest.approx(4.6)

    # Notifications reached both parties.
    pro_kinds = {
        n["type"]
        for n in (await client.get(f"{API}/notifications?limit=100", headers=professional.headers)).json()
    }
    assert {
        "VERIFICATION_APPROVED",
        "QUOTE_ACCEPTED",
        "BOOKING_FUNDED",
        "PAYMENT_RELEASED",
        "REVIEW_RECEIVED",
    } <= pro_kinds
    customer_kinds = {
        n["type"]
        for n in (await client.get(f"{API}/notifications?limit=100", headers=customer.headers)).json()
    }
    assert {
        "QUOTE_RECEIVED",
        "BOOKING_FUNDED",
        "JOB_STARTED",
        "COMPLETION_SUBMITTED",
        "PAYMENT_RELEASED",
    } <= customer_kinds

    # The admin sees the whole transaction.
    bookings = (
        await client.get(f"{API}/admin/bookings?customer_id={customer.id}", headers=admin.headers)
    ).json()
    assert [(b["id"], b["status"], b["escrow_state"]) for b in bookings] == [
        (booking_id, "COMPLETED", "RELEASED")
    ]
    txs = (
        await client.get(f"{API}/admin/chain-transactions?escrow_id={escrow['id']}", headers=admin.headers)
    ).json()
    assert {(tx["kind"], tx["status"]) for tx in txs} == {
        ("FUND", "CONFIRMED"),
        ("SUBMIT_COMPLETION", "CONFIRMED"),
        ("RELEASE", "CONFIRMED"),
    }
    audit = (
        await client.get(f"{API}/admin/audit-logs?entity_id={booking_id}&limit=100", headers=admin.headers)
    ).json()
    actions = {entry["action"] for entry in audit}
    assert {"quote.accepted", "booking.transition", "escrow.fund_prepared"} <= actions
    status = (await client.get(f"{API}/admin/ops/status", headers=admin.headers)).json()
    assert status["rpc"]["healthy"] is True
    assert status["failed_verification_count"] == 0
    _save(t, "prd-journey")
