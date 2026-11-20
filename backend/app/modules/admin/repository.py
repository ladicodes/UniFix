"""Read queries for the admin console. Every list is ordered newest first and backed by an index."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthSessionFamily
from app.modules.bookings.models import Booking
from app.modules.chat.models import Report, ReportStatus, ReportTarget
from app.modules.disputes.models import ACTIVE_DISPUTE, Dispute
from app.modules.payments.models import (
    ChainEvent,
    ChainSyncState,
    ChainTransaction,
    Escrow,
    EventStatus,
    TxStatus,
)
from app.modules.professionals.models import ProfessionalProfile
from app.modules.requests.models import ServiceRequest
from app.modules.users.models import User
from app.modules.wallets.models import Wallet


async def _page(
    session: AsyncSession,
    statement: Select[Any] | Any,
    where: Sequence[ColumnElement[bool]],
    *,
    limit: int,
    offset: int,
) -> tuple[list[Any], int]:
    filtered = statement.where(*where)
    total = (
        await session.execute(select(func.count()).select_from(filtered.order_by(None).subquery()))
    ).scalar_one()
    rows = (await session.execute(filtered.limit(limit).offset(offset))).all()
    return list(rows), int(total)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def users(
    session: AsyncSession, *, q: str | None, role: str | None, status: str | None, limit: int, offset: int
) -> tuple[list[User], int]:
    where: list[ColumnElement[bool]] = []
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        where.append(or_(User.email.ilike(pattern, escape="\\"), User.full_name.ilike(pattern, escape="\\")))
    if role:
        where.append(User.role == role)
    if status:
        where.append(User.status == status)
    rows, total = await _page(
        session,
        select(User).order_by(User.created_at.desc(), User.id.desc()),
        where,
        limit=limit,
        offset=offset,
    )
    return [row[0] for row in rows], total


async def user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def profile_for(session: AsyncSession, user_id: uuid.UUID) -> ProfessionalProfile | None:
    return (
        await session.execute(select(ProfessionalProfile).where(ProfessionalProfile.user_id == user_id))
    ).scalar_one_or_none()


async def wallets_for(session: AsyncSession, user_id: uuid.UUID) -> Sequence[Wallet]:
    rows = await session.execute(
        select(Wallet).where(Wallet.user_id == user_id).order_by(Wallet.created_at.desc())
    )
    return rows.scalars().all()


async def _count(session: AsyncSession, model: Any, *where: ColumnElement[bool]) -> int:
    return int((await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one())


async def user_counts(
    session: AsyncSession, user_id: uuid.UUID, profile_id: uuid.UUID | None, now: datetime
) -> dict[str, int]:
    return {
        "active_sessions": await _count(
            session,
            AuthSessionFamily,
            AuthSessionFamily.user_id == user_id,
            AuthSessionFamily.revoked_at.is_(None),
            AuthSessionFamily.absolute_expires_at > now,
        ),
        "bookings_as_customer": await _count(session, Booking, Booking.customer_id == user_id),
        "bookings_as_professional": (
            await _count(session, Booking, Booking.professional_id == profile_id) if profile_id else 0
        ),
        "reports_filed": await _count(session, Report, Report.reporter_id == user_id),
        "reports_against": await _count(
            session, Report, Report.target_type == ReportTarget.USER.value, Report.target_id == user_id
        ),
    }


async def bookings(
    session: AsyncSession,
    *,
    status: str | None,
    customer_id: uuid.UUID | None,
    professional_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Booking, Escrow | None]], int]:
    where: list[ColumnElement[bool]] = []
    if status:
        where.append(Booking.status == status)
    if customer_id:
        where.append(Booking.customer_id == customer_id)
    if professional_id:
        where.append(Booking.professional_id == professional_id)
    statement = (
        select(Booking, Escrow)
        .outerjoin(Escrow, Escrow.booking_id == Booking.id)
        .order_by(Booking.created_at.desc(), Booking.id.desc())
    )
    rows, total = await _page(session, statement, where, limit=limit, offset=offset)
    return [(row[0], row[1]) for row in rows], total


async def escrows(
    session: AsyncSession,
    *,
    state: str | None,
    reconciliation: str | None,
    failed_verification: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[Escrow], int]:
    where: list[ColumnElement[bool]] = []
    if state:
        where.append(Escrow.state == state)
    if reconciliation:
        where.append(Escrow.reconciliation == reconciliation)
    if failed_verification is True:
        where.append(Escrow.verification_error.is_not(None))
    elif failed_verification is False:
        where.append(Escrow.verification_error.is_(None))
    rows, total = await _page(
        session,
        select(Escrow).order_by(Escrow.created_at.desc(), Escrow.id.desc()),
        where,
        limit=limit,
        offset=offset,
    )
    return [row[0] for row in rows], total


async def chain_transactions(
    session: AsyncSession,
    *,
    escrow_id: uuid.UUID | None,
    status: str | None,
    kind: str | None,
    limit: int,
    offset: int,
) -> tuple[list[ChainTransaction], int]:
    where: list[ColumnElement[bool]] = []
    if escrow_id:
        where.append(ChainTransaction.escrow_id == escrow_id)
    if status:
        where.append(ChainTransaction.status == status)
    if kind:
        where.append(ChainTransaction.kind == kind)
    statement = select(ChainTransaction).order_by(
        ChainTransaction.created_at.desc(), ChainTransaction.id.desc()
    )
    rows, total = await _page(session, statement, where, limit=limit, offset=offset)
    return [row[0] for row in rows], total


async def service_requests(
    session: AsyncSession,
    *,
    status: str | None,
    category_id: uuid.UUID | None,
    customer_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[ServiceRequest], int]:
    where: list[ColumnElement[bool]] = []
    if status:
        where.append(ServiceRequest.status == status)
    if category_id:
        where.append(ServiceRequest.category_id == category_id)
    if customer_id:
        where.append(ServiceRequest.customer_id == customer_id)
    statement = select(ServiceRequest).order_by(ServiceRequest.created_at.desc(), ServiceRequest.id.desc())
    rows, total = await _page(session, statement, where, limit=limit, offset=offset)
    return [row[0] for row in rows], total


async def reports(
    session: AsyncSession, *, status: str | None, target_type: str | None, limit: int, offset: int
) -> tuple[list[Report], int]:
    where: list[ColumnElement[bool]] = []
    if status:
        where.append(Report.status == status)
    if target_type:
        where.append(Report.target_type == target_type)
    statement = select(Report).order_by(Report.created_at.desc(), Report.id.desc())
    rows, total = await _page(session, statement, where, limit=limit, offset=offset)
    return [row[0] for row in rows], total


async def report(session: AsyncSession, report_id: uuid.UUID, *, for_update: bool = False) -> Report | None:
    statement = select(Report).where(Report.id == report_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


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
) -> tuple[list[AuditLog], int]:
    where: list[ColumnElement[bool]] = []
    if action:
        where.append(AuditLog.action == action)
    if entity_type:
        where.append(AuditLog.entity_type == entity_type)
    if entity_id:
        where.append(AuditLog.entity_id == entity_id)
    if actor_user_id:
        where.append(AuditLog.actor_user_id == actor_user_id)
    if since:
        where.append(AuditLog.occurred_at >= since)
    if until:
        where.append(AuditLog.occurred_at < until)
    statement = select(AuditLog).order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
    rows, total = await _page(session, statement, where, limit=limit, offset=offset)
    return [row[0] for row in rows], total


# ---------------------------------------------------------------- ops status (all indexed)

_PENDING = (TxStatus.SUBMITTED.value, TxStatus.PENDING.value)


async def ops_counts(session: AsyncSession) -> dict[str, Any]:
    oldest = (
        await session.execute(
            select(func.min(func.coalesce(ChainTransaction.submitted_at, ChainTransaction.created_at))).where(
                ChainTransaction.status.in_(_PENDING)
            )
        )
    ).scalar_one()
    return {
        "pending_tx_count": await _count(session, ChainTransaction, ChainTransaction.status.in_(_PENDING)),
        "awaiting_signature_count": await _count(
            session, ChainTransaction, ChainTransaction.status == TxStatus.PREPARED.value
        ),
        "oldest_pending": oldest,
        "failed_verification_count": await _count(session, Escrow, Escrow.verification_error.is_not(None)),
        "conflict_event_count": await _count(
            session, ChainEvent, ChainEvent.status == EventStatus.CONFLICT.value
        ),
        "unapplied_event_count": await _count(
            session, ChainEvent, ChainEvent.status == EventStatus.INGESTED.value
        ),
        "open_disputes": await _count(
            session, Dispute, Dispute.status.in_([s.value for s in ACTIVE_DISPUTE])
        ),
        "open_reports": await _count(session, Report, Report.status == ReportStatus.OPEN.value),
    }


async def sync_state(session: AsyncSession, contract_id: str | None) -> ChainSyncState | None:
    if contract_id is None:
        return None
    return await session.get(ChainSyncState, contract_id)
