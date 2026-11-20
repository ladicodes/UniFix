"""Cross-cutting admin console: read-only lists, report resolution and operational status."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.errors import Conflict, NotFound
from app.modules.admin import repository
from app.modules.admin.schemas import (
    AdminAuditLogOut,
    AdminBookingOut,
    AdminChainTxOut,
    AdminEscrowOut,
    AdminReportOut,
    AdminServiceRequestOut,
    AdminUserDetailOut,
    AdminUserOut,
    AdminWalletOut,
    OpsStatusOut,
    ReconcilerStatus,
    ResolveReportIn,
    RpcStatus,
)
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType, AuditLog
from app.modules.auth.context import AuthContext
from app.modules.chat.models import ReportStatus
from app.modules.payments.models import ChainTransaction, Escrow
from app.modules.stellar.context import StellarContext
from app.modules.users.models import User


def user_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        email=user.email,
        name=user.full_name,
        role=user.role,
        status=user.status,
        country=user.country,
        city=user.city,
        campus_id=user.campus_id,
        email_verified=user.email_verified_at is not None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def users(
    session: AsyncSession, *, q: str | None, role: str | None, status: str | None, limit: int, offset: int
) -> tuple[list[AdminUserOut], int]:
    rows, total = await repository.users(session, q=q, role=role, status=status, limit=limit, offset=offset)
    return [user_out(row) for row in rows], total


async def user_detail(session: AsyncSession, services: Services, user_id: uuid.UUID) -> AdminUserDetailOut:
    user = await repository.user(session, user_id)
    if user is None:
        raise NotFound("User not found.")
    profile = await repository.profile_for(session, user.id)
    counts = await repository.user_counts(
        session, user.id, profile.id if profile else None, services.clock.now()
    )
    return AdminUserDetailOut(
        **user_out(user).model_dump(),
        professional_id=profile.id if profile else None,
        verification_status=profile.verification_status if profile else None,
        wallets=[AdminWalletOut.model_validate(w) for w in await repository.wallets_for(session, user.id)],
        **counts,
    )


async def bookings(
    session: AsyncSession,
    *,
    status: str | None,
    customer_id: uuid.UUID | None,
    professional_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[AdminBookingOut], int]:
    rows, total = await repository.bookings(
        session,
        status=status,
        customer_id=customer_id,
        professional_id=professional_id,
        limit=limit,
        offset=offset,
    )
    return [
        AdminBookingOut(
            id=b.id,
            title=b.title,
            status=b.status,
            amount_minor=b.amount_minor,
            currency=b.currency,
            customer_id=b.customer_id,
            professional_id=b.professional_id,
            conversation_id=b.conversation_id,
            service_request_id=b.service_request_id,
            escrow_id=e.id if e else None,
            escrow_state=e.state if e else None,
            created_at=b.created_at,
            updated_at=b.updated_at,
        )
        for b, e in rows
    ], total


def escrow_out(escrow: Escrow) -> AdminEscrowOut:
    return AdminEscrowOut(
        id=escrow.id,
        booking_id=escrow.booking_id,
        network=escrow.network,
        contract_id=escrow.contract_id,
        state=escrow.state,
        reconciliation=escrow.reconciliation,
        asset_code=escrow.asset_code,
        asset_amount=str(int(escrow.asset_units)),
        fiat_amount_minor=escrow.fiat_amount_minor,
        fiat_currency=escrow.fiat_currency,
        is_demo_rate=escrow.is_demo_rate,
        customer_wallet=escrow.customer_wallet,
        professional_wallet=escrow.professional_wallet,
        refund_after=escrow.refund_after,
        review_deadline=escrow.review_deadline,
        settled_by=escrow.settled_by,
        verification_error=escrow.verification_error,
        failure_reason=escrow.failure_reason,
        last_synced_ledger=escrow.last_synced_ledger,
        created_at=escrow.created_at,
        updated_at=escrow.updated_at,
    )


async def escrows(
    session: AsyncSession,
    *,
    state: str | None,
    reconciliation: str | None,
    failed_verification: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[AdminEscrowOut], int]:
    rows, total = await repository.escrows(
        session,
        state=state,
        reconciliation=reconciliation,
        failed_verification=failed_verification,
        limit=limit,
        offset=offset,
    )
    return [escrow_out(row) for row in rows], total


def chain_tx_out(stellar: StellarContext, tx: ChainTransaction) -> AdminChainTxOut:
    """No envelope XDR: admins get the hash and the explorer link instead."""
    return AdminChainTxOut(
        id=tx.id,
        escrow_id=tx.escrow_id,
        kind=tx.kind,
        status=tx.status,
        tx_hash=tx.tx_hash,
        source_account=tx.source_account,
        ledger=tx.ledger,
        result_code=tx.result_code,
        error=tx.error,
        attempts=tx.attempts,
        requested_by=tx.requested_by,
        created_at=tx.created_at,
        submitted_at=tx.submitted_at,
        confirmed_at=tx.confirmed_at,
        explorer_url=stellar.explorer_tx_url(tx.tx_hash),
    )


async def chain_transactions(
    session: AsyncSession,
    stellar: StellarContext,
    *,
    escrow_id: uuid.UUID | None,
    status: str | None,
    kind: str | None,
    limit: int,
    offset: int,
) -> tuple[list[AdminChainTxOut], int]:
    rows, total = await repository.chain_transactions(
        session, escrow_id=escrow_id, status=status, kind=kind, limit=limit, offset=offset
    )
    return [chain_tx_out(stellar, row) for row in rows], total


async def service_requests(
    session: AsyncSession,
    *,
    status: str | None,
    category_id: uuid.UUID | None,
    customer_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[AdminServiceRequestOut], int]:
    rows, total = await repository.service_requests(
        session, status=status, category_id=category_id, customer_id=customer_id, limit=limit, offset=offset
    )
    return [AdminServiceRequestOut.model_validate(row) for row in rows], total


async def reports(
    session: AsyncSession, *, status: str | None, target_type: str | None, limit: int, offset: int
) -> tuple[list[AdminReportOut], int]:
    rows, total = await repository.reports(
        session, status=status, target_type=target_type, limit=limit, offset=offset
    )
    return [AdminReportOut.model_validate(row) for row in rows], total


async def resolve_report(
    session: AsyncSession, services: Services, admin: AuthContext, report_id: uuid.UUID, data: ResolveReportIn
) -> AdminReportOut:
    """Status only: the reported content is never deleted here (moderation has its own routes)."""
    report = await repository.report(session, report_id, for_update=True)
    if report is None:
        raise NotFound("Report not found.")
    if report.status != ReportStatus.OPEN.value:
        raise Conflict("This report is already resolved.", code="REPORT_NOT_OPEN")
    now = services.clock.now()
    report.status, report.resolved_by, report.resolved_at = data.decision.value, admin.user_id, now
    report.resolution_note = data.note
    await audit.record(
        session,
        action="admin.report_resolved",
        entity_type="report",
        entity_id=report.id,
        actor_user_id=admin.user_id,
        actor_type=ActorType.ADMIN,
        data={
            "decision": data.decision.value,
            "target_type": report.target_type,
            "target_id": str(report.target_id),
        },
    )
    await session.commit()
    await session.refresh(report)
    return AdminReportOut.model_validate(report)


def audit_out(row: AuditLog) -> AdminAuditLogOut:
    return AdminAuditLogOut(
        id=row.id,
        occurred_at=row.occurred_at,
        actor_type=row.actor_type,
        actor_user_id=row.actor_user_id,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        request_id=row.request_id,
        ip=str(row.ip) if row.ip is not None else None,
        data=row.data,
    )


async def audit_logs(
    session: AsyncSession,
    *,
    action: str | None,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[AdminAuditLogOut], int]:
    rows, total = await repository.audit_logs(
        session,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return [audit_out(row) for row in rows], total


async def ops_status(session: AsyncSession, services: Services, stellar: StellarContext) -> OpsStatusOut:
    now = services.clock.now()
    counts = await repository.ops_counts(session)
    oldest = counts.pop("oldest_pending")
    rpc = RpcStatus(configured=False, healthy=None, latest_ledger=None, oldest_ledger=None, error=None)
    if stellar.gateway is not None:
        health = await stellar.gateway.health()  # never raises; failures are reported as unhealthy
        rpc = RpcStatus(
            configured=True,
            healthy=health.healthy,
            latest_ledger=health.latest_ledger,
            oldest_ledger=health.oldest_ledger,
            error=health.error,
        )
    state = await repository.sync_state(session, services.settings.escrow_contract_id)
    lag = None
    if state is not None and state.last_ledger is not None and rpc.latest_ledger is not None:
        lag = max(rpc.latest_ledger - state.last_ledger, 0)
    reconciler = ReconcilerStatus(
        enabled=stellar.gateway is not None and services.settings.reconciler_enabled,
        last_ledger=state.last_ledger if state else None,
        cursor_lag_ledgers=lag,
        leader_instance=state.leader_instance if state else None,
        leader_since=state.leader_since if state else None,
        last_error=state.last_error if state else None,
        last_error_at=state.last_error_at if state else None,
        updated_at=state.updated_at if state else None,
    )
    return OpsStatusOut(
        checked_at=now,
        oldest_pending_age_seconds=max(int((now - oldest).total_seconds()), 0) if oldest else None,
        rpc=rpc,
        reconciler=reconciler,
        **counts,
    )
