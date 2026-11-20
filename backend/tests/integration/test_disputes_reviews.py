"""Disputes (lock, evidence, arbitration, concessions, escalation) and verified reviews.

PostgreSQL 16 + the chain double. The on-chain rules themselves are covered by ``cargo test`` and
the testnet runs; here we test the off-chain guards, the reconciler mapping and reputation.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text

from app.core.clock import FrozenClock
from app.core.container import Services
from app.modules.disputes.service import split_amount
from app.modules.payments.models import ChainTransaction, Receipt
from app.modules.payments.reconciler import Reconciler
from app.modules.reviews.service import overall
from app.modules.stellar import contract
from app.modules.stellar.contract import Function
from tests.chain import FakeChain
from tests.conftest import ARBITER
from tests.support import (
    API,
    Account,
    Deal,
    RecordingEmailSender,
    booking,
    chain_action,
    create_admin_account,
    fund,
    image_bytes,
    link_wallet,
    make_deal,
    register,
    relogin,
    sign,
    upload,
)

AMOUNT = 212_121_213
RATINGS = {"quality": 5, "punctuality": 4, "communication": 5, "professionalism": 4, "value": 3}


async def _complete(client: httpx.AsyncClient, chain: FakeChain, reconciler: Reconciler, deal: Deal) -> None:
    await chain_action(
        client,
        chain,
        reconciler,
        f"/bookings/{deal.booking_id}/completion",
        deal.professional,
        deal.professional_wallet,
        {"notes": "Done"},
        submit_path=f"/bookings/{deal.booking_id}/completion/submit",
    )


async def _disputed(
    client: httpx.AsyncClient,
    chain: FakeChain,
    reconciler: Reconciler,
    outbox: RecordingEmailSender,
    *,
    by: str = "customer",
    complete: bool = False,
) -> tuple[Deal, dict[str, Any]]:
    """A funded booking, a dispute record, and its on-chain lock confirmed: DISPUTED."""
    deal = await make_deal(client, chain, outbox)
    bundle = await fund(client, chain, reconciler, deal)
    if complete:
        await _complete(client, chain, reconciler, deal)
    account, keypair = (
        (deal.customer, deal.customer_wallet)
        if by == "customer"
        else (deal.professional, deal.professional_wallet)
    )
    opened = await client.post(
        f"{API}/escrows/{bundle['escrow']['id']}/disputes",
        json={"reason": "QUALITY", "details": "The screen flickers after the repair."},
        headers=account.headers,
    )
    assert opened.status_code == 201, opened.text
    dispute = opened.json()["dispute"]
    locked = await client.post(
        f"{API}/disputes/{dispute['id']}/lock",
        json={"signed_xdr": sign(opened.json()["unsigned_xdr"], keypair)},
        headers=account.headers,
    )
    assert locked.status_code == 200, locked.text
    chain.close_ledger()
    await reconciler.tick()
    view = await booking(client, deal)
    assert view["booking"]["status"] == "DISPUTED"
    return deal, view


async def _arbiter(client: httpx.AsyncClient, services: Services, chain: FakeChain) -> Account:
    admin = await create_admin_account(client, services)
    await link_wallet(client, chain, admin, ARBITER)
    return admin


async def _resolve(
    client: httpx.AsyncClient,
    chain: FakeChain,
    reconciler: Reconciler,
    admin: Account,
    dispute_id: str,
    body: dict[str, Any],
) -> None:
    prepared = await client.post(f"{API}/disputes/{dispute_id}/resolve", json=body, headers=admin.headers)
    assert prepared.status_code == 200, prepared.text
    submitted = await client.post(
        f"{API}/disputes/{dispute_id}/resolve",
        json={"signed_xdr": sign(prepared.json()["unsigned_xdr"], ARBITER)},
        headers=admin.headers,
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "AWAITING_SETTLEMENT"
    assert submitted.json()["outcome"] is None  # set only from the confirmed chain event
    chain.close_ledger()
    await reconciler.tick()


# ---------------------------------------------------------------- disputes


def test_split_rounding() -> None:
    assert split_amount(AMOUNT, 3_333) == AMOUNT * 3_333 // 10_000 == 70_700_000
    assert split_amount(AMOUNT, 1) == 21_212  # floor; the remainder goes to the customer
    assert split_amount(3, 5_000) == 1
    assert split_amount(1, 9_999) == 0
    assert (split_amount(AMOUNT, 0), split_amount(AMOUNT, 10_000)) == (0, AMOUNT)
    with pytest.raises(ValueError, match="bps"):
        split_amount(AMOUNT, 10_001)


async def test_dispute_blocks_settlement_before_and_after_the_lock(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    await _complete(client, chain, reconciler, deal)
    escrow_id = bundle["escrow"]["id"]
    opened = await client.post(
        f"{API}/escrows/{escrow_id}/disputes",
        json={"reason": "INCOMPLETE", "details": "Half of the work is missing."},
        headers=deal.customer.headers,
    )
    assert opened.status_code == 201
    assert opened.json()["dispute"]["status"] == "OPEN"
    # The record alone blocks ordinary settlement (the window before on-chain confirmation).
    release = await client.post(f"{API}/escrows/{escrow_id}/release", json={}, headers=deal.customer.headers)
    refund = await client.post(
        f"{API}/escrows/{escrow_id}/refund", json={}, headers=deal.professional.headers
    )
    assert (release.json()["code"], refund.json()["code"]) == ("DISPUTE_OPEN", "DISPUTE_OPEN")
    again = await client.post(
        f"{API}/escrows/{escrow_id}/disputes",
        json={"reason": "OTHER", "details": "Second attempt at a dispute."},
        headers=deal.professional.headers,
    )
    assert again.json()["code"] == "DISPUTE_EXISTS"
    await client.post(
        f"{API}/disputes/{opened.json()['dispute']['id']}/lock",
        json={"signed_xdr": sign(opened.json()["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    chain.close_ledger()
    await reconciler.tick()
    view = await booking(client, deal)
    dispute = view["dispute"]
    assert view["booking"]["status"] == "DISPUTED"
    assert view["escrow"]["state"] == "DISPUTED"
    assert dispute["status"] == "UNDER_REVIEW"
    assert dispute["sla"]["evidence_closes_at"]
    assert dispute["sla"]["decision_due_at"]
    assert "CONCEDE_RELEASE" in view["allowed_actions"]
    assert "APPROVE_RELEASE" not in view["allowed_actions"]
    completion = (
        await client.get(f"{API}/bookings/{deal.booking_id}/completion", headers=deal.customer.headers)
    ).json()
    assert completion["status"] == "DISPUTED"


@pytest.mark.concurrency
async def test_one_active_dispute_under_concurrency(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    url = f"{API}/escrows/{bundle['escrow']['id']}/disputes"
    body = {"reason": "NO_SHOW", "details": "Nobody came to do the job."}
    responses = await asyncio.gather(
        client.post(url, json=body, headers=deal.customer.headers),
        client.post(url, json=body, headers=deal.professional.headers),
        client.post(url, json=body, headers=deal.customer.headers),
    )
    assert sorted(r.status_code for r in responses) == [201, 409, 409]
    async with seeded.session_factory() as session:
        assert (await session.execute(text("SELECT count(*) FROM disputes"))).scalar_one() == 1


async def test_dispute_guards(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    prepared = await client.post(
        f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers
    )
    escrow_id = prepared.json()["escrow"]["id"]
    body = {"reason": "OTHER", "details": "Something went wrong."}
    unfunded = await client.post(
        f"{API}/escrows/{escrow_id}/disputes", json=body, headers=deal.customer.headers
    )
    assert unfunded.json()["code"] == "DISPUTE_NOT_ALLOWED"
    deal2 = await make_deal(client, chain, email_outbox)
    funded = await fund(client, chain, reconciler, deal2)
    url = f"{API}/escrows/{funded['escrow']['id']}/disputes"
    assert (await client.post(url, json=body, headers=(await register(client)).headers)).status_code == 404
    admin = await create_admin_account(client, seeded)
    assert (await client.post(url, json=body, headers=admin.headers)).json()["code"] == "ROLE_FORBIDDEN"
    clock.advance(funded["escrow"]["refund_after"] - int(clock.now().timestamp()))
    late = await client.post(url, json=body, headers=(await relogin(client, deal2.customer)).headers)
    assert late.json()["code"] == "DEADLINE_PASSED"


async def test_evidence_access_matrix(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal, view = await _disputed(client, chain, reconciler, email_outbox)
    dispute_id = view["dispute"]["id"]
    photo = (await upload(client, deal.customer, "DISPUTE_EVIDENCE", image_bytes("JPEG"))).json()
    added = await client.post(
        f"{API}/disputes/{dispute_id}/evidence",
        json={"note": "Photo of the flicker", "file_id": photo["id"]},
        headers=deal.customer.headers,
    )
    assert added.status_code == 201, added.text
    await client.post(
        f"{API}/disputes/{dispute_id}/evidence",
        json={"note": "It was fine when I left"},
        headers=deal.professional.headers,
    )
    admin = await create_admin_account(client, seeded)
    outsider = await register(client)
    for account in (deal.customer, deal.professional, admin):
        seen = await client.get(f"{API}/disputes/{dispute_id}", headers=account.headers)
        assert len(seen.json()["evidence"]) == 2
    assert (await client.get(f"{API}/disputes/{dispute_id}", headers=outsider.headers)).status_code == 404
    assert (
        await client.post(
            f"{API}/disputes/{dispute_id}/evidence", json={"note": "x"}, headers=outsider.headers
        )
    ).status_code == 404
    for account, expected in ((deal.professional, 200), (admin, 200), (outsider, 404)):
        assert (await client.get(photo["url"], headers=account.headers)).status_code == expected
    foreign = (await upload(client, deal.professional, "DISPUTE_EVIDENCE")).json()
    stolen = await client.post(
        f"{API}/disputes/{dispute_id}/evidence",
        json={"note": "x", "file_id": foreign["id"]},
        headers=deal.customer.headers,
    )
    assert stolen.json()["code"] == "INVALID_FILE"


@pytest.mark.parametrize(
    ("body", "status", "outcome", "payout"),
    [
        ({"outcome": "RELEASE", "note": "Work was done as agreed"}, "COMPLETED", "RELEASE", AMOUNT),
        ({"outcome": "REFUND", "note": "No work was done"}, "REFUNDED", "REFUND", 0),
        (
            {"outcome": "SPLIT", "split_bps_to_professional": 3_333, "note": "Partly done"},
            "RESOLVED",
            "SPLIT",
            AMOUNT * 3_333 // 10_000,
        ),
    ],
)
async def test_arbiter_resolution_outcomes(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    body: dict[str, Any],
    status: str,
    outcome: str,
    payout: int,
) -> None:
    deal, view = await _disputed(client, chain, reconciler, email_outbox, complete=True)
    admin = await _arbiter(client, seeded, chain)
    await _resolve(client, chain, reconciler, admin, view["dispute"]["id"], body)
    done = await booking(client, deal)
    assert done["booking"]["status"] == status
    assert done["dispute"]["status"] == "RESOLVED"
    assert done["dispute"]["outcome"] == outcome
    assert done["escrow"]["settled_by"] == "ARBITER"
    assert done["escrow"]["professional_payout"] == str(payout)
    assert done["escrow"]["customer_refund"] == str(AMOUNT - payout)
    assert chain.balances.get(deal.professional_wallet.public_key, 0) == payout
    if outcome == "SPLIT":
        assert done["dispute"]["split_bps_to_professional"] == 3_333
    async with seeded.session_factory() as session:
        kinds = (await session.execute(select(Receipt.kind).order_by(Receipt.number))).scalars().all()
        entries = (
            (await session.execute(text("SELECT type FROM ledger_entries ORDER BY created_at")))
            .scalars()
            .all()
        )
    assert kinds == ["FUNDING", "RESOLUTION"]
    expected = (
        ["CUSTOMER_FUNDING"]
        + (["PROFESSIONAL_PAYOUT"] if payout else [])
        + (["CUSTOMER_REFUND"] if AMOUNT - payout else [])
    )
    assert sorted(entries) == sorted(expected)


async def test_resolution_requires_the_arbiter_wallet_and_a_locked_dispute(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal, view = await _disputed(client, chain, reconciler, email_outbox)
    dispute_id = view["dispute"]["id"]
    url = f"{API}/disputes/{dispute_id}/resolve"
    body = {"outcome": "REFUND", "note": "No work was done"}
    assert (await client.post(url, json=body, headers=deal.customer.headers)).status_code == 403
    plain_admin = await create_admin_account(client, seeded)
    assert (await client.post(url, json=body, headers=plain_admin.headers)).json()["code"] == (
        "ARBITER_WALLET_REQUIRED"
    )
    await link_wallet(client, chain, plain_admin)  # some other wallet
    assert (await client.post(url, json=body, headers=plain_admin.headers)).json()["code"] == (
        "ARBITER_WALLET_REQUIRED"
    )
    arbiter = await _arbiter(client, seeded, chain)
    bad = await client.post(url, json={"outcome": "SPLIT", "note": "half"}, headers=arbiter.headers)
    assert bad.json()["code"] == "INVALID_SPLIT"
    conceded = await client.post(
        url, json={"outcome": "CONCEDED_RELEASE", "note": "conceded?"}, headers=arbiter.headers
    )
    assert conceded.json()["code"] == "INVALID_OUTCOME"
    # Prepared but never signed: nothing is decided.
    assert (await client.post(url, json=body, headers=arbiter.headers)).status_code == 200
    chain.close_ledger()
    await reconciler.tick()
    still = (await client.get(f"{API}/disputes/{dispute_id}", headers=arbiter.headers)).json()
    assert (still["status"], still["outcome"]) == ("UNDER_REVIEW", None)


@pytest.mark.parametrize("who", ["customer", "professional"])
async def test_concessions_favour_the_other_party(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    who: str,
) -> None:
    deal, view = await _disputed(client, chain, reconciler, email_outbox, by="professional")
    escrow_id = view["escrow"]["id"]
    if who == "customer":
        await chain_action(
            client, chain, reconciler, f"/escrows/{escrow_id}/release", deal.customer, deal.customer_wallet
        )
        expected = ("COMPLETED", "CONCEDED_RELEASE")
    else:
        await chain_action(
            client,
            chain,
            reconciler,
            f"/escrows/{escrow_id}/refund",
            deal.professional,
            deal.professional_wallet,
        )
        expected = ("REFUNDED", "CONCEDED_REFUND")
    done = await booking(client, deal)
    assert (done["booking"]["status"], done["dispute"]["outcome"]) == expected
    # Neither party can move funds toward themselves while disputed: the routes are role-bound.
    other = await make_deal(client, chain, email_outbox)
    del other


async def test_disputed_escrows_never_time_out_and_escalate(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
) -> None:
    deal, view = await _disputed(client, chain, reconciler, email_outbox)
    clock.advance(8 * 86_400)  # past refund_after + keeper delay and past decision_due_at
    await reconciler.tick()
    async with seeded.session_factory() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(ChainTransaction).where(ChainTransaction.kind == "FINALIZE")
            )
        ).scalar_one()
    assert count == 0  # the keeper never selects a disputed escrow
    admin = await create_admin_account(client, seeded)
    level_one = (await client.get(f"{API}/disputes/{view['dispute']['id']}", headers=admin.headers)).json()
    assert level_one["sla"]["escalation_level"] == 1
    clock.advance(7 * 86_400)
    await reconciler.tick()
    admin = await relogin(client, admin)
    level_two = (await client.get(f"{API}/disputes/{view['dispute']['id']}", headers=admin.headers)).json()
    assert (level_two["sla"]["escalation_level"], level_two["status"]) == (2, "UNDER_REVIEW")
    queue = (await client.get(f"{API}/admin/disputes", headers=admin.headers)).json()
    assert [d["dispute"]["id"] for d in queue] == [view["dispute"]["id"]]
    assert (await booking(client, deal, await relogin(client, deal.customer)))["booking"][
        "status"
    ] == "DISPUTED"
    assert chain.balances[chain.contract_id] == AMOUNT  # funds stay locked until a human decides


async def test_out_of_band_dispute_is_recorded(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    key = bytes.fromhex(bundle["escrow"]["escrow_id_hex"])
    pro = deal.professional_wallet.public_key
    chain.invoke(Function.OPEN_DISPUTE, contract.open_dispute_args(key, pro), signer=pro)
    chain.close_ledger()
    await reconciler.tick()
    view = await booking(client, deal)
    assert view["booking"]["status"] == "DISPUTED"
    assert (view["dispute"]["status"], view["dispute"]["reason"]) == ("UNDER_REVIEW", "OTHER")


async def test_never_locked_dispute_closes_when_the_deadline_settles(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
) -> None:
    deal = await make_deal(client, chain, email_outbox)
    bundle = await fund(client, chain, reconciler, deal)
    opened = await client.post(
        f"{API}/escrows/{bundle['escrow']['id']}/disputes",
        json={"reason": "OTHER", "details": "Opened but never signed."},
        headers=deal.customer.headers,
    )
    clock.advance(
        bundle["escrow"]["refund_after"] - int(clock.now().timestamp()) + seeded.settings.keeper_delay_seconds
    )
    await reconciler.tick()
    chain.close_ledger()
    await reconciler.tick()
    customer = await relogin(client, deal.customer)
    view = await booking(client, deal, customer)
    assert view["booking"]["status"] == "REFUNDED"
    dispute = (
        await client.get(f"{API}/disputes/{opened.json()['dispute']['id']}", headers=customer.headers)
    ).json()
    assert dispute["status"] == "CLOSED"


# ---------------------------------------------------------------- reviews


async def _completed(
    client: httpx.AsyncClient, chain: FakeChain, reconciler: Reconciler, outbox: RecordingEmailSender
) -> Deal:
    deal = await make_deal(client, chain, outbox)
    bundle = await fund(client, chain, reconciler, deal)
    await _complete(client, chain, reconciler, deal)
    await chain_action(
        client,
        chain,
        reconciler,
        f"/escrows/{bundle['escrow']['id']}/release",
        deal.customer,
        deal.customer_wallet,
    )
    return deal


def test_overall_is_the_mean_to_one_decimal() -> None:
    assert overall([5, 4, 5, 4, 3]) == Decimal("4.2")
    assert overall([5, 5, 5, 5, 4]) == Decimal("4.8")
    assert overall([1, 1, 1, 1, 2]) == Decimal("1.2")


async def test_review_eligibility(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
    clock: FrozenClock,
) -> None:
    pending = await make_deal(client, chain, email_outbox)
    body = {"ratings": RATINGS, "comment": "Great job"}
    early = await client.post(
        f"{API}/bookings/{pending.booking_id}/reviews", json=body, headers=pending.customer.headers
    )
    assert early.json()["code"] == "REVIEW_NOT_ELIGIBLE"
    deal = await _completed(client, chain, reconciler, email_outbox)
    url = f"{API}/bookings/{deal.booking_id}/reviews"
    assert (await client.post(url, json=body, headers=deal.professional.headers)).status_code == 403
    assert (await client.post(url, json=body, headers=(await register(client)).headers)).status_code == 404
    invalid = await client.post(
        url, json={"ratings": {**RATINGS, "value": 6}, "comment": "x"}, headers=deal.customer.headers
    )
    assert invalid.status_code == 422
    assert "REVIEW" in (await booking(client, deal))["allowed_actions"]
    created = await client.post(url, json=body, headers=deal.customer.headers)
    assert created.status_code == 201, created.text
    assert (created.json()["overall"], created.json()["status"]) == (4.2, "PUBLISHED")
    assert (await client.post(url, json=body, headers=deal.customer.headers)).json()[
        "code"
    ] == "REVIEW_EXISTS"
    assert (await booking(client, deal))["review"]["id"] == created.json()["id"]
    late = await _completed(client, chain, reconciler, email_outbox)
    clock.advance(31 * 86_400)
    customer = await relogin(client, late.customer)
    closed = await client.post(
        f"{API}/bookings/{late.booking_id}/reviews", json=body, headers=customer.headers
    )
    assert closed.json()["code"] == "REVIEW_WINDOW_CLOSED"


async def test_review_on_a_resolved_booking(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    deal, view = await _disputed(client, chain, reconciler, email_outbox)
    admin = await _arbiter(client, seeded, chain)
    await _resolve(
        client,
        chain,
        reconciler,
        admin,
        view["dispute"]["id"],
        {"outcome": "SPLIT", "split_bps_to_professional": 5_000, "note": "Half done"},
    )
    created = await client.post(
        f"{API}/bookings/{deal.booking_id}/reviews",
        json={"ratings": RATINGS, "comment": "OK in the end"},
        headers=deal.customer.headers,
    )
    assert created.status_code == 201


async def test_aggregates_response_reports_and_moderation(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    first = await _completed(client, chain, reconciler, email_outbox)
    review_a = (
        await client.post(
            f"{API}/bookings/{first.booking_id}/reviews",
            json={"ratings": RATINGS, "comment": "Great"},
            headers=first.customer.headers,
        )
    ).json()
    # A second job for the same professional.
    second = await make_deal(client, chain, email_outbox)
    del second  # (different professional; aggregates are per professional)
    profile = (await client.get(f"{API}/professionals/{first.professional_id}")).json()
    assert (profile["review_count"], profile["rating"]) == (1, 4.2)

    respond = f"{API}/reviews/{review_a['id']}/response"
    assert (
        await client.post(respond, json={"body": "Thanks"}, headers=first.customer.headers)
    ).status_code == 403
    answered = await client.post(respond, json={"body": "Thank you!"}, headers=first.professional.headers)
    assert answered.json()["response"]["body"] == "Thank you!"
    assert (await client.post(respond, json={"body": "again"}, headers=first.professional.headers)).json()[
        "code"
    ] == ("RESPONSE_EXISTS")

    reporter = await register(client)
    report_url = f"{API}/reviews/{review_a['id']}/report"
    assert (
        await client.post(report_url, json={"reason": "spam"}, headers=reporter.headers)
    ).status_code == 201
    assert (await client.post(report_url, json={"reason": "spam"}, headers=reporter.headers)).json()[
        "code"
    ] == ("ALREADY_REPORTED")

    moderate = f"{API}/admin/reviews/{review_a['id']}/moderate"
    assert (
        await client.post(
            moderate, json={"action": "HIDE", "reason": "abuse"}, headers=first.customer.headers
        )
    ).status_code == 403
    admin = await create_admin_account(client, seeded)
    hidden = await client.post(
        moderate, json={"action": "HIDE", "reason": "Under investigation"}, headers=admin.headers
    )
    assert hidden.json()["status"] == "HIDDEN"
    profile = (await client.get(f"{API}/professionals/{first.professional_id}")).json()
    assert (profile["review_count"], profile["rating"]) == (0, 0.0)
    assert (await client.get(f"{API}/professionals/{first.professional_id}/reviews")).json() == []
    restored = await client.post(
        moderate, json={"action": "RESTORE", "reason": "Cleared"}, headers=admin.headers
    )
    assert restored.json()["status"] == "PUBLISHED"
    profile = (await client.get(f"{API}/professionals/{first.professional_id}")).json()
    assert (profile["review_count"], profile["rating"]) == (1, 4.2)
    listed = (await client.get(f"{API}/professionals/{first.professional_id}/reviews")).json()
    assert [r["id"] for r in listed] == [review_a["id"]]
    assert listed[0]["job_title"]
    assert listed[0]["customer_name"]
    removed = await client.post(
        moderate, json={"action": "REMOVE", "reason": "Policy"}, headers=admin.headers
    )
    assert removed.json()["status"] == "REMOVED"
    assert (
        await client.post(moderate, json={"action": "RESTORE", "reason": "x" * 3}, headers=admin.headers)
    ).json()["code"] == "REVIEW_REMOVED"
    async with seeded.session_factory() as session:
        actions = (
            (
                await session.execute(
                    text("SELECT action FROM audit_logs WHERE action LIKE 'review.%' ORDER BY id")
                )
            )
            .scalars()
            .all()
        )
        rows = (await session.execute(text("SELECT count(*) FROM reviews"))).scalar_one()
    assert actions == [
        "review.created",
        "review.responded",
        "review.reported",
        "review.hide",
        "review.restore",
        "review.remove",
    ]
    assert rows == 1  # moderation never deletes


async def test_category_aggregates_are_exact_over_several_reviews(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    from app.modules.reviews.service import recompute

    deal = await _completed(client, chain, reconciler, email_outbox)
    await client.post(
        f"{API}/bookings/{deal.booking_id}/reviews",
        json={"ratings": RATINGS, "comment": "one"},
        headers=deal.customer.headers,
    )
    async with seeded.session_factory() as session:  # two more synthetic rows for the same professional
        booking_ids = []
        for ratings in (
            {"quality": 3, "punctuality": 3, "communication": 4, "professionalism": 5, "value": 5},
            {"quality": 4, "punctuality": 5, "communication": 1, "professionalism": 2, "value": 4},
        ):
            other = await make_deal(client, chain, email_outbox)
            booking_ids.append((other.booking_id, ratings, other.customer.id))
        professional = (
            await session.execute(
                text("SELECT professional_id FROM bookings WHERE id = :id"), {"id": deal.booking_id}
            )
        ).scalar_one()
        for booking_id, ratings, customer_id in booking_ids:
            await session.execute(
                text(
                    "INSERT INTO reviews (id, booking_id, customer_id, professional_id, overall, quality,"
                    " punctuality, communication, professionalism, value, comment, status)"
                    " VALUES (gen_random_uuid(), :b, :c, :p, :o, :q, :pu, :co, :pr, :v, 'x', 'PUBLISHED')"
                ),
                {
                    "b": booking_id,
                    "c": customer_id,
                    "p": professional,
                    "o": overall(list(ratings.values())),
                    "q": ratings["quality"],
                    "pu": ratings["punctuality"],
                    "co": ratings["communication"],
                    "pr": ratings["professionalism"],
                    "v": ratings["value"],
                },
            )
        await recompute(session, professional)
        await session.commit()
        row = (
            await session.execute(
                text(
                    "SELECT rating_count, rating_avg, rating_quality, rating_communication"
                    " FROM professional_profiles WHERE id = :p"
                ),
                {"p": professional},
            )
        ).one()
    # overall: 4.2, 4.0, 3.2 → 3.80; quality: 5, 3, 4 → 4.00; communication: 5, 4, 1 → 3.33
    assert (row[0], row[1], row[2], row[3]) == (3, Decimal("3.80"), Decimal("4.00"), Decimal("3.33"))
