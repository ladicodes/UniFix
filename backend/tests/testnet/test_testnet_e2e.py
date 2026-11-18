"""Real Stellar TESTNET end-to-end through the HTTP API (Issues 5-6).

register → wallets (SEP-53 + Horizon) → quote → accept → fund (operator co-signed) → start →
complete (signed on-chain) → approve → release confirmed → receipts; fund → refund; and the
keeper's auto-release after the review window (short-windows deployment).
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import pytest
from stellar_sdk import Keypair

from tests.support import (
    API,
    Account,
    open_conversation,
    quote_payload,
    register,
    register_professional,
    sign,
)
from tests.support import verify_email as confirm_email
from tests.testnet.conftest import Testnet

pytestmark = pytest.mark.testnet
EXPLORER = "https://stellar.expert/explorer/testnet/tx/"
OUT = Path(__file__).resolve().parents[2] / "var" / "testnet"


async def _link(t: Testnet, account: Account, keypair: Keypair) -> None:
    challenge = (
        await t.client.post(
            f"{API}/wallets/challenge", json={"address": keypair.public_key}, headers=account.headers
        )
    ).json()
    signature = base64.b64encode(keypair.sign_message(challenge["message"])).decode()
    linked = await t.client.post(
        f"{API}/wallets",
        json={"address": keypair.public_key, "message": challenge["message"], "signature": signature},
        headers=account.headers,
    )
    assert linked.status_code == 200, linked.text
    wallets = (await t.client.get(f"{API}/wallets", headers=account.headers)).json()
    assert wallets[0]["account_exists"] is True
    assert wallets[0]["has_escrow_trustline"] is True


async def _deal(t: Testnet, *, labour: int = 150_000) -> dict[str, Any]:
    customer = await register(t.client)
    professional, professional_id = await register_professional(t.client)
    await confirm_email(t.client, t.outbox, customer)
    await confirm_email(t.client, t.outbox, professional)
    await _link(t, customer, t.keys["customer"])
    await _link(t, professional, t.keys["professional"])
    conversation = await open_conversation(t.client, customer, professional_id)
    quote = await t.client.post(
        f"{API}/quotes",
        json=quote_payload(conversation, labour_minor=labour, materials_minor=15_000),
        headers=professional.headers,
    )
    accepted = await t.client.post(
        f"{API}/quotes/{quote.json()['id']}/accept",
        json={"service_address": "Room 214"},
        headers=customer.headers,
    )
    assert accepted.status_code == 201, accepted.text
    return {
        "customer": customer,
        "professional": professional,
        "professional_id": professional_id,
        "booking_id": accepted.json()["booking"]["id"],
    }


async def _status(t: Testnet, deal: dict[str, Any]) -> dict[str, Any]:
    response = await t.client.get(f"{API}/bookings/{deal['booking_id']}", headers=deal["customer"].headers)
    return dict(response.json())


async def _act(
    t: Testnet,
    label: str,
    path: str,
    account: Account,
    keypair: Keypair,
    body: dict[str, Any],
    submit: str | None = None,
) -> str:
    prepared = await t.client.post(f"{API}{path}", json=body, headers=account.headers)
    assert prepared.status_code == 200, prepared.text
    tx_hash = prepared.json()["tx_hash"]
    submitted = await t.client.post(
        f"{API}{submit or path}",
        json={"signed_xdr": sign(prepared.json()["unsigned_xdr"], keypair)},
        headers=account.headers,
    )
    assert submitted.status_code == 200, submitted.text
    t.log.append({"step": label, "tx": tx_hash, "url": EXPLORER + tx_hash})
    print(f"  {label:32} {EXPLORER}{tx_hash}")
    return str(tx_hash)


async def _wait_status(t: Testnet, deal: dict[str, Any], status: str, timeout: float = 120) -> dict[str, Any]:
    async def reached() -> bool:
        return bool((await _status(t, deal))["booking"]["status"] == status)

    await t.until(reached, f"booking {status}", timeout)
    return await _status(t, deal)


def _save(t: Testnet, name: str) -> None:
    (OUT / f"e2e-{name}-{int(time.time())}.json").write_text(json.dumps(t.log, indent=2))


async def test_testnet_happy_path_fund_complete_release(testnet: Testnet) -> None:
    t = testnet
    deal = await _deal(t)
    prepared = await t.client.post(
        f"{API}/bookings/{deal['booking_id']}/escrow", json={}, headers=deal["customer"].headers
    )
    escrow = prepared.json()["escrow"]
    assert escrow["fx"]["is_demo_rate"] is True
    await _act(
        t,
        "fund",
        f"/bookings/{deal['booking_id']}/escrow",
        deal["customer"],
        t.keys["customer"],
        {},
        submit=f"/escrows/{escrow['id']}/funding",
    )
    funded = await _wait_status(t, deal, "FUNDED")
    proof = (
        await t.client.get(f"{API}/bookings/{deal['booking_id']}/agreement", headers=deal["customer"].headers)
    ).json()
    onchain = await t.stellar.require().get_escrow(bytes.fromhex(funded["escrow"]["escrow_id_hex"]))
    assert onchain is not None
    assert onchain.terms_hash == proof["terms_hash"]  # the agreement is bound on-chain
    assert (
        await t.client.post(
            f"{API}/bookings/{deal['booking_id']}/start", headers=deal["professional"].headers
        )
    ).status_code == 200
    await _act(
        t,
        "submit_completion",
        f"/bookings/{deal['booking_id']}/completion",
        deal["professional"],
        t.keys["professional"],
        {"notes": "Done and tested"},
        submit=f"/bookings/{deal['booking_id']}/completion/submit",
    )
    await _wait_status(t, deal, "COMPLETION_SUBMITTED")
    await _act(
        t, "release (approve)", f"/escrows/{escrow['id']}/release", deal["customer"], t.keys["customer"], {}
    )
    done = await _wait_status(t, deal, "COMPLETED")
    assert done["escrow"]["settled_by"] == "CUSTOMER"
    receipts = (
        await t.client.get(f"{API}/bookings/{deal['booking_id']}/receipts", headers=deal["customer"].headers)
    ).json()
    assert [r["kind"] for r in receipts] == ["FUNDING", "RELEASE"]
    assert all(r["fx"]["is_demo_rate"] for r in receipts)
    assert (await t.client.get(f"{API}/professionals/{deal['professional_id']}")).json()[
        "completed_jobs"
    ] == 1
    _save(t, "happy")


async def test_testnet_fund_then_professional_refund(testnet: Testnet) -> None:
    t = testnet
    deal = await _deal(t)
    prepared = await t.client.post(
        f"{API}/bookings/{deal['booking_id']}/escrow", json={}, headers=deal["customer"].headers
    )
    escrow_id = prepared.json()["escrow"]["id"]
    await _act(
        t,
        "fund",
        f"/bookings/{deal['booking_id']}/escrow",
        deal["customer"],
        t.keys["customer"],
        {},
        submit=f"/escrows/{escrow_id}/funding",
    )
    await _wait_status(t, deal, "FUNDED")
    await _act(
        t,
        "refund (professional)",
        f"/escrows/{escrow_id}/refund",
        deal["professional"],
        t.keys["professional"],
        {},
    )
    refunded = await _wait_status(t, deal, "REFUNDED")
    assert refunded["escrow"]["customer_refund"] == refunded["escrow"]["asset_amount"]
    _save(t, "refund")


async def test_testnet_keeper_auto_releases_after_review_window(testnet_short: Testnet) -> None:
    t = testnet_short
    deal = await _deal(t)
    prepared = await t.client.post(
        f"{API}/bookings/{deal['booking_id']}/escrow", json={}, headers=deal["customer"].headers
    )
    escrow_id = prepared.json()["escrow"]["id"]
    await _act(
        t,
        "fund",
        f"/bookings/{deal['booking_id']}/escrow",
        deal["customer"],
        t.keys["customer"],
        {},
        submit=f"/escrows/{escrow_id}/funding",
    )
    await _wait_status(t, deal, "FUNDED")
    await _act(
        t,
        "submit_completion",
        f"/bookings/{deal['booking_id']}/completion",
        deal["professional"],
        t.keys["professional"],
        {"notes": "Done"},
        submit=f"/bookings/{deal['booking_id']}/completion/submit",
    )
    await _wait_status(t, deal, "COMPLETION_SUBMITTED")
    done = await _wait_status(t, deal, "COMPLETED", timeout=360)  # review window 120 s, then the keeper
    assert done["escrow"]["settled_by"] == "TIMEOUT"
    finalize = [x for x in done["escrow"]["transactions"] if x["kind"] == "FINALIZE"]
    assert len(finalize) == 1
    t.log.append(
        {
            "step": "keeper finalize_expired (auto-release)",
            "tx": finalize[0]["hash"],
            "url": EXPLORER + finalize[0]["hash"],
        }
    )
    print(f"  keeper auto-release              {EXPLORER}{finalize[0]['hash']}")
    _save(t, "keeper")
