"""Professional profiles, discovery, portfolio and the verification workflow."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import Conflict, Forbidden, NotFound
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.auth.context import AuthContext
from app.modules.campuses import service as campuses
from app.modules.campuses.schemas import CampusSummary
from app.modules.catalog import service as catalog
from app.modules.notifications import service as notifications
from app.modules.notifications.models import NotificationType
from app.modules.professionals import repository
from app.modules.professionals.models import (
    Availability,
    CheckStatus,
    PortfolioItem,
    ProfessionalProfile,
    ProfessionalVerification,
    SortOrder,
    VerificationStatus,
    VerificationType,
)
from app.modules.professionals.repository import SearchFilters, SearchRow
from app.modules.professionals.schemas import (
    AdminVerificationOut,
    PortfolioCreateIn,
    PortfolioItemOut,
    PortfolioUpdateIn,
    ProfessionalCreateIn,
    ProfessionalOut,
    ProfessionalPrivateOut,
    ProfessionalUpdateIn,
    RatingBreakdown,
    VerificationDecisionIn,
    VerificationFlags,
    VerificationOut,
    VerificationSubmitIn,
)
from app.modules.uploads import service as uploads
from app.modules.uploads.models import FilePurpose
from app.modules.users.models import Role, User

MAX_PORTFOLIO_ITEMS = 30
# "Available now" means NOW; "available today" includes those available now.
_AVAILABILITY_FILTER: dict[Availability, list[str]] = {
    Availability.NOW: [Availability.NOW.value],
    Availability.TODAY: [Availability.NOW.value, Availability.TODAY.value],
}
_COORDINATE_PRECISION = Decimal("0.01")  # ~1.1 km: stored locations are deliberately approximate


def _approximate(value: Decimal | None) -> Decimal | None:
    return value.quantize(_COORDINATE_PRECISION, rounding=ROUND_HALF_UP) if value is not None else None


def derive_status(checks: Sequence[ProfessionalVerification]) -> VerificationStatus:
    """VERIFIED requires a verified IDENTITY check; otherwise pending beats rejected beats nothing."""
    by_type = {check.type: check.status for check in checks}
    if by_type.get(VerificationType.IDENTITY.value) == CheckStatus.VERIFIED.value:
        return VerificationStatus.VERIFIED
    if CheckStatus.PENDING.value in by_type.values():
        return VerificationStatus.PENDING
    if CheckStatus.REJECTED.value in by_type.values():
        return VerificationStatus.REJECTED
    return VerificationStatus.NOT_SUBMITTED


# ---------------------------------------------------------------- creation and updates


async def _category_ids(session: AsyncSession, primary: str, extra: Sequence[str]) -> list[uuid.UUID]:
    categories = await catalog.require_active_by_slugs(session, [primary, *extra])
    return [category.id for category in categories]


async def _create(session: AsyncSession, user: User, data: ProfessionalCreateIn) -> ProfessionalProfile:
    category_ids = await _category_ids(session, data.category_slug, data.category_slugs)
    await campuses.require_active_many(session, data.campus_ids)
    profile = ProfessionalProfile(
        id=uuid.uuid4(),
        user_id=user.id,
        primary_category_id=category_ids[0],
        headline=data.headline,
        bio=data.bio,
        city=data.city,
        area=data.area,
        country=data.country.value,
        latitude=_approximate(data.latitude),
        longitude=_approximate(data.longitude),
        years_experience=data.years_experience,
        availability=data.availability.value,
        starting_price_minor=data.starting_price_minor,
        currency=data.currency.value,
        skills=data.skills,
        languages=data.languages,
        coverage=data.coverage,
        verification_status=VerificationStatus.NOT_SUBMITTED.value,
    )
    repository.add(session, profile)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_professional_profiles_user_id":
            raise Conflict(
                "A professional profile already exists for this account.", code="PROFILE_EXISTS"
            ) from exc
        raise
    await repository.replace_categories(session, profile.id, category_ids)
    await repository.replace_campuses(session, profile.id, list(dict.fromkeys(data.campus_ids)))
    await audit.record(
        session,
        action="professional.profile_created",
        entity_type="professional",
        entity_id=profile.id,
        actor_user_id=user.id,
    )
    return profile


def onboarding_step(data: ProfessionalCreateIn) -> Callable[[AsyncSession, User], Awaitable[None]]:
    """Registration hook: create the profile in the same transaction as the account."""

    async def step(session: AsyncSession, user: User) -> None:
        await _create(session, user, data)

    return step


async def create_profile(
    session: AsyncSession, caller: AuthContext, data: ProfessionalCreateIn
) -> ProfessionalProfile:
    if await repository.get_by_user(session, caller.user_id) is not None:
        raise Conflict("A professional profile already exists for this account.", code="PROFILE_EXISTS")
    profile = await _create(session, caller.user, data)
    await session.commit()
    return profile


async def update_profile(
    session: AsyncSession, caller: AuthContext, professional_id: uuid.UUID, data: ProfessionalUpdateIn
) -> ProfessionalProfile:
    profile = await repository.get(session, professional_id, for_update=True)
    if profile is None or profile.user_id != caller.user_id:
        raise NotFound("Professional not found.")
    changes = data.model_dump(exclude_unset=True)
    if "category_slug" in changes or "category_slugs" in changes:
        current = await repository.category_slugs(session, [profile.id])
        primary = changes.get("category_slug") or await _primary_slug(session, profile)
        extra = changes.get("category_slugs")
        extra_slugs = extra if extra is not None else [s for s in current.get(profile.id, []) if s != primary]
        category_ids = await _category_ids(session, primary, extra_slugs)
        profile.primary_category_id = category_ids[0]
        await repository.replace_categories(session, profile.id, category_ids)
    if changes.get("campus_ids") is not None:
        await campuses.require_active_many(session, changes["campus_ids"])
        await repository.replace_campuses(session, profile.id, list(dict.fromkeys(changes["campus_ids"])))
    if "latitude" in changes:
        profile.latitude = _approximate(data.latitude)
        profile.longitude = _approximate(data.longitude)
    simple = {
        "headline", "bio", "city", "area", "coverage", "years_experience",
        "starting_price_minor", "skills", "languages", "is_listed",
    }  # fmt: skip
    for field in simple & changes.keys():
        if changes[field] is not None:
            setattr(profile, field, changes[field])
    for field in ("currency", "availability"):
        if changes.get(field) is not None:
            setattr(profile, field, changes[field].value)
    await audit.record(
        session,
        action="professional.profile_updated",
        entity_type="professional",
        entity_id=profile.id,
        actor_user_id=caller.user_id,
        data={"fields": sorted(changes)},
    )
    await session.commit()
    await session.refresh(profile)
    return profile


async def _primary_slug(session: AsyncSession, profile: ProfessionalProfile) -> str:
    categories = await catalog.require_active_ids(session, [profile.primary_category_id])
    return categories[0].slug


# ---------------------------------------------------------------- presentation


@dataclass(frozen=True, slots=True)
class _Bundle:
    categories: dict[uuid.UUID, list[str]]
    campuses: dict[uuid.UUID, list[CampusSummary]]
    portfolio: dict[uuid.UUID, list[PortfolioItem]]
    verifications: dict[uuid.UUID, list[ProfessionalVerification]]
    primary_slugs: dict[uuid.UUID, str]
    avatar_urls: dict[uuid.UUID, str | None]


async def _load(session: AsyncSession, rows: Sequence[SearchRow]) -> _Bundle:
    ids = [row.profile.id for row in rows]
    categories = await repository.category_slugs(session, ids)
    campus_rows = await repository.campuses_for(session, ids)
    primary = await catalog.slugs_by_id(session, [row.profile.primary_category_id for row in rows])
    avatar_ids = [row.user.avatar_file_id for row in rows if row.user.avatar_file_id]
    avatars = await repository.files_by_id(session, avatar_ids)
    return _Bundle(
        categories=categories,
        campuses={
            pid: [CampusSummary.model_validate(campus) for campus in items]
            for pid, items in campus_rows.items()
        },
        portfolio=await repository.portfolio_for(session, ids),
        verifications=await repository.verifications_for(session, ids),
        primary_slugs={row.profile.id: primary[row.profile.primary_category_id] for row in rows},
        avatar_urls={
            row.user.id: uploads.public_url(avatars.get(row.user.avatar_file_id))
            if row.user.avatar_file_id
            else None
            for row in rows
        },
    )


def _public(row: SearchRow, bundle: _Bundle) -> ProfessionalOut:
    profile, user = row.profile, row.user
    checks = {check.type: check.status for check in bundle.verifications.get(profile.id, [])}
    verified = CheckStatus.VERIFIED.value
    return ProfessionalOut(
        id=profile.id,
        user_id=user.id,
        name=user.full_name,
        avatar_url=bundle.avatar_urls.get(user.id),
        category=bundle.primary_slugs[profile.id],
        categories=bundle.categories.get(profile.id, []),
        headline=profile.headline,
        bio=profile.bio,
        city=profile.city,
        area=profile.area,
        country=profile.country,
        campuses=bundle.campuses.get(profile.id, []),
        distance_km=row.distance_km,
        coverage=profile.coverage,
        skills=profile.skills,
        languages=profile.languages,
        rating=float(profile.rating_avg),
        review_count=profile.rating_count,
        completed_jobs=profile.completed_jobs,
        years_experience=profile.years_experience,
        verification=VerificationFlags(
            identity=checks.get(VerificationType.IDENTITY.value) == verified,
            trade=checks.get(VerificationType.TRADE.value) == verified,
            phone=checks.get(VerificationType.PHONE.value) == verified,
        ),
        verification_status=VerificationStatus(profile.verification_status),
        availability=Availability(profile.availability),
        response_minutes=profile.response_minutes,
        starting_price_minor=profile.starting_price_minor,
        currency=profile.currency,
        portfolio=[
            PortfolioItemOut(
                id=item.id,
                title=item.title,
                caption=item.caption,
                image_url=f"/api/v1/files/{item.image_file_id}",
                category_id=item.category_id,
            )
            for item in bundle.portfolio.get(profile.id, [])
        ],
        rating_breakdown=RatingBreakdown(
            quality=float(profile.rating_quality),
            punctuality=float(profile.rating_punctuality),
            communication=float(profile.rating_communication),
            professionalism=float(profile.rating_professionalism),
            value=float(profile.rating_value),
        ),
        joined_at=profile.created_at,
    )


async def present_many(session: AsyncSession, rows: Sequence[SearchRow]) -> list[ProfessionalOut]:
    bundle = await _load(session, rows)
    return [_public(row, bundle) for row in rows]


async def _verification_out(
    session: AsyncSession, services: Services, checks: Sequence[ProfessionalVerification]
) -> list[VerificationOut]:
    files = await repository.files_by_id(session, [fid for check in checks for fid in check.file_ids])
    return [
        VerificationOut(
            id=check.id,
            type=VerificationType(check.type),
            status=CheckStatus(check.status),
            note=check.note,
            files=[uploads.file_ref(services, files[fid]) for fid in check.file_ids if fid in files],
            submitted_at=check.submitted_at,
            reviewed_at=check.reviewed_at,
            rejection_reason=check.rejection_reason,
        )
        for check in sorted(checks, key=lambda c: c.type)
    ]


async def present_private(
    session: AsyncSession, services: Services, profile: ProfessionalProfile, user: User
) -> ProfessionalPrivateOut:
    row = SearchRow(profile=profile, user=user, distance_km=None)
    bundle = await _load(session, [row])
    public = _public(row, bundle)
    return ProfessionalPrivateOut(
        **public.model_dump(),
        is_listed=profile.is_listed,
        latitude=profile.latitude,
        longitude=profile.longitude,
        verifications=await _verification_out(session, services, bundle.verifications.get(profile.id, [])),
    )


# ---------------------------------------------------------------- reads and discovery


async def get_public(
    session: AsyncSession,
    caller: AuthContext | None,
    professional_id: uuid.UUID,
    reference: tuple[float, float] | None,
) -> ProfessionalOut:
    found = await repository.get_with_user(session, professional_id)
    if found is None:
        raise NotFound("Professional not found.")
    profile, user = found
    visible = profile.is_listed and user.is_active
    is_privileged = caller is not None and (caller.is_admin or caller.user_id == user.id)
    if not visible and not is_privileged:
        raise NotFound("Professional not found.")
    distance = await repository.distance_to(session, profile.id, reference) if reference else None
    return (await present_many(session, [SearchRow(profile=profile, user=user, distance_km=distance)]))[0]


async def reference_for(session: AsyncSession, caller: AuthContext | None) -> tuple[float, float] | None:
    """The caller's own campus centroid, used for distance on profile pages."""
    if caller is None or caller.user.campus_id is None:
        return None
    campus = await campuses.get_active(session, caller.user.campus_id)
    return campuses.centroid(campus) if campus else None


async def get_mine(session: AsyncSession, services: Services, caller: AuthContext) -> ProfessionalPrivateOut:
    profile = await repository.get_by_user(session, caller.user_id)
    if profile is None:
        raise NotFound("You have not created a professional profile yet.", code="PROFILE_NOT_FOUND")
    return await present_private(session, services, profile, caller.user)


async def require_own_profile(session: AsyncSession, caller: AuthContext) -> ProfessionalProfile:
    profile = await repository.get_by_user(session, caller.user_id, for_update=True)
    if profile is None:
        raise NotFound("You have not created a professional profile yet.", code="PROFILE_NOT_FOUND")
    return profile


@dataclass(frozen=True, slots=True)
class DiscoveryQuery:
    q: str | None
    category: str | None
    campus: str | None
    city: str | None
    availability: Availability | None
    min_rating: float | None
    verified_only: bool
    sort: SortOrder
    lat: float | None
    lng: float | None


async def discover(
    session: AsyncSession, caller: AuthContext | None, query: DiscoveryQuery, *, limit: int, offset: int
) -> tuple[list[ProfessionalOut], int]:
    category_ids: list[uuid.UUID] | None = None
    if query.category:
        category_ids = await catalog.ids_including_children(session, query.category)
        if category_ids is None:
            return [], 0  # unknown category: nothing matches
    campus_id: uuid.UUID | None = None
    campus_reference: tuple[float, float] | None = None
    if query.campus:
        campus = await campuses.get_active_by_slug(session, query.campus)
        if campus is None:
            return [], 0
        campus_id = campus.id
        campus_reference = campuses.centroid(campus)
    reference = await _reference_point(session, caller, query, campus_reference)
    availability = _AVAILABILITY_FILTER.get(query.availability) if query.availability else None
    rows, total = await repository.search(
        session,
        SearchFilters(
            q=query.q,
            category_ids=category_ids,
            campus_id=campus_id,
            city=query.city,
            availability=availability,
            min_rating=query.min_rating,
            verified_only=query.verified_only,
            sort=query.sort,
            reference=reference,
            limit=limit,
            offset=offset,
        ),
    )
    return await present_many(session, rows), total


async def _reference_point(
    session: AsyncSession,
    caller: AuthContext | None,
    query: DiscoveryQuery,
    campus_reference: tuple[float, float] | None,
) -> tuple[float, float] | None:
    if query.lat is not None and query.lng is not None:
        return (query.lat, query.lng)
    if campus_reference is not None:
        return campus_reference
    return await reference_for(session, caller)


# ---------------------------------------------------------------- portfolio


async def add_portfolio_item(
    session: AsyncSession, caller: AuthContext, data: PortfolioCreateIn
) -> PortfolioItem:
    profile = await require_own_profile(session, caller)
    if await repository.count_portfolio(session, profile.id) >= MAX_PORTFOLIO_ITEMS:
        raise Conflict(f"A portfolio holds at most {MAX_PORTFOLIO_ITEMS} items.", code="PORTFOLIO_FULL")
    await uploads.require_owned(session, caller, [data.image_file_id], FilePurpose.PORTFOLIO)
    if data.category_id is not None:
        await catalog.require_active_ids(session, [data.category_id])
    item = PortfolioItem(
        professional_id=profile.id,
        title=data.title,
        caption=data.caption,
        category_id=data.category_id,
        image_file_id=data.image_file_id,
        sort_order=await repository.count_portfolio(session, profile.id),
    )
    repository.add(session, item)
    await session.commit()
    await session.refresh(item)
    return item


async def update_portfolio_item(
    session: AsyncSession, caller: AuthContext, item_id: uuid.UUID, data: PortfolioUpdateIn
) -> PortfolioItem:
    profile = await require_own_profile(session, caller)
    item = await repository.get_portfolio_item(session, item_id, profile.id)
    if item is None:
        raise NotFound("Portfolio item not found.")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("category_id") is not None:
        await catalog.require_active_ids(session, [changes["category_id"]])
    for field, value in changes.items():
        if value is None and field in {"title", "caption", "sort_order"}:
            continue
        setattr(item, field, value)
    await session.commit()
    await session.refresh(item)
    return item


async def delete_portfolio_item(session: AsyncSession, caller: AuthContext, item_id: uuid.UUID) -> None:
    profile = await require_own_profile(session, caller)
    item = await repository.get_portfolio_item(session, item_id, profile.id)
    if item is None:
        raise NotFound("Portfolio item not found.")
    await repository.delete_portfolio_item(session, item)
    await session.commit()


def portfolio_out(item: PortfolioItem) -> PortfolioItemOut:
    return PortfolioItemOut(
        id=item.id,
        title=item.title,
        caption=item.caption,
        image_url=f"/api/v1/files/{item.image_file_id}",
        category_id=item.category_id,
    )


# ---------------------------------------------------------------- verification


async def _refresh_status(session: AsyncSession, profile: ProfessionalProfile) -> None:
    checks = (await repository.verifications_for(session, [profile.id])).get(profile.id, [])
    profile.verification_status = derive_status(checks).value


async def submit_verification(
    session: AsyncSession, services: Services, caller: AuthContext, data: VerificationSubmitIn
) -> ProfessionalPrivateOut:
    profile = await require_own_profile(session, caller)
    await uploads.require_owned(session, caller, data.file_ids, FilePurpose.VERIFICATION_DOCUMENT)
    now = services.clock.now()
    check = await repository.get_verification_by_type(session, profile.id, data.type.value)
    if check is not None and check.status == CheckStatus.VERIFIED.value:
        raise Conflict("This check is already verified.", code="ALREADY_VERIFIED")
    if check is None:
        check = ProfessionalVerification(professional_id=profile.id, type=data.type.value, status="PENDING")
        repository.add(session, check)
    check.status = CheckStatus.PENDING.value
    check.file_ids = list(dict.fromkeys(data.file_ids))
    check.note = data.note
    check.submitted_at = now
    check.reviewed_at = None
    check.reviewed_by = None
    check.rejection_reason = None
    await session.flush()
    await _refresh_status(session, profile)
    await audit.record(
        session,
        action="professional.verification_submitted",
        entity_type="professional",
        entity_id=profile.id,
        actor_user_id=caller.user_id,
        data={"type": data.type.value, "documents": len(check.file_ids)},
    )
    await session.commit()
    await session.refresh(profile)
    return await present_private(session, services, profile, caller.user)


async def _admin_rows(
    session: AsyncSession,
    services: Services,
    rows: Sequence[tuple[ProfessionalVerification, ProfessionalProfile, User]],
) -> list[AdminVerificationOut]:
    files = await repository.files_by_id(session, [fid for check, _, _ in rows for fid in check.file_ids])
    return [
        AdminVerificationOut(
            id=check.id,
            professional_id=profile.id,
            professional_name=user.full_name,
            professional_email=user.email,
            type=VerificationType(check.type),
            status=CheckStatus(check.status),
            note=check.note,
            files=[uploads.file_ref(services, files[fid]) for fid in check.file_ids if fid in files],
            submitted_at=check.submitted_at,
            reviewed_at=check.reviewed_at,
            rejection_reason=check.rejection_reason,
        )
        for check, profile, user in rows
    ]


async def list_verifications(
    session: AsyncSession, services: Services, *, status: CheckStatus | None, limit: int, offset: int
) -> tuple[list[AdminVerificationOut], int]:
    rows, total = await repository.list_verifications(
        session, status=status.value if status else None, limit=limit, offset=offset
    )
    return await _admin_rows(session, services, rows), total


async def admin_verification(
    session: AsyncSession, services: Services, verification_id: uuid.UUID
) -> AdminVerificationOut:
    row = await repository.get_verification_with_owner(session, verification_id)
    if row is None:
        raise NotFound("Verification not found.")
    return (await _admin_rows(session, services, [row]))[0]


async def decide_verification(
    session: AsyncSession,
    services: Services,
    admin: AuthContext,
    verification_id: uuid.UUID,
    data: VerificationDecisionIn,
) -> CheckStatus:
    check = await repository.get_verification(session, verification_id, for_update=True)
    if check is None:
        raise NotFound("Verification not found.")
    if check.status != CheckStatus.PENDING.value:
        raise Conflict("Only pending verifications can be decided.", code="VERIFICATION_NOT_PENDING")
    profile = await repository.get(session, check.professional_id, for_update=True)
    assert profile is not None
    if profile.user_id == admin.user_id:
        raise Forbidden("Admins cannot decide their own verification.", code="SELF_REVIEW")
    check.status = data.decision.value
    check.reviewed_by = admin.user_id
    check.reviewed_at = services.clock.now()
    check.rejection_reason = data.reason if data.decision is CheckStatus.REJECTED else None
    await session.flush()
    await _refresh_status(session, profile)
    approved = data.decision is not CheckStatus.REJECTED
    label = check.type.replace("_", " ").lower()
    await notifications.notify(
        session,
        profile.user_id,
        NotificationType.VERIFICATION_APPROVED if approved else NotificationType.VERIFICATION_REJECTED,
        title="Verification approved" if approved else "Verification rejected",
        body=f"Your {label} check was approved."
        if approved
        else f"Your {label} check was rejected: {data.reason or 'see your profile for details'}.",
        href="/profile",
        data={"type": check.type, "decision": check.status},
        now=check.reviewed_at,
    )
    await audit.record(
        session,
        action="admin.verification_decided",
        entity_type="professional",
        entity_id=profile.id,
        actor_user_id=admin.user_id,
        actor_type=ActorType.ADMIN,
        data={"type": check.type, "decision": check.status, "reason": data.reason},
    )
    await session.commit()
    return CheckStatus(check.status)


def require_professional_role(caller: AuthContext) -> None:
    if caller.role is not Role.PROFESSIONAL:
        raise Forbidden("Only professional accounts can do this.", code="ROLE_FORBIDDEN")
