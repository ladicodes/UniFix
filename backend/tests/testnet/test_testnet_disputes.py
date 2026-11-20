"""Real Stellar TESTNET: disputes through the HTTP API (Issue 7).

fund → dispute lock → arbiter resolves RELEASE / REFUND / SPLIT; a concession by each party;
and the on-chain refusals: finalize_expired on a disputed escrow, resolve on an undisputed one,
and a party moving funds toward themselves while disputed.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from app.modules.stellar import contract
from app.modules.stellar.contract import Function
from app.modules.stellar.errors import ChainRejected
from tests.support import API, create_admin_account, sign
from tests.testnet.conftest import Testnet
from tests.testnet.test_testnet_e2e import EXPLORER, _act, _deal, _save, _wait_status

pytestmark = pytest.mark.testnet


async def _funded_dispute(t: Testnet, *, by: str = "customer") -> tuple[dict[str, Any], dict[str, Any], str]:
    deal = await _deal(t)
    prepared = await t.client.post(
        f"{API}/bookings/{deal['booking_id']}/escrow", json={}, headers=deal["customer"].headers
    )
    escrow = prepared.json()["escrow"]
    await _act(
        t,
        "fund",
        f"/bookings/{deal['booking_id']}/escrow",
        deal["customer"],
        t.keys["customer"],
        {},
        submit=f"/escrows/{escrow['id']}/funding",
    )
    await _wait_status(t, deal, "FUNDED")
    account, key = (
        (deal["customer"], t.keys["customer"])
        if by == "customer"
        else (deal["professional"], t.keys["professional"])
    )
    opened = await t.client.post(
        f"{API}/escrows/{escrow['id']}/disputes",
        json={"reason": "QUALITY", "details": "Testnet dispute run."},
        headers=account.headers,
    )
    assert opened.status_code == 201, opened.text
    dispute_id = opened.json()["dispute"]["id"]
    submitted = await t.client.post(
        f"{API}/disputes/{dispute_id}/lock",
        json={"signed_xdr": sign(opened.json()["unsigned_xdr"], key)},
        headers=account.headers,
    )
    assert submitted.status_code == 200, submitted.text
    t.log.append(
        {
            "step": f"open_dispute ({by})",
            "tx": opened.json()["tx_hash"],
            "url": EXPLORER + opened.json()["tx_hash"],
        }
    )
    print(f"  open_dispute ({by:12})          {EXPLORER}{opened.json()['tx_hash']}")
    await _wait_status(t, deal, "DISPUTED")
    return deal, escrow, dispute_id


async def _attempt(t: Testnet, signer: str, function: Function, args: list[Any]) -> str:
    """Try a call as ``signer`` all the way to the network; return how the chain refused it."""
    import asyncio

    gateway = t.stellar.require()
    keypair = t.keys[signer]
    try:
        prepared = await gateway.prepare_call(
            source=keypair.public_key,
            function=function,
            args=args,
            valid_until=int(t.services.clock.now().timestamp()) + 300,
        )
    except ChainRejected as rejected:
        return f"simulation: {rejected.code}"
    prepared.envelope.sign(keypair)  # only the caller's own signature: the other party's auth is missing
    sent = await gateway.send(prepared.envelope)
    if sent.status == "ERROR":
        return "rejected at submission"
    for _ in range(30):
        status = await gateway.get_transaction(prepared.tx_hash)
        if status.status != "NOT_FOUND":
            assert status.status == "FAILED", status
            t.log.append(
                {"step": "failed on-chain", "tx": prepared.tx_hash, "url": EXPLORER + prepared.tx_hash}
            )
            return f"transaction failed on-chain ({prepared.tx_hash})"
        await asyncio.sleep(2)
    raise AssertionError("the attempt neither failed nor landed")


async def _arbiter(t: Testnet) -> Any:
    admin = await create_admin_account(t.client, t.services)
    key = t.keys["arbiter"]
    challenge = (
        await t.client.post(
            f"{API}/wallets/challenge", json={"address": key.public_key}, headers=admin.headers
        )
    ).json()
    signature = base64.b64encode(key.sign_message(challenge["message"])).decode()
    linked = await t.client.post(
        f"{API}/wallets",
        headers=admin.headers,
        json={"address": key.public_key, "message": challenge["message"], "signature": signature},
    )
    assert linked.status_code == 200, linked.text
    return admin


@pytest.mark.parametrize(
    ("body", "status", "outcome"),
    [
        ({"outcome": "RELEASE", "note": "Testnet: work done"}, "COMPLETED", "RELEASE"),
        ({"outcome": "REFUND", "note": "Testnet: not done"}, "REFUNDED", "REFUND"),
        (
            {"outcome": "SPLIT", "split_bps_to_professional": 4_000, "note": "Testnet: partly done"},
            "RESOLVED",
            "SPLIT",
        ),
    ],
)
async def test_testnet_arbiter_resolves(
    testnet: Testnet, body: dict[str, Any], status: str, outcome: str
) -> None:
    t = testnet
    deal, _escrow, dispute_id = await _funded_dispute(t)
    admin = await _arbiter(t)
    await _act(t, f"resolve {outcome}", f"/disputes/{dispute_id}/resolve", admin, t.keys["arbiter"], body)
    done = await _wait_status(t, deal, status)
    assert (done["dispute"]["outcome"], done["escrow"]["settled_by"]) == (outcome, "ARBITER")
    _save(t, f"resolve-{outcome.lower()}")


@pytest.mark.parametrize("who", ["customer", "professional"])
async def test_testnet_concession(testnet: Testnet, who: str) -> None:
    t = testnet
    deal, escrow, _ = await _funded_dispute(t, by="professional" if who == "customer" else "customer")
    key = bytes.fromhex(escrow["escrow_id_hex"])
    # On-chain refusals while disputed: no timeout exit, and no party can pay themselves.
    for label, signer, function in (
        ("finalize_expired on a disputed escrow", "operator", Function.FINALIZE_EXPIRED),
        ("customer refunds themselves", "customer", Function.REFUND),
        ("professional releases to themselves", "professional", Function.RELEASE),
    ):
        outcome = await _attempt(t, signer, function, contract.escrow_only_args(key))
        t.log.append({"step": label, "refused": outcome})
        print(f"  {label:40} refused on-chain: {outcome}")
    if who == "customer":
        await _act(
            t,
            "customer concedes (release)",
            f"/escrows/{escrow['id']}/release",
            deal["customer"],
            t.keys["customer"],
            {},
        )
        expected = ("COMPLETED", "CONCEDED_RELEASE")
    else:
        await _act(
            t,
            "professional concedes (refund)",
            f"/escrows/{escrow['id']}/refund",
            deal["professional"],
            t.keys["professional"],
            {},
        )
        expected = ("REFUNDED", "CONCEDED_REFUND")
    done = await _wait_status(t, deal, expected[0])
    assert done["dispute"]["outcome"] == expected[1]
    _save(t, f"concede-{who}")


async def test_testnet_arbiter_cannot_resolve_an_undisputed_escrow(testnet: Testnet) -> None:
    t = testnet
    deal = await _deal(t)
    prepared = await t.client.post(
        f"{API}/bookings/{deal['booking_id']}/escrow", json={}, headers=deal["customer"].headers
    )
    escrow = prepared.json()["escrow"]
    await _act(
        t,
        "fund",
        f"/bookings/{deal['booking_id']}/escrow",
        deal["customer"],
        t.keys["customer"],
        {},
        submit=f"/escrows/{escrow['id']}/funding",
    )
    await _wait_status(t, deal, "FUNDED")
    with pytest.raises(ChainRejected) as refused:
        await t.stellar.require().prepare_call(
            source=t.keys["arbiter"].public_key,
            function=Function.RESOLVE,
            args=contract.resolve_args(bytes.fromhex(escrow["escrow_id_hex"]), 1),
            valid_until=int(t.services.clock.now().timestamp()) + 300,
        )
    assert refused.value.code == "CONTRACT_INVALID_STATE"
    print("  arbiter resolve on undisputed escrow      refused on-chain: CONTRACT_INVALID_STATE")
