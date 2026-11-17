from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import AdminDep, OptionalCallerDep, ServicesDep, SessionDep, require_role
from app.core.errors import error_responses
from app.core.pagination import PageDep, set_page_headers
from app.modules.auth.context import AuthContext
from app.modules.professionals import service
from app.modules.professionals.models import Availability, CheckStatus, SortOrder
from app.modules.professionals.schemas import (
    AdminVerificationOut,
    PortfolioCreateIn,
    PortfolioItemOut,
    PortfolioUpdateIn,
    ProfessionalCreateIn,
    ProfessionalOut,
    ProfessionalPrivateOut,
    ProfessionalUpdateIn,
    VerificationDecisionIn,
    VerificationSubmitIn,
)
from app.modules.users.models import Role

router = APIRouter(tags=["professionals"])
ProfessionalDep = Annotated[AuthContext, Depends(require_role(Role.PROFESSIONAL))]


@router.get(
    "/professionals",
    responses=error_responses(422),
    summary="Discover professionals (search, filter, sort, paginate)",
    description=(
        "Only listed professionals with active accounts are returned. `NEAREST` uses `lat`/`lng`, "
        "else the `campus` filter's centroid, else the caller's campus; without any, `distance_km` is null."
    ),
)
async def discover(
    response: Response,
    session: SessionDep,
    caller: OptionalCallerDep,
    page: PageDep,
    q: Annotated[str | None, Query(max_length=100, description="Full-text search")] = None,
    category: Annotated[
        str | None, Query(max_length=64, description="Category slug (includes sub-categories)")
    ] = None,
    campus: Annotated[str | None, Query(max_length=64, description="Campus slug")] = None,
    city: Annotated[str | None, Query(max_length=80)] = None,
    availability: Annotated[Availability | None, Query(description="NOW or TODAY")] = None,
    min_rating: Annotated[float | None, Query(ge=0, le=5)] = None,
    verified_only: bool = False,
    sort: SortOrder = SortOrder.BEST,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
) -> list[ProfessionalOut]:
    items, total = await service.discover(
        session,
        caller,
        service.DiscoveryQuery(
            q=q.strip() or None if q else None,
            category=category,
            campus=campus,
            city=city.strip() or None if city else None,
            availability=availability,
            min_rating=min_rating,
            verified_only=verified_only,
            sort=sort,
            lat=lat if lng is not None else None,
            lng=lng if lat is not None else None,
        ),
        limit=page.limit,
        offset=page.offset,
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.post(
    "/professionals/me",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 409, 422),
    summary="Create the caller's professional profile (once)",
)
async def create_profile(
    data: ProfessionalCreateIn, caller: ProfessionalDep, session: SessionDep, services: ServicesDep
) -> ProfessionalPrivateOut:
    profile = await service.create_profile(session, caller, data)
    return await service.present_private(session, services, profile, caller.user)


@router.get(
    "/professionals/me",
    responses=error_responses(401, 403, 404),
    summary="The caller's own profile, including private verification details",
)
async def get_my_profile(
    caller: ProfessionalDep, session: SessionDep, services: ServicesDep
) -> ProfessionalPrivateOut:
    return await service.get_mine(session, services, caller)


@router.get(
    "/professionals/{professional_id}",
    responses=error_responses(404),
    summary="Public professional profile",
)
async def get_professional(
    professional_id: uuid.UUID, session: SessionDep, caller: OptionalCallerDep
) -> ProfessionalOut:
    reference = await service.reference_for(session, caller)
    return await service.get_public(session, caller, professional_id, reference)


@router.patch(
    "/professionals/{professional_id}",
    responses=error_responses(400, 401, 403, 404, 422),
    summary="Update the caller's own professional profile",
)
async def update_profile(
    professional_id: uuid.UUID,
    data: ProfessionalUpdateIn,
    caller: ProfessionalDep,
    session: SessionDep,
    services: ServicesDep,
) -> ProfessionalPrivateOut:
    profile = await service.update_profile(session, caller, professional_id, data)
    return await service.present_private(session, services, profile, caller.user)


@router.post(
    "/professionals/me/portfolio",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="Add a portfolio item (image uploaded first with purpose PORTFOLIO)",
)
async def add_portfolio_item(
    data: PortfolioCreateIn, caller: ProfessionalDep, session: SessionDep
) -> PortfolioItemOut:
    return service.portfolio_out(await service.add_portfolio_item(session, caller, data))


@router.patch(
    "/professionals/me/portfolio/{item_id}",
    responses=error_responses(400, 401, 403, 404, 422),
    summary="Edit a portfolio item",
)
async def update_portfolio_item(
    item_id: uuid.UUID, data: PortfolioUpdateIn, caller: ProfessionalDep, session: SessionDep
) -> PortfolioItemOut:
    return service.portfolio_out(await service.update_portfolio_item(session, caller, item_id, data))


@router.delete(
    "/professionals/me/portfolio/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404),
    summary="Remove a portfolio item",
)
async def delete_portfolio_item(item_id: uuid.UUID, caller: ProfessionalDep, session: SessionDep) -> Response:
    await service.delete_portfolio_item(session, caller, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/professionals/me/verifications",
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="Submit (or resubmit) a verification check; documents stay private",
)
async def submit_verification(
    data: VerificationSubmitIn, caller: ProfessionalDep, session: SessionDep, services: ServicesDep
) -> ProfessionalPrivateOut:
    return await service.submit_verification(session, services, caller, data)


@router.get(
    "/admin/verifications",
    tags=["admin"],
    responses=error_responses(401, 403, 422),
    summary="Verification review queue (admin), oldest first",
)
async def list_verifications(
    response: Response,
    admin: AdminDep,
    session: SessionDep,
    services: ServicesDep,
    page: PageDep,
    status_filter: Annotated[CheckStatus | None, Query(alias="status")] = CheckStatus.PENDING,
) -> list[AdminVerificationOut]:
    items, total = await service.list_verifications(
        session, services, status=status_filter, limit=page.limit, offset=page.offset
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.post(
    "/admin/verifications/{verification_id}/decision",
    tags=["admin"],
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Approve or reject a pending verification check (admin)",
)
async def decide_verification(
    verification_id: uuid.UUID,
    data: VerificationDecisionIn,
    admin: AdminDep,
    session: SessionDep,
    services: ServicesDep,
) -> AdminVerificationOut:
    await service.decide_verification(session, services, admin, verification_id, data)
    return await service.admin_verification(session, services, verification_id)
