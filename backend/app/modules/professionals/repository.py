from __future__ import annotations

import typing
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Float, cast, delete, exists, func, insert, literal, null, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.campuses.models import Campus
from app.modules.catalog.models import ServiceCategory
from app.modules.professionals.models import (
    PortfolioItem,
    ProfessionalProfile,
    ProfessionalVerification,
    SortOrder,
    professional_campuses,
    professional_categories,
)
from app.modules.uploads.models import StoredFile
from app.modules.users.models import AccountStatus, User

EARTH_RADIUS_KM = 6371.0
# Bayesian prior for the BEST sort: a professional with few reviews is pulled toward 3.0.
_PRIOR_REVIEWS = 5
_PRIOR_MEAN = 3.0


@dataclass(frozen=True, slots=True)
class SearchFilters:
    q: str | None = None
    category_ids: Sequence[uuid.UUID] | None = None
    campus_id: uuid.UUID | None = None
    city: str | None = None
    availability: Sequence[str] | None = None
    min_rating: float | None = None
    verified_only: bool = False
    sort: SortOrder = SortOrder.BEST
    reference: tuple[float, float] | None = None  # (lat, lng)
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SearchRow:
    profile: ProfessionalProfile
    user: User
    distance_km: float | None


def cast_uuid(value: object) -> uuid.UUID:
    """Association-table columns are untyped in SQLAlchemy's stubs; their values are UUIDs."""
    return typing.cast(uuid.UUID, value)


def _haversine(
    lat1: float, lng1: float, lat2: ColumnElement[float], lng2: ColumnElement[float]
) -> ColumnElement[float]:
    dlat = func.radians(lat2 - lat1) / 2
    dlng = func.radians(lng2 - lng1) / 2
    a = func.power(func.sin(dlat), 2) + func.cos(func.radians(literal(lat1))) * func.cos(
        func.radians(lat2)
    ) * func.power(func.sin(dlng), 2)
    return 2 * EARTH_RADIUS_KM * func.asin(func.sqrt(a))


def _distance(reference: tuple[float, float]) -> ColumnElement[float]:
    """Profile point if set, otherwise the nearest served campus centroid."""
    lat, lng = reference
    own = _haversine(
        lat, lng, cast(ProfessionalProfile.latitude, Float), cast(ProfessionalProfile.longitude, Float)
    )
    nearest_campus = (
        select(func.min(_haversine(lat, lng, cast(Campus.latitude, Float), cast(Campus.longitude, Float))))
        .select_from(professional_campuses.join(Campus, Campus.id == professional_campuses.c.campus_id))
        .where(
            professional_campuses.c.professional_id == ProfessionalProfile.id, Campus.latitude.is_not(None)
        )
        .scalar_subquery()
    )
    return func.coalesce(own, nearest_campus)


def _visible() -> list[ColumnElement[bool]]:
    return [ProfessionalProfile.is_listed.is_(True), User.status == AccountStatus.ACTIVE.value]


def _filters(filters: SearchFilters) -> list[ColumnElement[bool]]:
    conditions = _visible()
    if filters.q:
        query = func.websearch_to_tsquery("simple", filters.q)
        conditions.append(
            or_(ProfessionalProfile.search_vector.op("@@")(query), User.full_name.ilike(f"%{filters.q}%"))
        )
    if filters.category_ids is not None:
        conditions.append(
            or_(
                ProfessionalProfile.primary_category_id.in_(filters.category_ids),
                exists().where(
                    professional_categories.c.professional_id == ProfessionalProfile.id,
                    professional_categories.c.category_id.in_(filters.category_ids),
                ),
            )
        )
    if filters.campus_id is not None:
        conditions.append(
            exists().where(
                professional_campuses.c.professional_id == ProfessionalProfile.id,
                professional_campuses.c.campus_id == filters.campus_id,
            )
        )
    if filters.city:
        conditions.append(func.lower(ProfessionalProfile.city) == filters.city.lower())
    if filters.availability:
        conditions.append(ProfessionalProfile.availability.in_(filters.availability))
    if filters.min_rating is not None:
        conditions.append(ProfessionalProfile.rating_avg >= filters.min_rating)
    if filters.verified_only:
        conditions.append(ProfessionalProfile.verification_status == "VERIFIED")
    return conditions


async def search(session: AsyncSession, filters: SearchFilters) -> tuple[list[SearchRow], int]:
    conditions = _filters(filters)
    base = (
        select(ProfessionalProfile, User)
        .join(User, User.id == ProfessionalProfile.user_id)
        .where(*conditions)
    )
    distance = _distance(filters.reference) if filters.reference else cast(null(), Float)
    bayesian = (
        ProfessionalProfile.rating_count * ProfessionalProfile.rating_avg + _PRIOR_REVIEWS * _PRIOR_MEAN
    ) / (ProfessionalProfile.rating_count + _PRIOR_REVIEWS)
    order = {
        SortOrder.BEST: [bayesian.desc(), ProfessionalProfile.completed_jobs.desc()],
        SortOrder.MOST_JOBS: [ProfessionalProfile.completed_jobs.desc(), bayesian.desc()],
        SortOrder.EXPERIENCE: [ProfessionalProfile.years_experience.desc(), bayesian.desc()],
        SortOrder.NEAREST: (
            [distance.asc().nulls_last(), bayesian.desc()] if filters.reference else [bayesian.desc()]
        ),
    }[filters.sort]
    statement = (
        base.add_columns(distance.label("distance_km"))
        .order_by(*order, ProfessionalProfile.created_at.asc(), ProfessionalProfile.id)
        .limit(filters.limit)
        .offset(filters.offset)
    )
    rows = [
        SearchRow(profile=row[0], user=row[1], distance_km=round(row[2], 1) if row[2] is not None else None)
        for row in (await session.execute(statement)).all()
    ]
    count_statement = (
        select(func.count())
        .select_from(ProfessionalProfile)
        .join(User, User.id == ProfessionalProfile.user_id)
        .where(*conditions)
    )
    total = int((await session.execute(count_statement)).scalar_one())
    return rows, total


async def distance_to(
    session: AsyncSession, professional_id: uuid.UUID, reference: tuple[float, float]
) -> float | None:
    value = await session.scalar(
        select(_distance(reference)).where(ProfessionalProfile.id == professional_id)
    )
    return round(float(value), 1) if value is not None else None


async def get(
    session: AsyncSession, professional_id: uuid.UUID, *, for_update: bool = False
) -> ProfessionalProfile | None:
    statement = select(ProfessionalProfile).where(ProfessionalProfile.id == professional_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def get_with_user(
    session: AsyncSession, professional_id: uuid.UUID
) -> tuple[ProfessionalProfile, User] | None:
    statement = (
        select(ProfessionalProfile, User)
        .join(User, User.id == ProfessionalProfile.user_id)
        .where(ProfessionalProfile.id == professional_id)
    )
    row = (await session.execute(statement)).first()
    return (row[0], row[1]) if row else None


async def get_by_user(
    session: AsyncSession, user_id: uuid.UUID, *, for_update: bool = False
) -> ProfessionalProfile | None:
    statement = select(ProfessionalProfile).where(ProfessionalProfile.user_id == user_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def id_for_user(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(select(ProfessionalProfile.id).where(ProfessionalProfile.user_id == user_id))


def add(session: AsyncSession, row: ProfessionalProfile | ProfessionalVerification | PortfolioItem) -> None:
    session.add(row)


async def replace_categories(
    session: AsyncSession, professional_id: uuid.UUID, category_ids: Sequence[uuid.UUID]
) -> None:
    await session.execute(
        delete(professional_categories).where(professional_categories.c.professional_id == professional_id)
    )
    if category_ids:
        await session.execute(
            insert(professional_categories),
            [{"professional_id": professional_id, "category_id": cid} for cid in category_ids],
        )


async def replace_campuses(
    session: AsyncSession, professional_id: uuid.UUID, campus_ids: Sequence[uuid.UUID]
) -> None:
    await session.execute(
        delete(professional_campuses).where(professional_campuses.c.professional_id == professional_id)
    )
    if campus_ids:
        await session.execute(
            insert(professional_campuses),
            [{"professional_id": professional_id, "campus_id": cid} for cid in campus_ids],
        )


async def category_slugs(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    result: dict[uuid.UUID, list[str]] = defaultdict(list)
    if not ids:
        return result
    statement = (
        select(professional_categories.c.professional_id, ServiceCategory.slug)
        .join(ServiceCategory, ServiceCategory.id == professional_categories.c.category_id)
        .where(professional_categories.c.professional_id.in_(ids))
        .order_by(ServiceCategory.sort_order, ServiceCategory.slug)
    )
    for professional_id, slug in (await session.execute(statement)).all():
        result[cast_uuid(professional_id)].append(str(slug))
    return result


async def campuses_for(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[Campus]]:
    result: dict[uuid.UUID, list[Campus]] = defaultdict(list)
    if not ids:
        return result
    statement = (
        select(professional_campuses.c.professional_id, Campus)
        .join(Campus, Campus.id == professional_campuses.c.campus_id)
        .where(professional_campuses.c.professional_id.in_(ids))
        .order_by(Campus.name)
    )
    for professional_id, campus in (await session.execute(statement)).all():
        result[cast_uuid(professional_id)].append(typing.cast(Campus, campus))
    return result


async def portfolio_for(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[PortfolioItem]]:
    result: dict[uuid.UUID, list[PortfolioItem]] = defaultdict(list)
    if not ids:
        return result
    statement = (
        select(PortfolioItem)
        .join(StoredFile, StoredFile.id == PortfolioItem.image_file_id)
        .where(PortfolioItem.professional_id.in_(ids), StoredFile.deleted_at.is_(None))
        .order_by(PortfolioItem.sort_order, PortfolioItem.created_at)
    )
    for item in (await session.execute(statement)).scalars().all():
        result[item.professional_id].append(item)
    return result


async def verifications_for(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[ProfessionalVerification]]:
    result: dict[uuid.UUID, list[ProfessionalVerification]] = defaultdict(list)
    if not ids:
        return result
    statement = select(ProfessionalVerification).where(ProfessionalVerification.professional_id.in_(ids))
    for row in (await session.execute(statement)).scalars().all():
        result[row.professional_id].append(row)
    return result


async def count_portfolio(session: AsyncSession, professional_id: uuid.UUID) -> int:
    statement = select(func.count()).where(PortfolioItem.professional_id == professional_id)
    return int((await session.execute(statement)).scalar_one())


async def get_portfolio_item(
    session: AsyncSession, item_id: uuid.UUID, professional_id: uuid.UUID
) -> PortfolioItem | None:
    statement = select(PortfolioItem).where(
        PortfolioItem.id == item_id, PortfolioItem.professional_id == professional_id
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def delete_portfolio_item(session: AsyncSession, item: PortfolioItem) -> None:
    await session.delete(item)


async def get_verification(
    session: AsyncSession, verification_id: uuid.UUID, *, for_update: bool = False
) -> ProfessionalVerification | None:
    statement = select(ProfessionalVerification).where(ProfessionalVerification.id == verification_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def get_verification_by_type(
    session: AsyncSession, professional_id: uuid.UUID, verification_type: str
) -> ProfessionalVerification | None:
    statement = (
        select(ProfessionalVerification)
        .where(
            ProfessionalVerification.professional_id == professional_id,
            ProfessionalVerification.type == verification_type,
        )
        .with_for_update()
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def get_verification_with_owner(
    session: AsyncSession, verification_id: uuid.UUID
) -> tuple[ProfessionalVerification, ProfessionalProfile, User] | None:
    statement = (
        select(ProfessionalVerification, ProfessionalProfile, User)
        .join(ProfessionalProfile, ProfessionalProfile.id == ProfessionalVerification.professional_id)
        .join(User, User.id == ProfessionalProfile.user_id)
        .where(ProfessionalVerification.id == verification_id)
    )
    row = (await session.execute(statement)).first()
    return (row[0], row[1], row[2]) if row else None


async def list_verifications(
    session: AsyncSession, *, status: str | None, limit: int, offset: int
) -> tuple[list[tuple[ProfessionalVerification, ProfessionalProfile, User]], int]:
    conditions = [ProfessionalVerification.status == status] if status else []
    statement = (
        select(ProfessionalVerification, ProfessionalProfile, User)
        .join(ProfessionalProfile, ProfessionalProfile.id == ProfessionalVerification.professional_id)
        .join(User, User.id == ProfessionalProfile.user_id)
        .where(*conditions)
        .order_by(ProfessionalVerification.submitted_at.asc(), ProfessionalVerification.id)
        .limit(limit)
        .offset(offset)
    )
    rows = [(row[0], row[1], row[2]) for row in (await session.execute(statement)).all()]
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(ProfessionalVerification).where(*conditions)
            )
        ).scalar_one()
    )
    return rows, total


async def files_by_id(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, StoredFile]:
    if not ids:
        return {}
    statement = select(StoredFile).where(StoredFile.id.in_(ids))
    return {file.id: file for file in (await session.execute(statement)).scalars().all()}
