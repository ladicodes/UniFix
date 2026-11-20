"""Escrow funding, completion, release, refunds, keeper and the exactly-once reconciler.

PostgreSQL 16 + the in-memory chain double (tests/chain.py). Real-network behaviour of the same
adapter is verified separately on testnet (scripts/testnet.py, tests marked ``testnet``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text, update

from app.core.clock import FrozenClock
from app.core.config import StellarNetwork
from app.core.container import Services
from app.modules.payments import fx
from app.modules.payments.models import ChainEvent, ChainTransaction, Escrow, LedgerEntry, Receipt
from app.modules.payments.reconciler import RECONCILER_LOCK_ID, Reconciler
from app.modules.stellar import contract
from app.modules.stellar.context import StellarContext
from app.modules.stellar.contract import Function
from tests.chain import FakeChain
from tests.conftest import OPERATOR
from tests.support import (
    API,
    Deal,
    RecordingEmailSender,
    booking,
    chain_action,
    create_admin_account,
    fund,
    image_bytes,
    make_deal,
    register,
    relogin,
    sign,
    upload,
)

AMOUNT_UNITS = 212_121_213  # ₦35,000.00 at the 1650 demo rate, rounded up (STELLAR_ESCROW_DESIGN §8)


async def _count(services: Services, model: Any, **where: Any) -> int:
    async with services.session_factory() as session:
        statement = select(func.count()).select_from(model)
        for column, value in where.items():
            statement = statement.where(getattr(model, column) == value)
        return int((await session.execute(statement)).scalar_one())


async def _escrow_row(services: Services, booking_id: str) -> Escrow:
    async with services.session_factory() as session:
        row = (await session.execute(select(Escrow).where(Escrow.booking_id == booking_id))).scalar_one()
        return row


async def _complete(client: httpx.AsyncClient, chain: FakeChain, reconciler: Reconciler, deal: Deal) -> None:
    await chain_action(
        client,
        chain,
        reconciler,
        f"/bookings/{deal.booking_id}/completion",
        deal.professional,
        deal.professional_wallet,
        {"notes": "Screen replaced and tested", "checklist": [{"label": "Touch", "done": True}]},
        submit_path=f"/bookings/{deal.booking_id}/completion/submit",
    )


# ---------------------------------------------------------------- conversion


def test_fx_conversion_boundary_vectors(settings: Any) -> None:
    rate = fx.parse_rate("1650.00000000")
    assert fx.to_asset_units(3_500_000, "NGN", rate, 7) == AMOUNT_UNITS  # 212,121,212.12… → up
    assert fx.to_asset_units(165_000, "NGN", rate, 7) == 10_000_000  # exactly 1 USDC: no rounding
    assert fx.to_asset_units(1, "NGN", rate, 7) == 61  # 60.606… → 61 (never rounds to zero)
    assert fx.to_asset_units(165_001, "NGN", rate, 7) == 10_000_061
    assert fx.to_asset_units(10**15, "NGN", fx.parse_rate("0.00000001"), 7) == 10**28  # i128-sized, exact
    assert fx.to_asset_units(1_000, "GHS", fx.parse_rate("15.5"), 7) == 6_451_613
    with pytest.raises(fx.RateUnavailable):
        fx.parse_rate("1650.000000001")  # more than 8 places
    for bad in ("0", "-1", "nan", "abc"):
        with pytest.raises(fx.RateUnavailable):
            fx.parse_rate(bad)
    with pytest.raises(ValueError, match="positive"):
        fx.to_asset_units(0, "NGN", rate, 7)


def test_demo_rate_is_labelled_and_refused_off_testnet(settings: Any) -> None:
    from datetime import UTC, datetime

    locked = fx.lock_rate(settings, "NGN", datetime.now(UTC))
    assert (locked.source, locked.is_demo_rate, locked.rate_text) == (
        "DEMO_FIXED_RATE",
        True,
        "1650.00000000",
    )
    mainnet = settings.model_copy(update={"stellar_network": StellarNetwork.PUBLIC})
    with pytest.raises(fx.RateUnavailable, match="testnet-only"):
        fx.lock_rate(mainnet, "NGN", datetime.now(UTC))


# ---------------------------------------------------------------- the happy path


async def test_fund_complete_release_end_to_end(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    pending = await booking(client, deal)
    assert "FUND" in pending["allowed_actions"]

    prepared = await client.post(
        f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers
    )
    assert prepared.status_code == 200, prepared.text
    escrow = prepared.json()["escrow"]
    assert escrow["state"] == "CREATED"
    assert escrow["reconciliation"] == "AWAITING_SIGNATURE"
    assert escrow["asset_amount"] == str(AMOUNT_UNITS)
    assert escrow["fiat"] == {"amount_minor": 3_500_000, "currency": "NGN"}
    assert escrow["fx"]["is_demo_rate"] is True
    assert escrow["fx"]["source"] == "DEMO_FIXED_RATE"
    assert escrow["customer_wallet"] == deal.customer_wallet.public_key

    # The escrow terms bind the accepted agreement; the hashes are independently checkable.
    proof = (
        await client.get(f"{API}/bookings/{deal.booking_id}/agreement", headers=deal.customer.headers)
    ).json()
    terms = json.loads(proof["escrow_terms_json"])
    assert (
        hashlib.sha256(proof["escrow_terms_json"].encode()).hexdigest()
        == proof["terms_hash"]
        == escrow["terms_hash"]
    )
    assert terms["agreement_hash"] == proof["agreement_hash"]
    assert terms["fx"]["is_demo_rate"] is True
    assert terms["asset_amount"] == str(AMOUNT_UNITS)

    submitted = await client.post(
        f"{API}/escrows/{escrow['id']}/funding",
        json={"signed_xdr": sign(prepared.json()["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    assert submitted.json()["reconciliation"] == "PENDING_CONFIRMATION"
    # Submitted is not funded: nothing changes until the chain confirms.
    assert (await booking(client, deal))["booking"]["status"] == "PENDING_PAYMENT"
    await reconciler.tick()
    assert (await booking(client, deal))["booking"]["status"] == "PENDING_PAYMENT"
    chain.close_ledger()
    await reconciler.tick()
    funded = await booking(client, deal)
    assert funded["booking"]["status"] == "FUNDED"
    assert funded["escrow"]["state"] == "FUNDED"
    assert funded["escrow"]["reconciliation"] == "CONFIRMED"
    assert funded["escrow"]["transactions"][0]["status"] == "CONFIRMED"
    assert chain.escrows[bytes.fromhex(escrow["escrow_id_hex"])].terms_hash == escrow["terms_hash"]
    assert chain.balances[deal.customer_wallet.public_key] == 10**12 - AMOUNT_UNITS
    pro_view = await booking(client, deal, deal.professional)
    assert pro_view["booking"]["address"] is not None  # revealed once funded
    assert {"START", "SUBMIT_COMPLETION", "REFUND"} <= set(pro_view["allowed_actions"])

    assert (
        await client.post(f"{API}/bookings/{deal.booking_id}/start", headers=deal.professional.headers)
    ).status_code == 200
    await _complete(client, chain, reconciler, deal)
    submitted_view = await booking(client, deal)
    assert submitted_view["booking"]["status"] == "COMPLETION_SUBMITTED"
    assert submitted_view["escrow"]["review_deadline"] is not None
    assert "APPROVE_RELEASE" in submitted_view["allowed_actions"]
    completion = (
        await client.get(f"{API}/bookings/{deal.booking_id}/completion", headers=deal.customer.headers)
    ).json()
    assert completion["status"] == "SUBMITTED"
    assert hashlib.sha256(completion["evidence_json"].encode()).hexdigest() == completion["evidence_hash"]
    assert chain.escrows[bytes.fromhex(escrow["escrow_id_hex"])].evidence_hash == completion["evidence_hash"]

    await chain_action(
        client, chain, reconciler, f"/escrows/{escrow['id']}/release", deal.customer, deal.customer_wallet
    )
    done = await booking(client, deal)
    assert done["booking"]["status"] == "COMPLETED"
    assert done["escrow"]["state"] == "RELEASED"
    assert (done["escrow"]["professional_payout"], done["escrow"]["settled_by"]) == (
        str(AMOUNT_UNITS),
        "CUSTOMER",
    )
    assert chain.balances[deal.professional_wallet.public_key] == AMOUNT_UNITS
    receipts = (
        await client.get(f"{API}/bookings/{deal.booking_id}/receipts", headers=deal.customer.headers)
    ).json()
    assert [r["kind"] for r in receipts] == ["FUNDING", "RELEASE"]
    for receipt in receipts:
        assert receipt["fx"]["is_demo_rate"] is True
        assert receipt["asset_amount"] == str(AMOUNT_UNITS)
        assert hashlib.sha256(receipt["payload_json"].encode()).hexdigest() == receipt["payload_hash"]
        assert receipt["number"].startswith("UFX-")
    profile = (await client.get(f"{API}/professionals/{deal.professional_id}")).json()
    assert profile["completed_jobs"] == 1
    assert await _count(seeded, LedgerEntry) == 2
    # Re-running the reconciler changes nothing (exactly once).
    await reconciler.tick()
    await reconciler.full_sweep()
    assert await _count(seeded, LedgerEntry) == 2
    assert await _count(seeded, Receipt) == 2
    assert (await client.get(f"{API}/professionals/{deal.professional_id}")).json()["completed_jobs"] == 1


# ---------------------------------------------------------------- preparation and submission


async def test_prepare_is_idempotent_and_expires(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    path = f"{API}/bookings/{deal.booking_id}/escrow"
    first = (await client.post(path, json={}, headers=deal.customer.headers)).json()
    again = (await client.post(path, json={}, headers=deal.customer.headers)).json()
    assert first["tx_hash"] == again["tx_hash"]
    clock.advance(301)
    customer = await relogin(client, deal.customer)
    late = await client.post(
        f"{API}/escrows/{first['escrow']['id']}/funding",
        json={"signed_xdr": sign(first["unsigned_xdr"], deal.customer_wallet)},
        headers=customer.headers,
    )
    assert (late.status_code, late.json()["code"]) == (409, "TX_EXPIRED")
    fresh = (await client.post(path, json={}, headers=customer.headers)).json()
    assert fresh["tx_hash"] != first["tx_hash"]
    assert fresh["escrow"]["id"] == first["escrow"]["id"]  # one escrow per booking
    statuses = [t["status"] for t in fresh["escrow"]["transactions"]]
    assert statuses == ["EXPIRED", "PENDING"]


async def test_tampered_or_foreign_signatures_are_rejected(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    from stellar_sdk import Keypair

    deal = await make_deal(client, chain, email_outbox)
    prepared = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    escrow_id = prepared["escrow"]["id"]
    # A transaction the backend never prepared (same call, different amount).
    gateway: Any = chain
    other = await gateway.prepare_call(
        source=deal.customer_wallet.public_key,
        function=Function.FUND,
        args=contract.fund_args(
            b"\x09" * 32,
            deal.customer_wallet.public_key,
            deal.professional_wallet.public_key,
            1,
            b"\x01" * 32,
            int(chain.now()) + 2 * 86_400,
        ),
        valid_until=int(chain.now()) + 300,
        operator=OPERATOR,
    )
    for signed in (
        sign(other.xdr, deal.customer_wallet),
        sign(prepared["unsigned_xdr"], Keypair.random()),
        prepared["unsigned_xdr"],
    ):
        response = await client.post(
            f"{API}/escrows/{escrow_id}/funding", json={"signed_xdr": signed}, headers=deal.customer.headers
        )
        assert (response.status_code, response.json()["code"]) == (400, "TX_MISMATCH")
    # The professional cannot submit the customer's funding.
    stolen = await client.post(
        f"{API}/escrows/{escrow_id}/funding",
        json={"signed_xdr": sign(prepared["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.professional.headers,
    )
    assert stolen.status_code == 409
    assert chain.pending == []
    assert (await booking(client, deal))["escrow"]["reconciliation"] == "AWAITING_SIGNATURE"


async def test_funding_preconditions(
    client: httpx.AsyncClient, seeded: Services, chain: FakeChain, email_outbox: RecordingEmailSender
) -> None:
    deal = await make_deal(client, chain, email_outbox, wallets=False)
    path = f"{API}/bookings/{deal.booking_id}/escrow"
    assert (await client.post(path, json={}, headers=deal.professional.headers)).json()[
        "code"
    ] == "ROLE_FORBIDDEN"
    assert (await client.post(path, json={}, headers=(await register(client)).headers)).status_code == 404
    assert (await client.post(path, json={}, headers=deal.customer.headers)).json()[
        "code"
    ] == "WALLET_REQUIRED"
    from tests.support import link_wallet

    keypair = await link_wallet(client, chain, deal.customer, balance=10**12)
    assert (await client.post(path, json={}, headers=deal.customer.headers)).json()["code"] == (
        "PROFESSIONAL_WALLET_MISSING"
    )
    pro_wallet = await link_wallet(client, chain, deal.professional)
    chain.accounts[pro_wallet.public_key].trustline = False
    assert (await client.post(path, json={}, headers=deal.customer.headers)).json()[
        "code"
    ] == "WALLET_NO_TRUSTLINE"
    chain.accounts[pro_wallet.public_key].trustline = True
    chain.offline = True
    down = await client.post(path, json={}, headers=deal.customer.headers)
    assert (down.status_code, down.json()["code"]) == (503, "CHAIN_UNAVAILABLE")
    chain.offline = False
    assert await _count(seeded, ChainTransaction) == 0  # nothing was stored on any failure
    # Somebody else's wallet cannot be named.
    foreign = await client.post(
        path, json={"customer_wallet": pro_wallet.public_key}, headers=deal.customer.headers
    )
    assert foreign.json()["code"] == "WALLET_REQUIRED"
    ok = await client.post(path, json={"customer_wallet": keypair.public_key}, headers=deal.customer.headers)
    assert ok.status_code == 200


async def test_unverified_email_cannot_fund(
    client: httpx.AsyncClient, seeded: Services, chain: FakeChain, email_outbox: RecordingEmailSender
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    async with seeded.session_factory() as session:
        await session.execute(
            text("UPDATE users SET email_verified_at = NULL WHERE id = :id"), {"id": deal.customer.id}
        )
        await session.commit()
    response = await client.post(
        f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers
    )
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"


# ---------------------------------------------------------------- failure modes (STELLAR_ESCROW_DESIGN §9)


async def test_try_again_later_then_accepted(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    chain.try_again_later = 2  # two refusals, then accepted within the 3 retries
    await fund(client, chain, reconciler, deal)


async def test_rpc_outage_after_submit_is_resent_by_the_reconciler(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    prepared = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    original_send = chain.send

    async def down(envelope: Any) -> Any:
        chain.offline = True
        try:
            return await original_send(envelope)
        finally:
            chain.offline = False

    chain.send = down  # type: ignore[method-assign]
    response = await client.post(
        f"{API}/escrows/{prepared['escrow']['id']}/funding",
        json={"signed_xdr": sign(prepared["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    assert response.status_code == 200
    assert response.json()["reconciliation"] == "PENDING_CONFIRMATION"
    async with seeded.session_factory() as session:
        assert (await session.execute(select(ChainTransaction.status))).scalar_one() == "SUBMITTED"
    chain.send = original_send  # type: ignore[method-assign]
    await reconciler.tick()  # NOT_FOUND within time bounds → resend from the stored signed envelope
    chain.close_ledger()
    await reconciler.tick()
    assert (await booking(client, deal))["booking"]["status"] == "FUNDED"


async def test_failed_and_never_landing_transactions(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    prepared = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    await client.post(
        f"{API}/escrows/{prepared['escrow']['id']}/funding",
        json={"signed_xdr": sign(prepared["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    chain.balances[deal.customer_wallet.public_key] = 0  # spent elsewhere before the ledger closed
    chain.close_ledger()
    await reconciler.tick()
    failed = await booking(client, deal)
    assert failed["booking"]["status"] == "PENDING_PAYMENT"
    assert failed["escrow"]["transactions"][0]["status"] == "FAILED"
    assert failed["escrow"]["reconciliation"] == "FAILED"
    assert "FUND" in failed["allowed_actions"]  # safe to prepare again
    assert await _count(seeded, LedgerEntry) == 0

    chain.balances[deal.customer_wallet.public_key] = 10**12
    retry = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    await client.post(
        f"{API}/escrows/{retry['escrow']['id']}/funding",
        json={"signed_xdr": sign(retry["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    chain.drop_pending()  # never included
    clock.advance(400)  # past the time bounds + margin
    await reconciler.tick()
    expired = (await booking(client, deal, await relogin(client, deal.customer)))["escrow"]
    assert [t["status"] for t in expired["transactions"]] == ["FAILED", "EXPIRED"]


async def test_cannot_cancel_or_expire_while_funding_is_in_flight(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    prepared = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    await client.post(
        f"{API}/escrows/{prepared['escrow']['id']}/funding",
        json={"signed_xdr": sign(prepared["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    cancel = await client.post(
        f"{API}/bookings/{deal.booking_id}/cancel",
        json={"reason": "never mind"},
        headers=deal.customer.headers,
    )
    assert cancel.json()["code"] == "FUNDING_IN_PROGRESS"
    clock.advance(8 * 86_400)  # past the 7-day payment window
    customer = await relogin(client, deal.customer)
    assert (await booking(client, deal, customer))["booking"]["status"] == "PENDING_PAYMENT"


# ---------------------------------------------------------------- exactly-once reconciliation


async def test_same_event_from_both_sources_and_concurrent_reconcilers_apply_once(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    stellar: StellarContext,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    prepared = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    await client.post(
        f"{API}/escrows/{prepared['escrow']['id']}/funding",
        json={"signed_xdr": sign(prepared["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    chain.close_ledger()
    first, second = Reconciler(seeded, stellar), Reconciler(seeded, stellar)
    # Both ingestion paths, then two leaders at once.
    await first.poll_transactions()  # TX_RESULT path
    await second.scan_events()  # EVENT_SCAN path: the same (tx_hash, event_index)
    assert await _count(seeded, ChainEvent) == 1
    applied = await asyncio.gather(first.apply_pending(), second.apply_pending(), first.tick(), second.tick())
    assert sum(applied[:2]) == 1
    assert await _count(seeded, LedgerEntry) == 1
    assert await _count(seeded, Receipt) == 1
    assert (await booking(client, deal))["booking"]["status"] == "FUNDED"
    async with seeded.session_factory() as session:
        source = (await session.execute(select(ChainEvent.source))).scalar_one()
        cursor = (await session.execute(text("SELECT cursor FROM chain_sync_state"))).scalar_one()
    assert source == "TX_RESULT"
    assert cursor == "1"  # the scan cursor covers the event it saw


async def test_crash_between_apply_steps_recovers(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.payments import reconciler as module

    deal = await make_deal(client, chain, email_outbox)
    prepared = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    await client.post(
        f"{API}/escrows/{prepared['escrow']['id']}/funding",
        json={"signed_xdr": sign(prepared["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    chain.close_ledger()

    async def crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("process killed mid-apply")

    monkeypatch.setattr(module, "_receipt", crash)  # after the ledger entry and state writes
    with pytest.raises(RuntimeError):
        await reconciler.tick()
    assert await _count(seeded, LedgerEntry) == 0  # rolled back as one unit
    assert await _count(seeded, ChainEvent, status="INGESTED") == 1
    assert (await booking(client, deal))["booking"]["status"] == "PENDING_PAYMENT"
    monkeypatch.undo()
    fresh = Reconciler(seeded, reconciler.stellar)  # "after restart": everything resumes from the DB
    await fresh.tick()
    assert (await booking(client, deal))["booking"]["status"] == "FUNDED"
    assert await _count(seeded, LedgerEntry) == 1


@pytest.mark.concurrency
async def test_parallel_funding_submissions_produce_one_effect(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    prepared = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    signed = sign(prepared["unsigned_xdr"], deal.customer_wallet)
    url = f"{API}/escrows/{prepared['escrow']['id']}/funding"
    responses = await asyncio.gather(
        *[client.post(url, json={"signed_xdr": signed}, headers=deal.customer.headers) for _ in range(5)]
    )
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len(chain.pending) == 1
    chain.close_ledger()
    await asyncio.gather(reconciler.tick(), reconciler.tick())
    assert await _count(seeded, LedgerEntry) == 1
    # A second funding of the same booking is impossible.
    again = await client.post(
        f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers
    )
    assert again.json()["code"] == "BOOKING_NOT_PAYABLE"


async def test_terms_tampered_on_chain_is_flagged_not_funded(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
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
    chain.escrows[key] = replace(chain.escrows[key], terms_hash="00" * 32, amount=1)
    await reconciler.tick()
    view = await booking(client, deal)
    assert view["booking"]["status"] == "PENDING_PAYMENT"
    assert view["escrow"]["reconciliation"] == "FAILED"
    assert view["escrow"]["failure_reason"].startswith("FAILED_VERIFICATION")
    assert await _count(seeded, ChainEvent, status="CONFLICT") == 1
    assert await _count(seeded, LedgerEntry) == 0


async def test_database_tampering_cannot_release_funds(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    async with seeded.session_factory() as session:  # an attacker with DB write access
        await session.execute(
            update(Escrow).where(Escrow.id == bundle["escrow"]["id"]).values(state="COMPLETION_SUBMITTED")
        )
        await session.execute(
            text("UPDATE bookings SET status = 'COMPLETION_SUBMITTED' WHERE id = :id"),
            {"id": deal.booking_id},
        )
        await session.commit()
    release = await client.post(
        f"{API}/escrows/{bundle['escrow']['id']}/release", json={}, headers=deal.customer.headers
    )
    # The chain refuses (still Funded on-chain, release is the customer's anyway); the professional
    # gets nothing without the customer's own wallet signature, and no receipt/ledger is written.
    assert release.status_code == 200  # preparation only: an unsigned transaction for the customer
    assert chain.balances.get(deal.professional_wallet.public_key, 0) == 0
    assert await _count(seeded, LedgerEntry) == 1
    assert await _count(seeded, Receipt) == 1


async def test_out_of_band_release_is_detected_from_events(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    key = bytes.fromhex(bundle["escrow"]["escrow_id_hex"])
    chain.invoke(Function.RELEASE, contract.escrow_only_args(key), signer=deal.customer_wallet.public_key)
    chain.close_ledger()
    await reconciler.tick()
    done = await booking(client, deal)
    assert done["booking"]["status"] == "COMPLETED"
    assert done["escrow"]["settled_by"] == "CUSTOMER"
    assert [
        r["kind"]
        for r in (
            await client.get(f"{API}/bookings/{deal.booking_id}/receipts", headers=deal.customer.headers)
        ).json()
    ] == ["FUNDING", "RELEASE"]


async def test_retention_gap_triggers_full_sweep(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    key = bytes.fromhex(bundle["escrow"]["escrow_id_hex"])
    chain.invoke(Function.REFUND, contract.escrow_only_args(key), signer=deal.professional_wallet.public_key)
    chain.close_ledger()
    chain.events.clear()  # the RPC no longer has those events…
    chain.oldest_ledger = chain.ledger + 1  # …and the cursor is older than its retention window
    await reconciler.tick()
    view = await booking(client, deal)
    assert view["booking"]["status"] == "REFUNDED"
    async with seeded.session_factory() as session:
        sources = (
            (await session.execute(select(ChainEvent.source).order_by(ChainEvent.ledger))).scalars().all()
        )
    assert sources[-1] == "STATE_SYNC"


async def test_leader_election_uses_one_advisory_lock(seeded: Services) -> None:
    async with seeded.engine.connect() as a, seeded.engine.connect() as b:
        got_a = (await a.execute(select(func.pg_try_advisory_lock(RECONCILER_LOCK_ID)))).scalar_one()
        got_b = (await b.execute(select(func.pg_try_advisory_lock(RECONCILER_LOCK_ID)))).scalar_one()
        assert (got_a, got_b) == (True, False)
        await a.execute(select(func.pg_advisory_unlock(RECONCILER_LOCK_ID)))
        assert (await b.execute(select(func.pg_try_advisory_lock(RECONCILER_LOCK_ID)))).scalar_one() is True
        await b.execute(select(func.pg_advisory_unlock(RECONCILER_LOCK_ID)))


# ---------------------------------------------------------------- refunds, cancellation, extension


async def test_cancellation_request_decline_and_refund(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    path = f"{API}/bookings/{deal.booking_id}/cancellation-requests"
    assert (
        await client.post(path, json={"reason": "Not needed"}, headers=deal.professional.headers)
    ).status_code == 403
    first = await client.post(path, json={"reason": "Not needed"}, headers=deal.customer.headers)
    assert first.status_code == 201
    assert (await client.post(path, json={"reason": "again"}, headers=deal.customer.headers)).json()[
        "code"
    ] == ("CANCELLATION_OPEN")
    pro_view = await booking(client, deal, deal.professional)
    assert "DECLINE_CANCELLATION" in pro_view["allowed_actions"]
    declined = await client.post(
        f"{API}/cancellation-requests/{first.json()['id']}/decline",
        json={"reason": "Parts ordered"},
        headers=deal.professional.headers,
    )
    assert declined.json()["status"] == "DECLINED"
    second = await client.post(path, json={"reason": "Please refund"}, headers=deal.customer.headers)
    assert second.status_code == 201
    await chain_action(
        client,
        chain,
        reconciler,
        f"/escrows/{bundle['escrow']['id']}/refund",
        deal.professional,
        deal.professional_wallet,
    )
    refunded = await booking(client, deal)
    assert refunded["booking"]["status"] == "REFUNDED"
    assert refunded["escrow"]["customer_refund"] == str(AMOUNT_UNITS)
    assert chain.balances[deal.customer_wallet.public_key] == 10**12
    async with seeded.session_factory() as session:
        status = (
            await session.execute(
                text("SELECT status FROM cancellation_requests WHERE id = :id"), {"id": second.json()["id"]}
            )
        ).scalar_one()
    assert status == "ACCEPTED"
    kinds = [
        r["kind"]
        for r in (
            await client.get(f"{API}/bookings/{deal.booking_id}/receipts", headers=deal.customer.headers)
        ).json()
    ]
    assert kinds == ["FUNDING", "REFUND"]


async def test_extend_deadline(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    escrow = bundle["escrow"]
    path = f"/escrows/{escrow['id']}/extend"
    too_late = await client.post(
        f"{API}{path}",
        json={"new_refund_after": escrow["refund_after"] + 200 * 86_400},
        headers=deal.customer.headers,
    )
    assert too_late.json()["code"] == "INVALID_DEADLINE"
    assert (
        await client.post(
            f"{API}{path}",
            json={"new_refund_after": escrow["refund_after"] + 1},
            headers=deal.professional.headers,
        )
    ).status_code == 403
    new = escrow["refund_after"] + 5 * 86_400
    await chain_action(
        client, chain, reconciler, path, deal.customer, deal.customer_wallet, {"new_refund_after": new}
    )
    assert (await booking(client, deal))["escrow"]["refund_after"] == new


async def test_action_guards(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    start = await client.post(f"{API}/bookings/{deal.booking_id}/start", headers=deal.professional.headers)
    assert start.status_code == 409  # not funded yet
    bundle = await fund(client, chain, reconciler, deal)
    escrow_id = bundle["escrow"]["id"]
    early = await client.post(f"{API}/escrows/{escrow_id}/release", json={}, headers=deal.customer.headers)
    assert early.json()["code"] == "RELEASE_NOT_ALLOWED"
    assert (
        await client.post(f"{API}/escrows/{escrow_id}/refund", json={}, headers=deal.customer.headers)
    ).status_code == 403
    completion = await client.post(
        f"{API}/bookings/{deal.booking_id}/completion", json={"notes": "done"}, headers=deal.customer.headers
    )
    assert completion.status_code == 403
    outsider = await register(client)
    assert (await client.get(f"{API}/escrows/{escrow_id}", headers=outsider.headers)).status_code == 404
    assert (
        await client.get(f"{API}/bookings/{deal.booking_id}/receipts", headers=outsider.headers)
    ).status_code == 404
    admin = await create_admin_account(client, seeded)
    assert (await client.get(f"{API}/escrows/{escrow_id}", headers=admin.headers)).status_code == 200
    # Wallets in a live escrow cannot be unlinked.
    wallet_id = (await client.get(f"{API}/wallets", headers=deal.customer.headers)).json()[0]["id"]
    removed = await client.delete(f"{API}/wallets/{wallet_id}", headers=deal.customer.headers)
    assert removed.json()["code"] == "WALLET_IN_ESCROW"


async def test_completion_evidence_photos_are_private(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    await fund(client, chain, reconciler, deal)
    photo = (await upload(client, deal.professional, "COMPLETION_EVIDENCE", image_bytes("JPEG"))).json()
    prepared = await client.post(
        f"{API}/bookings/{deal.booking_id}/completion",
        json={"notes": "Fixed", "photo_file_ids": [photo["id"]]},
        headers=deal.professional.headers,
    )
    assert prepared.status_code == 200, prepared.text
    evidence = json.loads(prepared.json()["submission"]["evidence_json"])
    assert evidence["photos"][0]["sha256"]  # the photo bytes are bound into the evidence hash
    assert (await client.get(photo["url"], headers=deal.customer.headers)).status_code == 200
    assert (await client.get(photo["url"], headers=(await register(client)).headers)).status_code == 404
    other_upload = (await upload(client, deal.professional, "PORTFOLIO")).json()  # wrong purpose
    stolen = await client.post(
        f"{API}/bookings/{deal.booking_id}/completion",
        json={"notes": "x", "photo_file_ids": [other_upload["id"]]},
        headers=deal.professional.headers,
    )
    assert stolen.json()["code"] == "INVALID_FILE"


# ---------------------------------------------------------------- keeper (D16b)


async def test_keeper_refunds_after_refund_after(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
    stellar: StellarContext,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    clock.advance(bundle["escrow"]["refund_after"] - int(clock.now().timestamp()) - 1)
    await reconciler.run_keeper()
    assert await _count(seeded, ChainTransaction, kind="FINALIZE") == 0  # not mature yet
    clock.advance(seeded.settings.keeper_delay_seconds + 2)
    other = Reconciler(seeded, stellar)
    await asyncio.gather(reconciler.run_keeper(), other.run_keeper())  # two keepers, one submission
    assert await _count(seeded, ChainTransaction, kind="FINALIZE") == 1
    chain.close_ledger()
    await reconciler.tick()
    view = await booking(client, deal, await relogin(client, deal.customer))
    assert view["booking"]["status"] == "REFUNDED"
    assert view["escrow"]["settled_by"] == "TIMEOUT"
    assert view["escrow"]["transactions"][-1]["kind"] == "FINALIZE"


async def test_keeper_auto_releases_after_review_deadline(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    await fund(client, chain, reconciler, deal)
    await _complete(client, chain, reconciler, deal)
    clock.advance(seeded.settings.escrow_review_window_seconds + seeded.settings.keeper_delay_seconds + 1)
    await reconciler.tick()  # keeper submits finalize_expired
    chain.close_ledger()
    await reconciler.tick()
    customer = await relogin(client, deal.customer)
    view = await booking(client, deal, customer)
    assert view["booking"]["status"] == "COMPLETED"
    assert view["escrow"]["settled_by"] == "TIMEOUT"
    assert (await client.get(f"{API}/professionals/{deal.professional_id}")).json()["completed_jobs"] == 1
    await reconciler.tick()
    assert await _count(seeded, ChainTransaction, kind="FINALIZE") == 1  # finalized exactly once
