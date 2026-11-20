"""Admin console routes (ADMIN role only). Lists follow the limit/offset + X-Total-Count convention."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import AdminDep, ServicesDep, SessionDep, StellarDep
from app.core.errors import error_responses
from app.core.pagination import PageDep, set_page_headers
from app.modules.admin import service
from app.modules.admin.schemas import (
    AdminAuditLogOut,
    AdminBookingOut,
    AdminChainTxOut,
    AdminEscrowOut,
    AdminReportOut,
    AdminServiceRequestOut,
    AdminUserDetailOut,
    AdminUserOut,
    OpsStatusOut,
    ResolveReportIn,
)
from app.modules.bookings.models import BookingStatus
from app.modules.chat.models import ReportStatus, ReportTarget
from app.modules.payments.models import EscrowState, Reconciliation, TxKind, TxStatus
from app.modules.requests.models import RequestStatus
from app.modules.users.models import AccountStatus, Role

router = APIRouter(prefix="/admin", tags=["admin"])
_ERRORS = error_responses(401, 403, 422)


def _value(enum_member: object) -> str | None:
    return getattr(enum_member, "value", None)


@router.get("/users", responses=_ERRORS, summary="Search and filter users")
async def list_users(
    _: AdminDep,
    session: SessionDep,
    response: Response,
    page: PageDep,
    q: Annotated[
        str | None, Query(min_length=2, max_length=120, description="Email or name contains")
    ] = None,
    role: Role | None = None,
    status: AccountStatus | None = None,
) -> list[AdminUserOut]:
    items, total = await service.users(
        session, q=q, role=_value(role), status=_value(status), limit=page.limit, offset=page.offset
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get(
    "/users/{user_id}",
    responses=error_responses(401, 403, 404, 422),
    summary="User detail with activity counts",
)
async def get_user(
    user_id: uuid.UUID, _: AdminDep, session: SessionDep, services: ServicesDep
) -> AdminUserDetailOut:
    return await service.user_detail(session, services, user_id)


@router.get("/bookings", responses=_ERRORS, summary="All bookings with their escrow state")
async def list_bookings(
    _: AdminDep,
    session: SessionDep,
    response: Response,
    page: PageDep,
    status: BookingStatus | None = None,
    customer_id: uuid.UUID | None = None,
    professional_id: uuid.UUID | None = None,
) -> list[AdminBookingOut]:
    items, total = await service.bookings(
        session,
        status=_value(status),
        customer_id=customer_id,
        professional_id=professional_id,
        limit=page.limit,
        offset=page.offset,
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get("/escrows", responses=_ERRORS, summary="Escrows; failed_verification=true lists flagged ones")
async def list_escrows(
    _: AdminDep,
    session: SessionDep,
    response: Response,
    page: PageDep,
    state: EscrowState | None = None,
    reconciliation: Reconciliation | None = None,
    failed_verification: bool | None = None,
) -> list[AdminEscrowOut]:
    items, total = await service.escrows(
        session,
        state=_value(state),
        reconciliation=_value(reconciliation),
        failed_verification=failed_verification,
        limit=page.limit,
        offset=page.offset,
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get("/chain-transactions", responses=_ERRORS, summary="Chain transactions (hashes only, no XDR)")
async def list_chain_transactions(
    _: AdminDep,
    session: SessionDep,
    stellar: StellarDep,
    response: Response,
    page: PageDep,
    escrow_id: uuid.UUID | None = None,
    status: TxStatus | None = None,
    kind: TxKind | None = None,
) -> list[AdminChainTxOut]:
    items, total = await service.chain_transactions(
        session,
        stellar,
        escrow_id=escrow_id,
        status=_value(status),
        kind=_value(kind),
        limit=page.limit,
        offset=page.offset,
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get("/service-requests", responses=_ERRORS, summary="All service requests")
async def list_service_requests(
    _: AdminDep,
    session: SessionDep,
    response: Response,
    page: PageDep,
    status: RequestStatus | None = None,
    category_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
) -> list[AdminServiceRequestOut]:
    items, total = await service.service_requests(
        session,
        status=_value(status),
        category_id=category_id,
        customer_id=customer_id,
        limit=page.limit,
        offset=page.offset,
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get("/reports", responses=_ERRORS, summary="Report queue (messages, conversations, users, reviews)")
async def list_reports(
    _: AdminDep,
    session: SessionDep,
    response: Response,
    page: PageDep,
    status: ReportStatus | None = None,
    target_type: ReportTarget | None = None,
) -> list[AdminReportOut]:
    items, total = await service.reports(
        session, status=_value(status), target_type=_value(target_type), limit=page.limit, offset=page.offset
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.post(
    "/reports/{report_id}/resolve",
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Mark a report actioned or dismissed (audited; content is not deleted)",
)
async def resolve_report(
    report_id: uuid.UUID, data: ResolveReportIn, admin: AdminDep, session: SessionDep, services: ServicesDep
) -> AdminReportOut:
    return await service.resolve_report(session, services, admin, report_id, data)


@router.get("/audit-logs", responses=_ERRORS, summary="Audit log browser")
async def list_audit_logs(
    _: AdminDep,
    session: SessionDep,
    response: Response,
    page: PageDep,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AdminAuditLogOut]:
    items, total = await service.audit_logs(
        session,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        since=since,
        until=until,
        limit=page.limit,
        offset=page.offset,
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get(
    "/ops/status", responses=error_responses(401, 403), summary="Reconciler, chain transaction and RPC health"
)
async def ops_status(
    _: AdminDep, session: SessionDep, services: ServicesDep, stellar: StellarDep
) -> OpsStatusOut:
    return await service.ops_status(session, services, stellar)
