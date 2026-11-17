from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import CallerDep, HubDep, ServicesDep, SessionDep
from app.core.errors import error_responses
from app.core.pagination import PageDep, set_page_headers
from app.modules.bookings import service
from app.modules.bookings.models import BookingStatus
from app.modules.bookings.schemas import AgreementProof, BookingBundle, CancelBookingIn
from app.modules.users.models import Role

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get(
    "",
    responses=error_responses(401, 403, 422),
    summary="The caller's bookings (as customer and/or professional)",
)
async def list_bookings(
    response: Response,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    page: PageDep,
    status: BookingStatus | None = None,
    role: Role | None = None,
) -> list[BookingBundle]:
    items, total = await service.list_bookings(
        session, services, caller, status=status, role=role, limit=page.limit, offset=page.offset
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get(
    "/{booking_id}",
    responses=error_responses(401, 403, 404),
    summary="A booking with quote, parties and timeline",
)
async def get_booking(
    booking_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> BookingBundle:
    return await service.get_bundle(session, services, caller, booking_id)


@router.get(
    "/{booking_id}/agreement",
    responses=error_responses(401, 403, 404),
    summary="The canonical agreement document and its SHA-256, for independent verification",
)
async def get_agreement(
    booking_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> AgreementProof:
    return await service.agreement_proof(session, services, caller, booking_id)


@router.post(
    "/{booking_id}/start",
    responses=error_responses(401, 403, 404, 409),
    summary="Start work (professional; booking must be FUNDED)",
)
async def start_booking(
    booking_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep, hub: HubDep
) -> BookingBundle:
    return await service.start(session, services, hub, caller, booking_id)


@router.post(
    "/{booking_id}/cancel",
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Cancel a booking before payment (either party)",
)
async def cancel_booking(
    booking_id: uuid.UUID,
    data: CancelBookingIn,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    hub: HubDep,
) -> BookingBundle:
    return await service.cancel(session, services, hub, caller, booking_id, data.reason)
