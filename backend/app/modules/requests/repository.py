from __future__ import annotations

import typing
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, exists, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.models import Conversation
from app.modules.requests.models import RequestStatus, ServiceRequest, service_request_media


def add(session: AsyncSession, row: ServiceRequest) -> None:
    session.add(row)


async def get(
    session: AsyncSession, request_id: uuid.UUID, *, for_update: bool = False
) -> ServiceRequest | None:
    statement = select(ServiceRequest).where(ServiceRequest.id == request_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def set_media(session: AsyncSession, request_id: uuid.UUID, file_ids: Sequence[uuid.UUID]) -> None:
    await session.execute(
        delete(service_request_media).where(service_request_media.c.request_id == request_id)
    )
    if file_ids:
        await session.execute(
            insert(service_request_media),
            [{"request_id": request_id, "file_id": fid, "sort_order": i} for i, fid in enumerate(file_ids)],
        )


async def media_for(
    session: AsyncSession, request_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    result: dict[uuid.UUID, list[uuid.UUID]] = {rid: [] for rid in request_ids}
    if not request_ids:
        return result
    statement = (
        select(service_request_media.c.request_id, service_request_media.c.file_id)
        .where(service_request_media.c.request_id.in_(request_ids))
        .order_by(service_request_media.c.sort_order)
    )
    for request_id, file_id in (await session.execute(statement)).all():
        result[typing.cast(uuid.UUID, request_id)].append(typing.cast(uuid.UUID, file_id))
    return result


async def requests_for_file(session: AsyncSession, file_id: uuid.UUID) -> Sequence[ServiceRequest]:
    statement = (
        select(ServiceRequest)
        .join(service_request_media, service_request_media.c.request_id == ServiceRequest.id)
        .where(service_request_media.c.file_id == file_id)
    )
    return (await session.execute(statement)).scalars().all()


async def list_for_customer(
    session: AsyncSession, customer_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[Sequence[ServiceRequest], int]:
    condition = ServiceRequest.customer_id == customer_id
    rows = (
        (
            await session.execute(
                select(ServiceRequest)
                .where(condition)
                .order_by(ServiceRequest.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    total = int((await session.execute(select(func.count()).where(condition))).scalar_one())
    return rows, total


async def feed(
    session: AsyncSession,
    *,
    professional_id: uuid.UUID,
    category_ids: Sequence[uuid.UUID],
    campus_ids: Sequence[uuid.UUID],
    now: datetime,
    limit: int,
    offset: int,
) -> tuple[Sequence[ServiceRequest], int]:
    """Open, unexpired requests in the professional's categories; campus requests need a campus match."""
    conditions = [
        ServiceRequest.status == RequestStatus.OPEN.value,
        ServiceRequest.expires_at > now,
        ServiceRequest.category_id.in_(category_ids),
        or_(ServiceRequest.campus_id.is_(None), ServiceRequest.campus_id.in_(campus_ids)),
        or_(
            ServiceRequest.target_professional_id.is_(None),
            ServiceRequest.target_professional_id == professional_id,
        ),
    ]
    rows = (
        (
            await session.execute(
                select(ServiceRequest)
                .where(*conditions)
                .order_by(ServiceRequest.created_at.desc(), ServiceRequest.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    total = int(
        (
            await session.execute(select(func.count()).select_from(ServiceRequest).where(*conditions))
        ).scalar_one()
    )
    return rows, total


async def responded(
    session: AsyncSession, professional_id: uuid.UUID, request_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    if not request_ids:
        return set()
    statement = select(Conversation.service_request_id).where(
        Conversation.professional_id == professional_id, Conversation.service_request_id.in_(request_ids)
    )
    return {rid for rid in (await session.execute(statement)).scalars().all() if rid is not None}


async def conversation_ids(session: AsyncSession, request_id: uuid.UUID) -> list[uuid.UUID]:
    statement = (
        select(Conversation.id)
        .where(Conversation.service_request_id == request_id)
        .order_by(Conversation.created_at)
    )
    return list((await session.execute(statement)).scalars().all())


async def has_responded(session: AsyncSession, professional_id: uuid.UUID, request_id: uuid.UUID) -> bool:
    statement = select(
        exists().where(
            Conversation.professional_id == professional_id, Conversation.service_request_id == request_id
        )
    )
    return bool((await session.execute(statement)).scalar())
