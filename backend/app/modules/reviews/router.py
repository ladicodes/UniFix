from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import AdminDep, CallerDep, ServicesDep, SessionDep
from app.core.errors import error_responses
from app.core.pagination import PageDep, set_page_headers
from app.modules.chat.schemas import ReportOut
from app.modules.reviews import service
from app.modules.reviews.schemas import ModerateIn, ResponseIn, ReviewIn, ReviewOut, ReviewReportIn

router = APIRouter(tags=["reviews"])


@router.post(
    "/bookings/{booking_id}/reviews",
    status_code=201,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Review a completed or resolved booking (its customer, once, within 30 days)",
)
async def create_review(
    booking_id: uuid.UUID, data: ReviewIn, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> ReviewOut:
    return await service.create(session, services, caller, booking_id, data)


@router.get(
    "/professionals/{professional_id}/reviews",
    responses=error_responses(422),
    summary="Published reviews of a professional (newest first)",
)
async def list_reviews(
    professional_id: uuid.UUID, response: Response, session: SessionDep, page: PageDep
) -> list[ReviewOut]:
    items, total = await service.list_published(
        session, professional_id, limit=page.limit, offset=page.offset
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.post(
    "/reviews/{review_id}/response",
    responses=error_responses(401, 403, 404, 409, 422),
    summary="The reviewed professional's single public response",
)
async def respond(
    review_id: uuid.UUID, data: ResponseIn, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> ReviewOut:
    return await service.respond(session, services, caller, review_id, data)


@router.post(
    "/reviews/{review_id}/report",
    status_code=201,
    responses=error_responses(401, 404, 409, 422),
    summary="Report a review for moderation",
)
async def report_review(
    review_id: uuid.UUID, data: ReviewReportIn, caller: CallerDep, session: SessionDep
) -> ReportOut:
    return ReportOut.model_validate(await service.report(session, caller, review_id, data))


@router.post(
    "/admin/reviews/{review_id}/moderate",
    tags=["admin"],
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Hide, restore or remove a review (admin; audited; ratings recomputed)",
)
async def moderate_review(
    review_id: uuid.UUID, data: ModerateIn, admin: AdminDep, session: SessionDep, services: ServicesDep
) -> ReviewOut:
    return await service.moderate(session, services, admin, review_id, data)
