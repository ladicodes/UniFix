from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.calls.models import LIVE_STATUSES, CallSession, CallStatus


def add(session: AsyncSession, call: CallSession) -> None:
    session.add(call)


async def get(session: AsyncSession, call_id: uuid.UUID, *, for_update: bool = False) -> CallSession | None:
    statement = select(CallSession).where(CallSession.id == call_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def live_for(session: AsyncSession, conversation_id: uuid.UUID) -> CallSession | None:
    statement = select(CallSession).where(
        CallSession.conversation_id == conversation_id, CallSession.status.in_(LIVE_STATUSES)
    )
    return (await session.execute(statement.with_for_update())).scalar_one_or_none()


async def expire_unanswered(
    session: AsyncSession, conversation_id: uuid.UUID, ringing_before: datetime
) -> None:
    await session.execute(
        update(CallSession)
        .where(
            CallSession.conversation_id == conversation_id,
            CallSession.status == CallStatus.RINGING.value,
            CallSession.created_at < ringing_before,
        )
        .values(status=CallStatus.MISSED.value, ended_at=ringing_before, end_reason="no_answer")
    )
