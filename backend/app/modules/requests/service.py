"""Service requests: creation, the professional feed, responses and cancellation.

Privacy: professionals never see the exact location (``location_text``, coordinates) or
the customer's contact details. The address is revealed on the booking once it is funded.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.ratelimit import rate_limit_key
from app.modules.audit import service as audit
from app.modules.auth.context import AuthContext
from app.modules.campuses import repository as campuses_repository
from app.modules.campuses import service as campuses
from app.modules.campuses.schemas import CampusSummary
from app.modules.catalog import repository as catalog_repository
from app.modules.catalog import service as catalog
from app.modules.chat import repository as chat_repository
from app.modules.chat import service as chat
from app.modules.chat.hub import ConversationHub
from app.modules.chat.models import Conversation, MessageKind
from app.modules.professionals import repository as professionals_repository
from app.modules.professionals.models import ProfessionalProfile
from app.modules.requests import repository
from app.modules.requests.models import RequestStatus, ServiceRequest
from app.modules.requests.schemas import ServiceRequestIn, ServiceRequestOut, ServiceRequestOwnerOut
from app.modules.uploads import repository as uploads_repository
from app.modules.uploads import service as uploads
from app.modules.uploads.models import FilePurpose
from app.modules.users.models import Role

REQUEST_LIFETIME = timedelta(days=14)
REQUESTS_PER_HOUR = 20


def effective_status(request: ServiceRequest, now: datetime) -> RequestStatus:
    if request.status == RequestStatus.OPEN.value and request.expires_at <= now:
        return RequestStatus.EXPIRED
    return RequestStatus(request.status)


async def _professional_scope(
    session: AsyncSession, profile: ProfessionalProfile
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Category ids (with sub-categories) and campus ids a professional serves."""
    own = [profile.primary_category_id]
    slugs = (await professionals_repository.category_slugs(session, [profile.id])).get(profile.id, [])
    own += [c.id for c in await catalog_repository.get_by_slugs(session, slugs)]
    expanded: list[uuid.UUID] = []
    for category_id in dict.fromkeys(own):
        expanded += [category_id, *await catalog_repository.child_ids(session, category_id)]
    campus_ids = [
        c.id for c in (await professionals_repository.campuses_for(session, [profile.id])).get(profile.id, [])
    ]
    return list(dict.fromkeys(expanded)), campus_ids


async def _eligible(session: AsyncSession, profile: ProfessionalProfile, request: ServiceRequest) -> bool:
    if await repository.has_responded(session, profile.id, request.id):
        return True
    if request.target_professional_id is not None and request.target_professional_id != profile.id:
        return False
    categories, campus_ids = await _professional_scope(session, profile)
    return request.category_id in categories and (
        request.campus_id is None or request.campus_id in campus_ids
    )


async def can_read_request_media(session: AsyncSession, caller: AuthContext, file: object) -> bool:
    """Upload read rule: professionals eligible for (or responding to) the request may see its photos."""
    file_id = getattr(file, "id", None)
    if file_id is None or caller.role is not Role.PROFESSIONAL:
        return False
    profile = await professionals_repository.get_by_user(session, caller.user_id)
    if profile is None:
        return False
    for request in await repository.requests_for_file(session, file_id):
        if await _eligible(session, profile, request):
            return True
    return False


async def _present(
    session: AsyncSession,
    services: Services,
    requests: Sequence[ServiceRequest],
    *,
    owner_view: bool,
    responded: set[uuid.UUID] | None = None,
) -> list[ServiceRequestOut]:
    now = services.clock.now()
    media = await repository.media_for(session, [r.id for r in requests])
    files = {
        f.id: f
        for f in await uploads_repository.get_many(session, [fid for ids in media.values() for fid in ids])
    }
    slugs = await catalog.slugs_by_id(session, [r.category_id for r in requests])
    campus_rows = {
        c.id: c
        for c in await campuses_repository.get_many(session, [r.campus_id for r in requests if r.campus_id])
    }
    result: list[ServiceRequestOut] = []
    for request in requests:
        campus = campus_rows.get(request.campus_id) if request.campus_id else None
        base = {
            "id": request.id,
            "category_id": request.category_id,
            "category": slugs.get(request.category_id, ""),
            "title": request.title,
            "description": request.description,
            "item": request.item,
            "campus": CampusSummary.model_validate(campus) if campus else None,
            "city": campus.city if campus else None,
            "preferred_start": request.preferred_start,
            "preferred_end": request.preferred_end,
            "status": effective_status(request, now),
            "media": [uploads.file_ref(services, files[fid]) for fid in media[request.id] if fid in files],
            "targeted": request.target_professional_id is not None,
            "created_at": request.created_at,
            "expires_at": request.expires_at,
            "responded": request.id in (responded or set()),
        }
        if owner_view:
            result.append(
                ServiceRequestOwnerOut(
                    **base,
                    location_text=request.location_text,
                    latitude=str(request.latitude) if request.latitude is not None else None,
                    longitude=str(request.longitude) if request.longitude is not None else None,
                    target_professional_id=request.target_professional_id,
                    conversation_ids=await repository.conversation_ids(session, request.id),
                )
            )
        else:
            result.append(ServiceRequestOut(**base))
    return result


async def create(
    session: AsyncSession, services: Services, caller: AuthContext, data: ServiceRequestIn
) -> ServiceRequestOwnerOut:
    if caller.role is not Role.CUSTOMER:
        raise Forbidden("Only customers can post service requests.", code="ROLE_FORBIDDEN")
    now = services.clock.now()
    await services.rate_limiter.hit(
        bucket="service_requests",
        key=rate_limit_key(str(caller.user_id)),
        limit=REQUESTS_PER_HOUR,
        window=timedelta(hours=1),
        now=now,
    )
    await catalog.require_active_ids(session, [data.category_id])
    if data.campus_id is not None:
        await campuses.require_active(session, data.campus_id)
    if data.target_professional_id is not None:
        found = await professionals_repository.get_with_user(session, data.target_professional_id)
        if found is None or not found[0].is_listed or not found[1].is_active:
            raise BadRequest("Unknown professional.", code="UNKNOWN_PROFESSIONAL")
    await uploads.require_owned(session, caller, data.media_file_ids, FilePurpose.REQUEST_MEDIA)
    request = ServiceRequest(
        id=uuid.uuid4(),
        customer_id=caller.user_id,
        category_id=data.category_id,
        campus_id=data.campus_id,
        target_professional_id=data.target_professional_id,
        title=data.title,
        description=data.description,
        item=data.item,
        location_text=data.location_text,
        latitude=data.latitude,
        longitude=data.longitude,
        preferred_start=data.preferred_start,
        preferred_end=data.preferred_end,
        status=RequestStatus.OPEN.value,
        expires_at=now + REQUEST_LIFETIME,
    )
    repository.add(session, request)
    await session.flush()
    await repository.set_media(session, request.id, list(dict.fromkeys(data.media_file_ids)))
    await audit.record(
        session,
        action="request.created",
        entity_type="service_request",
        entity_id=request.id,
        actor_user_id=caller.user_id,
    )
    await session.commit()
    await session.refresh(request)
    out = (await _present(session, services, [request], owner_view=True))[0]
    assert isinstance(out, ServiceRequestOwnerOut)
    return out


async def list_mine(
    session: AsyncSession, services: Services, caller: AuthContext, *, limit: int, offset: int
) -> tuple[list[ServiceRequestOut], int]:
    rows, total = await repository.list_for_customer(session, caller.user_id, limit=limit, offset=offset)
    return await _present(session, services, rows, owner_view=True), total


async def _require_profile(session: AsyncSession, caller: AuthContext) -> ProfessionalProfile:
    if caller.role is not Role.PROFESSIONAL:
        raise Forbidden("Only professionals can do this.", code="ROLE_FORBIDDEN")
    profile = await professionals_repository.get_by_user(session, caller.user_id)
    if profile is None:
        raise NotFound("Create your professional profile first.", code="PROFILE_NOT_FOUND")
    return profile


async def feed(
    session: AsyncSession, services: Services, caller: AuthContext, *, limit: int, offset: int
) -> tuple[list[ServiceRequestOut], int]:
    profile = await _require_profile(session, caller)
    categories, campus_ids = await _professional_scope(session, profile)
    rows, total = await repository.feed(
        session,
        professional_id=profile.id,
        category_ids=categories,
        campus_ids=campus_ids,
        now=services.clock.now(),
        limit=limit,
        offset=offset,
    )
    responded = await repository.responded(session, profile.id, [r.id for r in rows])
    return await _present(session, services, rows, owner_view=False, responded=responded), total


async def get(
    session: AsyncSession, services: Services, caller: AuthContext, request_id: uuid.UUID
) -> ServiceRequestOut:
    request = await repository.get(session, request_id)
    if request is None:
        raise NotFound("Service request not found.")
    if caller.user_id == request.customer_id or caller.is_admin:
        return (await _present(session, services, [request], owner_view=True))[0]
    if caller.role is Role.PROFESSIONAL:
        profile = await professionals_repository.get_by_user(session, caller.user_id)
        if profile is not None and await _eligible(session, profile, request):
            responded = await repository.responded(session, profile.id, [request.id])
            return (await _present(session, services, [request], owner_view=False, responded=responded))[0]
    raise NotFound("Service request not found.")


async def respond(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    request_id: uuid.UUID,
    message: str,
) -> tuple[Conversation, bool]:
    """Open (or return) the professional's conversation about this request with a first message."""
    profile = await _require_profile(session, caller)
    request = await repository.get(session, request_id, for_update=True)
    if request is None or not await _eligible(session, profile, request):
        raise NotFound("Service request not found.")
    existing = await chat_repository.find_for_request(session, request.id, profile.id)
    if existing is not None:
        return existing, False
    now = services.clock.now()
    if effective_status(request, now) is not RequestStatus.OPEN:
        raise Conflict("This request is no longer open.", code="REQUEST_NOT_OPEN")
    try:
        conversation = await chat.create_conversation(
            session,
            customer_id=request.customer_id,
            professional_id=profile.id,
            professional_user_id=caller.user_id,
            service_request_id=request.id,
        )
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) != "uq_conversations_request_professional":
            raise
        existing = await chat_repository.find_for_request(session, request_id, profile.id)
        assert existing is not None
        return existing, False
    first = await chat.insert_message(
        session, conversation.id, sender=caller, body=message, kind=MessageKind.TEXT, now=now
    )
    await audit.record(
        session,
        action="request.responded",
        entity_type="service_request",
        entity_id=request.id,
        actor_user_id=caller.user_id,
        data={"conversation_id": str(conversation.id)},
    )
    await session.commit()
    await chat.publish_message(session, services, hub, first)
    return conversation, True


async def cancel(
    session: AsyncSession, services: Services, caller: AuthContext, request_id: uuid.UUID
) -> ServiceRequestOut:
    request = await repository.get(session, request_id, for_update=True)
    if request is None or request.customer_id != caller.user_id:
        raise NotFound("Service request not found.")
    if request.status == RequestStatus.BOOKED.value:
        raise Conflict(
            "This request already has a booking; cancel the booking instead.", code="REQUEST_BOOKED"
        )
    if request.status == RequestStatus.OPEN.value:
        request.status = RequestStatus.CANCELLED.value
        await audit.record(
            session,
            action="request.cancelled",
            entity_type="service_request",
            entity_id=request.id,
            actor_user_id=caller.user_id,
        )
    await session.commit()
    await session.refresh(request)
    return (await _present(session, services, [request], owner_view=True))[0]


async def mark_booked(session: AsyncSession, request: ServiceRequest) -> None:
    request.status = RequestStatus.BOOKED.value


async def reopen_if_booked(session: AsyncSession, request_id: uuid.UUID) -> None:
    """A booking cancelled before funding returns its request to the market."""
    request = await repository.get(session, request_id, for_update=True)
    if request is not None and request.status == RequestStatus.BOOKED.value:
        request.status = RequestStatus.OPEN.value


async def require_open_for_quote(
    session: AsyncSession, request_id: uuid.UUID, now: datetime
) -> ServiceRequest:
    request = await repository.get(session, request_id, for_update=True)
    if request is None:
        raise NotFound("Service request not found.")
    if effective_status(request, now) is not RequestStatus.OPEN:
        raise Conflict("This request is no longer open.", code="REQUEST_NOT_OPEN")
    return request


async def get_request(
    session: AsyncSession, request_id: uuid.UUID, *, for_update: bool = False
) -> ServiceRequest | None:
    return await repository.get(session, request_id, for_update=for_update)
