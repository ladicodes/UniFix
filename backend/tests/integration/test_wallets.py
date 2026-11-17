"""Wallet ownership through SEP-53 challenges (PostgreSQL + chain test double)."""

from __future__ import annotations

import base64
from datetime import timedelta

import httpx
from stellar_sdk import Keypair

from app.core.clock import FrozenClock
from app.core.container import Services
from tests.chain import FakeChain
from tests.support import API, link_wallet, register, relogin


async def _challenge(client: httpx.AsyncClient, account, address: str) -> str:  # type: ignore[no-untyped-def]
    response = await client.post(
        f"{API}/wallets/challenge", json={"address": address}, headers=account.headers
    )
    assert response.status_code == 201, response.text
    return str(response.json()["message"])


def _sign(keypair: Keypair, message: str) -> str:
    return base64.b64encode(keypair.sign_message(message)).decode()


async def test_link_wallet_end_to_end(
    client: httpx.AsyncClient, services: Services, chain: FakeChain
) -> None:
    user = await register(client)
    keypair = Keypair.random()
    chain.create_account(keypair.public_key, trustline=False)
    message = await _challenge(client, user, keypair.public_key)
    assert f"Address: {keypair.public_key}" in message
    assert "Network: Test SDF Network ; September 2015" in message
    linked = await client.post(
        f"{API}/wallets",
        json={"address": keypair.public_key, "message": message, "signature": _sign(keypair, message)},
        headers=user.headers,
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["wallet_address"] == keypair.public_key
    assert linked.json()["wallet_verified"] is True
    me = (await client.get(f"{API}/auth/me", headers=user.headers)).json()
    assert me["wallet_address"] == keypair.public_key
    wallets = (await client.get(f"{API}/wallets", headers=user.headers)).json()
    assert len(wallets) == 1
    assert wallets[0] | {"id": None, "verified_at": None} == {
        "id": None, "verified_at": None, "address": keypair.public_key, "network": "TESTNET",
        "is_primary": True, "account_exists": True, "has_escrow_trustline": False,
    }  # fmt: skip


async def test_challenge_is_single_use_and_bound(
    client: httpx.AsyncClient, services: Services, chain: FakeChain
) -> None:
    user = await register(client)
    keypair, other = Keypair.random(), Keypair.random()
    chain.create_account(keypair.public_key)
    chain.create_account(other.public_key)
    message = await _challenge(client, user, keypair.public_key)
    # Signed by a different key.
    wrong = await client.post(
        f"{API}/wallets",
        json={"address": keypair.public_key, "message": message, "signature": _sign(other, message)},
        headers=user.headers,
    )
    assert (wrong.status_code, wrong.json()["code"]) == (400, "INVALID_SIGNATURE")
    # The challenge was consumed by that attempt.
    reused = await client.post(
        f"{API}/wallets",
        json={"address": keypair.public_key, "message": message, "signature": _sign(keypair, message)},
        headers=user.headers,
    )
    assert reused.json()["code"] == "CHALLENGE_INVALID"
    # Mismatched address: the challenge was issued for another one.
    message = await _challenge(client, user, keypair.public_key)
    mismatch = await client.post(
        f"{API}/wallets",
        json={"address": other.public_key, "message": message, "signature": _sign(other, message)},
        headers=user.headers,
    )
    assert mismatch.json()["code"] == "CHALLENGE_INVALID"
    # Another user cannot use my challenge.
    intruder = await register(client)
    stolen = await client.post(
        f"{API}/wallets",
        json={"address": keypair.public_key, "message": message, "signature": _sign(keypair, message)},
        headers=intruder.headers,
    )
    assert stolen.json()["code"] == "CHALLENGE_INVALID"


async def test_challenge_expires(
    client: httpx.AsyncClient, services: Services, chain: FakeChain, clock: FrozenClock
) -> None:
    user = await register(client)
    keypair = Keypair.random()
    chain.create_account(keypair.public_key)
    message = await _challenge(client, user, keypair.public_key)
    clock.advance(timedelta(minutes=5, seconds=1).total_seconds())
    user = await relogin(client, user)
    expired = await client.post(
        f"{API}/wallets",
        json={"address": keypair.public_key, "message": message, "signature": _sign(keypair, message)},
        headers=user.headers,
    )
    assert expired.json()["code"] == "CHALLENGE_INVALID"


async def test_invalid_addresses_and_missing_accounts(
    client: httpx.AsyncClient, services: Services, chain: FakeChain
) -> None:
    user = await register(client)
    address = Keypair.random().public_key
    corrupted = address[:-1] + ("A" if address[-1] != "A" else "B")
    bad = await client.post(f"{API}/wallets/challenge", json={"address": corrupted}, headers=user.headers)
    assert (bad.status_code, bad.json()["code"]) == (400, "INVALID_WALLET_ADDRESS")
    unfunded = Keypair.random()
    message = await _challenge(client, user, unfunded.public_key)
    missing = await client.post(
        f"{API}/wallets",
        json={"address": unfunded.public_key, "message": message, "signature": _sign(unfunded, message)},
        headers=user.headers,
    )
    assert missing.json()["code"] == "WALLET_ACCOUNT_NOT_FOUND"
    assert (await client.post(f"{API}/wallets/challenge", json={"address": address})).status_code == 401


async def test_one_owner_per_address(client: httpx.AsyncClient, services: Services, chain: FakeChain) -> None:
    first, second = await register(client), await register(client)
    keypair = await link_wallet(client, chain, first)
    message = await _challenge(client, second, keypair.public_key)
    taken = await client.post(
        f"{API}/wallets",
        json={"address": keypair.public_key, "message": message, "signature": _sign(keypair, message)},
        headers=second.headers,
    )
    assert (taken.status_code, taken.json()["code"]) == (409, "WALLET_IN_USE")
    # Re-verifying your own wallet is harmless.
    await link_wallet(client, chain, first, keypair)
    assert len((await client.get(f"{API}/wallets", headers=first.headers)).json()) == 1


async def test_remove_wallet_promotes_another(
    client: httpx.AsyncClient, services: Services, chain: FakeChain
) -> None:
    user = await register(client)
    first = await link_wallet(client, chain, user)
    second = await link_wallet(client, chain, user)
    wallets = (await client.get(f"{API}/wallets", headers=user.headers)).json()
    assert [w["is_primary"] for w in wallets] == [True, False]
    primary_id = wallets[0]["id"]
    other = await register(client)
    assert (await client.delete(f"{API}/wallets/{primary_id}", headers=other.headers)).status_code == 404
    assert (await client.delete(f"{API}/wallets/{primary_id}", headers=user.headers)).status_code == 204
    remaining = (await client.get(f"{API}/wallets", headers=user.headers)).json()
    assert [(w["address"], w["is_primary"]) for w in remaining] == [(second.public_key, True)]
    # The address can now be linked again (by anyone who can sign for it).
    await link_wallet(client, chain, other, first)


async def test_wallets_degrade_when_network_is_down(
    client: httpx.AsyncClient, services: Services, chain: FakeChain
) -> None:
    user = await register(client)
    await link_wallet(client, chain, user)
    chain.offline = True
    wallets = (await client.get(f"{API}/wallets", headers=user.headers)).json()
    assert wallets[0]["account_exists"] is None
    keypair = Keypair.random()
    message = await _challenge(client, user, keypair.public_key)
    down = await client.post(
        f"{API}/wallets",
        json={"address": keypair.public_key, "message": message, "signature": _sign(keypair, message)},
        headers=user.headers,
    )
    assert (down.status_code, down.json()["code"]) == (503, "CHAIN_UNAVAILABLE")
