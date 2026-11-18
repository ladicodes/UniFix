"""Verified reviews (D10): the booking's customer, once, within 30 days of a COMPLETED or
RESOLVED booking. Ratings aggregate exactly from source rows in the same transaction."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import Conflict, Forbidden, NotFound
from app.modules.audit import service as audit
from app.modules.auth.context import AuthContext
from app.modules.bookings import service as bookings
from app.modules.bookings.models import Booking, BookingStatus, TimelineActor
from app.modules.chat import service as chat
from app.modules.chat.models import Report, ReportTarget
from app.modules.professionals.models import ProfessionalProfile
from app.modules.reviews.models import CATEGORIES, Review, ReviewStatus
from app.modules.reviews.schemas import (
    ModerateIn,
    ModerationAction,
    RatingsOut,
    ResponseIn,
    ReviewIn,
    ReviewOut,
    ReviewReportIn,
    ReviewResponseOut,
)

REVIEW_WINDOW = timedelta(days=30)
_ELIGIBLE = {BookingStatus.COMPLETED.value, BookingStatus.RESOLVED.value}


def overall(ratings: Sequence[int]) -> Decimal:
    """The mean of the five ratings, to one decimal (half up)."""
    return (Decimal(sum(ratings)) / Decimal(len(ratings))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


async def recompute(session: AsyncSession, professional_id: uuid.UUID) -> None:
    """Aggregates from the published rows (no incremental drift)."""
    await session.flush()
    columns = [func.avg(Review.overall), *(func.avg(getattr(Review, c)) for c in CATEGORIES), func.count()]
    row = (
        await session.execute(
            select(*columns).where(
                Review.professional_id == professional_id, Review.status == ReviewStatus.PUBLISHED.value
            )
        )
    ).one()
    two = Decimal("0.01")

    def avg(value: Decimal | None) -> Decimal:
        return (value or Decimal(0)).quantize(two, rounding=ROUND_HALF_UP)

    values = {"rating_avg": avg(row[0]), "rating_count": int(row[-1])}
    values.update({f"rating_{c}": avg(row[i + 1]) for i, c in enumerate(CATEGORIES)})
    await session.execute(
        update(ProfessionalProfile).where(ProfessionalProfile.id == professional_id).values(**values)
    )


async def _present(session: AsyncSession, reviews: Sequence[Review]) -> list[ReviewOut]:
    customers = await chat.public_users(session, [r.customer_id for r in reviews])
    result = []
    for review in reviews:
        booking = await bookings.booking_row(session, review.booking_id)
        result.append(
            ReviewOut(
                id=review.id,
                booking_id=review.booking_id,
                professional_id=review.professional_id,
                customer_id=review.customer_id,
                customer_name=customers[review.customer_id].name,
                job_title=booking.title,
                ratings=RatingsOut(**{c: getattr(review, c) for c in CATEGORIES}),
                overall=float(review.overall),
                comment=review.comment,
                status=review.status,
                created_at=review.created_at,
                response=ReviewResponseOut(body=review.response_body, created_at=review.response_at)
                if review.response_body and review.response_at
                else None,
            )
        )
    return result


async def _review(session: AsyncSession, review_id: uuid.UUID, *, for_update: bool = False) -> Review:
    statement = select(Review).where(Review.id == review_id)
    if for_update:
        statement = statement.with_for_update()
    review = (await session.execute(statement)).scalar_one_or_none()
    if review is None:
        raise NotFound("Review not found.")
    return review


def _eligible(booking: Booking, now: datetime) -> bool:
    concluded = booking.completed_at
    return booking.status in _ELIGIBLE and concluded is not None and now <= concluded + REVIEW_WINDOW


async def create(
    session: AsyncSession, services: Services, caller: AuthContext, booking_id: uuid.UUID, data: ReviewIn
) -> ReviewOut:
    booking, professional_user_id = await bookings.visible_booking(
        session, services, caller, booking_id, for_update=True
    )
    if caller.user_id != booking.customer_id or caller.user_id == professional_user_id:
        raise Forbidden("Only the booking's customer can review it.", code="ROLE_FORBIDDEN")
    now = services.clock.now()
    if booking.status not in _ELIGIBLE:
        raise Conflict("Reviews open once the booking is completed or resolved.", code="REVIEW_NOT_ELIGIBLE")
    if not _eligible(booking, now):
        raise Conflict("The 30-day review window has closed.", code="REVIEW_WINDOW_CLOSED")
    ratings = data.ratings.model_dump()
    review = Review(
        booking_id=booking.id,
        customer_id=caller.user_id,
        professional_id=booking.professional_id,
        overall=overall(list(ratings.values())),
        comment=data.comment,
        status=ReviewStatus.PUBLISHED.value,
        **ratings,
    )
    session.add(review)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_reviews_booking_id":
            raise Conflict("This booking has already been reviewed.", code="REVIEW_EXISTS") from exc
        raise
    await recompute(session, booking.professional_id)
    await bookings.add_timeline_note(
        session, booking, label="Customer left a review", actor=TimelineActor.CUSTOMER,
        actor_user_id=caller.user_id, now=now, data={"overall": str(review.overall)},
    )  # fmt: skip
    await audit.record(
        session, action="review.created", entity_type="review", entity_id=review.id,
        actor_user_id=caller.user_id, data={"booking_id": str(booking.id), "overall": str(review.overall)},
    )  # fmt: skip
    await session.commit()
    return (await _present(session, [review]))[0]


async def list_published(
    session: AsyncSession, professional_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[ReviewOut], int]:
    where = (Review.professional_id == professional_id, Review.status == ReviewStatus.PUBLISHED.value)
    total = int((await session.execute(select(func.count()).select_from(Review).where(*where))).scalar_one())
    rows = (
        (
            await session.execute(
                select(Review)
                .where(*where)
                .order_by(Review.created_at.desc(), Review.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return await _present(session, rows), total


async def respond(
    session: AsyncSession, services: Services, caller: AuthContext, review_id: uuid.UUID, data: ResponseIn
) -> ReviewOut:
    review = await _review(session, review_id, for_update=True)
    profile = (
        await session.execute(
            select(ProfessionalProfile).where(ProfessionalProfile.id == review.professional_id)
        )
    ).scalar_one()
    if profile.user_id != caller.user_id:
        raise Forbidden("Only the reviewed professional can respond.", code="ROLE_FORBIDDEN")
    if review.response_body is not None:
        raise Conflict("You have already responded to this review.", code="RESPONSE_EXISTS")
    if review.status != ReviewStatus.PUBLISHED.value:
        raise Conflict("This review is not published.", code="REVIEW_NOT_PUBLISHED")
    review.response_body, review.response_at = data.body, services.clock.now()
    await audit.record(
        session, action="review.responded", entity_type="review", entity_id=review.id,
        actor_user_id=caller.user_id,
    )  # fmt: skip
    await session.commit()
    return (await _present(session, [review]))[0]


async def report(
    session: AsyncSession, caller: AuthContext, review_id: uuid.UUID, data: ReviewReportIn
) -> Report:
    review = await _review(session, review_id)
    if review.status != ReviewStatus.PUBLISHED.value:
        raise NotFound("Review not found.")
    return await chat.create_report(
        session, caller, target_type=ReportTarget.REVIEW, target_id=review.id, conversation_id=None,
        reason=data.reason, details=data.details,
    )  # fmt: skip


async def moderate(
    session: AsyncSession, services: Services, admin: AuthContext, review_id: uuid.UUID, data: ModerateIn
) -> ReviewOut:
    review = await _review(session, review_id, for_update=True)
    if review.status == ReviewStatus.REMOVED.value:
        raise Conflict("Removed reviews are final.", code="REVIEW_REMOVED")
    target = {
        ModerationAction.HIDE: ReviewStatus.HIDDEN,
        ModerationAction.RESTORE: ReviewStatus.PUBLISHED,
        ModerationAction.REMOVE: ReviewStatus.REMOVED,
    }[data.action]
    previous = review.status
    review.status, review.moderated_by, review.moderation_reason = target.value, admin.user_id, data.reason
    await recompute(session, review.professional_id)
    await audit.record(
        session, action=f"review.{data.action.value.lower()}", entity_type="review", entity_id=review.id,
        actor_user_id=admin.user_id, data={"from": previous, "to": target.value, "reason": data.reason},
    )  # fmt: skip
    await session.commit()
    return (await _present(session, [review]))[0]


async def bundle_extension(
    session: AsyncSession, booking: Booking, actor: TimelineActor | None, now: datetime
) -> tuple[ReviewOut | None, list[str]]:
    review = (
        await session.execute(select(Review).where(Review.booking_id == booking.id))
    ).scalar_one_or_none()
    actions = (
        ["REVIEW"] if actor is TimelineActor.CUSTOMER and review is None and _eligible(booking, now) else []
    )
    return ((await _present(session, [review]))[0] if review else None), actions
