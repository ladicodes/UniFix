"""Admin console APIs: filters, pagination, no sensitive fields, report resolution, ops status."""

from __future__ import annotations

import json
from dataclasses import replace

import httpx

from app.core.container import Services
from app.modules.payments.reconciler import Reconciler
from tests.chain import FakeChain
from tests.support import (
    API,
    RecordingEmailSender,
    create_admin_account,
    fund,
    make_deal,
    register,
    sign,
)

SENSITIVE = ("password", "token_hash", "secret", "xdr", "envelope", "refresh", "escrow_key")


def _assert_no_sensitive_fields(payload: object) -> None:
    text = json.dumps(payload).lower()
    for marker in SENSITIVE:
        assert f'"{marker}' not in text, marker
        assert f"_{marker}" not in text, marker


async def test_user_search_filters_and_detail(client: httpx.AsyncClient, seeded: Services) -> None:
    admin = await create_admin_account(client, seeded)
    ada = await register(client, name="Ada Lovelace", email="ada.lovelace@example.com")
    listed = await client.get(f"{API}/admin/users?q=lovelace", headers=admin.headers)
    assert listed.status_code == 200
    assert [u["email"] for u in listed.json()] == ["ada.lovelace@example.com"]
    assert listed.headers["X-Total-Count"] == "1"
    _assert_no_sensitive_fields(listed.json())
    # LIKE wildcards in the search term are literals, not patterns.
    assert (await client.get(f"{API}/admin/users?q=%25%25", headers=admin.headers)).json() == []
    admins = (await client.get(f"{API}/admin/users?role=ADMIN", headers=admin.headers)).json()
    assert {u["role"] for u in admins} == {"ADMIN"}
    assert (await client.get(f"{API}/admin/users?role=OWNER", headers=admin.headers)).status_code == 422

    detail = await client.get(f"{API}/admin/users/{ada.id}", headers=admin.headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["active_sessions"] == 1
    assert body["bookings_as_customer"] == 0
    assert body["wallets"] == []
    _assert_no_sensitive_fields(body)
    assert (await client.get(f"{API}/admin/users/{admin.id}x", headers=admin.headers)).status_code == 422


async def test_bookings_escrows_and_chain_transactions(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    admin = await create_admin_account(client, seeded)
    deal = await make_deal(client, chain, email_outbox)
    pending = (await client.get(f"{API}/admin/bookings?status=PENDING_PAYMENT", headers=admin.headers)).json()
    assert [b["id"] for b in pending] == [deal.booking_id]
    assert pending[0]["escrow_id"] is None
    await fund(client, chain, reconciler, deal)
    funded = (await client.get(f"{API}/admin/bookings?status=FUNDED", headers=admin.headers)).json()
    assert funded[0]["escrow_state"] == "FUNDED"
    by_customer = await client.get(
        f"{API}/admin/bookings?customer_id={deal.customer.id}", headers=admin.headers
    )
    assert by_customer.headers["X-Total-Count"] == "1"

    escrows = (await client.get(f"{API}/admin/escrows?state=FUNDED", headers=admin.headers)).json()
    assert len(escrows) == 1
    assert escrows[0]["asset_amount"].isdigit()
    assert escrows[0]["is_demo_rate"] is True
    _assert_no_sensitive_fields(escrows)
    txs = (
        await client.get(
            f"{API}/admin/chain-transactions?escrow_id={escrows[0]['id']}", headers=admin.headers
        )
    ).json()
    assert [(t["kind"], t["status"]) for t in txs] == [("FUND", "CONFIRMED")]
    assert txs[0]["explorer_url"].endswith(txs[0]["tx_hash"])
    _assert_no_sensitive_fields(txs)


async def test_failed_verification_is_listed_and_reported_in_ops_status(
    client: httpx.AsyncClient,
    seeded: Services,
    chain: FakeChain,
    reconciler: Reconciler,
    email_outbox: RecordingEmailSender,
) -> None:
    admin = await create_admin_account(client, seeded)
    healthy = (await client.get(f"{API}/admin/ops/status", headers=admin.headers)).json()
    assert healthy["rpc"]["configured"] is True
    assert healthy["failed_verification_count"] == 0
    deal = await make_deal(client, chain, email_outbox)
    prepared = (
        await client.post(f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers)
    ).json()
    status = (await client.get(f"{API}/admin/ops/status", headers=admin.headers)).json()
    assert status["awaiting_signature_count"] == 1
    await client.post(
        f"{API}/escrows/{prepared['escrow']['id']}/funding",
        json={"signed_xdr": sign(prepared["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    status = (await client.get(f"{API}/admin/ops/status", headers=admin.headers)).json()
    assert status["pending_tx_count"] == 1
    assert status["oldest_pending_age_seconds"] is not None
    chain.close_ledger()
    key = bytes.fromhex(prepared["escrow"]["escrow_id_hex"])
    chain.escrows[key] = replace(chain.escrows[key], terms_hash="00" * 32)
    await reconciler.tick()
    flagged = (
        await client.get(f"{API}/admin/escrows?failed_verification=true", headers=admin.headers)
    ).json()
    assert len(flagged) == 1
    assert flagged[0]["verification_error"].startswith("FAILED_VERIFICATION")
    status = (await client.get(f"{API}/admin/ops/status", headers=admin.headers)).json()
    assert status["failed_verification_count"] == 1
    assert status["conflict_event_count"] == 1
    assert status["pending_tx_count"] == 0
    assert set(status["reconciler"]) >= {"last_ledger", "cursor_lag_ledgers", "last_error"}


async def test_report_queue_and_resolution(client: httpx.AsyncClient, seeded: Services) -> None:
    admin = await create_admin_account(client, seeded)
    customer = await register(client)
    from tests.support import open_conversation, register_professional

    _, professional_id = await register_professional(client)
    conversation = await open_conversation(client, customer, professional_id)
    reported = await client.post(
        f"{API}/conversations/{conversation}/report", json={"reason": "SPAM"}, headers=customer.headers
    )
    assert reported.status_code == 201, reported.text
    queue = await client.get(f"{API}/admin/reports?status=OPEN", headers=admin.headers)
    assert [r["id"] for r in queue.json()] == [reported.json()["id"]]
    report_id = reported.json()["id"]
    resolved = await client.post(
        f"{API}/admin/reports/{report_id}/resolve",
        json={"decision": "DISMISSED", "note": "Not spam"},
        headers=admin.headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert (resolved.json()["status"], resolved.json()["resolved_by"]) == ("DISMISSED", str(admin.id))
    again = await client.post(
        f"{API}/admin/reports/{report_id}/resolve",
        json={"decision": "ACTIONED", "note": "x" * 5},
        headers=admin.headers,
    )
    assert (again.status_code, again.json()["code"]) == (409, "REPORT_NOT_OPEN")
    assert (await client.get(f"{API}/admin/reports?status=OPEN", headers=admin.headers)).json() == []

    logs = await client.get(f"{API}/admin/audit-logs?action=admin.report_resolved", headers=admin.headers)
    assert logs.status_code == 200
    entry = logs.json()[0]
    assert (entry["entity_id"], entry["actor_user_id"], entry["actor_type"]) == (
        report_id,
        str(admin.id),
        "ADMIN",
    )
    by_entity = await client.get(f"{API}/admin/audit-logs?entity_id={report_id}", headers=admin.headers)
    assert by_entity.headers["X-Total-Count"] == "1"
    _assert_no_sensitive_fields(
        (await client.get(f"{API}/admin/audit-logs?limit=100", headers=admin.headers)).json()
    )


async def test_service_requests_list(client: httpx.AsyncClient, seeded: Services) -> None:
    admin = await create_admin_account(client, seeded)
    listed = await client.get(f"{API}/admin/service-requests?status=OPEN&limit=5", headers=admin.headers)
    assert listed.status_code == 200
    assert listed.headers["X-Total-Count"] == "0"
    assert (
        await client.get(f"{API}/admin/service-requests?limit=101", headers=admin.headers)
    ).status_code == 422
