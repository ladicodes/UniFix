from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.models import Conversation, ConversationMember, Message, Report, WebSocketTicket


def add(
    session: AsyncSession, *rows: Conversation | ConversationMember | Message | Report | WebSocketTicket
) -> None:
    session.add_all(rows)


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID, *, for_update: bool = False
) -> Conversation | None:
    statement = select(Conversation).where(Conversation.id == conversation_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def find_direct(
    session: AsyncSession, customer_id: uuid.UUID, professional_id: uuid.UUID
) -> Conversation | None:
    statement = select(Conversation).where(
        Conversation.customer_id == customer_id,
        Conversation.professional_id == professional_id,
        Conversation.service_request_id.is_(None),
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def find_for_request(
    session: AsyncSession, service_request_id: uuid.UUID, professional_id: uuid.UUID
) -> Conversation | None:
    statement = select(Conversation).where(
        Conversation.service_request_id == service_request_id, Conversation.professional_id == professional_id
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def members(session: AsyncSession, conversation_id: uuid.UUID) -> Sequence[ConversationMember]:
    statement = select(ConversationMember).where(ConversationMember.conversation_id == conversation_id)
    return (await session.execute(statement)).scalars().all()


async def members_for(
    session: AsyncSession, conversation_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[ConversationMember]]:
    result: dict[uuid.UUID, list[ConversationMember]] = {cid: [] for cid in conversation_ids}
    if not conversation_ids:
        return result
    statement = select(ConversationMember).where(ConversationMember.conversation_id.in_(conversation_ids))
    for member in (await session.execute(statement)).scalars().all():
        result[member.conversation_id].append(member)
    return result


async def get_member(
    session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False
) -> ConversationMember | None:
    statement = select(ConversationMember).where(
        ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == user_id
    )
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[Sequence[Conversation], int]:
    joined = (
        select(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(ConversationMember.user_id == user_id)
    )
    statement = (
        joined.order_by(
            func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(), Conversation.id
        )
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(statement)).scalars().all()
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ConversationMember)
                .where(ConversationMember.user_id == user_id)
            )
        ).scalar_one()
    )
    return rows, total


async def latest_seq(
    session: AsyncSession, conversation_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, uuid.UUID | None]]:
    """Highest message seq per conversation and who sent it (for unread state)."""
    if not conversation_ids:
        return {}
    ranked = (
        select(
            Message.conversation_id,
            Message.seq,
            Message.sender_id,
            func.row_number()
            .over(partition_by=Message.conversation_id, order_by=Message.seq.desc())
            .label("rank"),
        )
        .where(Message.conversation_id.in_(conversation_ids))
        .subquery()
    )
    statement = select(ranked.c.conversation_id, ranked.c.seq, ranked.c.sender_id).where(ranked.c.rank == 1)
    return {row[0]: (int(row[1]), row[2]) for row in (await session.execute(statement)).all()}


async def unread_user_ids(session: AsyncSession, conversation_id: uuid.UUID) -> list[uuid.UUID]:
    """Members with at least one message from someone else (or the system) after their last read."""
    statement = select(ConversationMember.user_id).where(
        ConversationMember.conversation_id == conversation_id,
        select(Message.id)
        .where(
            Message.conversation_id == conversation_id,
            Message.seq > ConversationMember.last_read_seq,
            (Message.sender_id.is_(None)) | (Message.sender_id != ConversationMember.user_id),
        )
        .exists(),
    )
    return list((await session.execute(statement)).scalars().all())


async def unread_for_many(
    session: AsyncSession, conversation_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    result: dict[uuid.UUID, list[uuid.UUID]] = {cid: [] for cid in conversation_ids}
    if not conversation_ids:
        return result
    statement = select(ConversationMember.conversation_id, ConversationMember.user_id).where(
        ConversationMember.conversation_id.in_(conversation_ids),
        select(Message.id)
        .where(
            Message.conversation_id == ConversationMember.conversation_id,
            Message.seq > ConversationMember.last_read_seq,
            (Message.sender_id.is_(None)) | (Message.sender_id != ConversationMember.user_id),
        )
        .exists(),
    )
    for conversation_id, user_id in (await session.execute(statement)).all():
        result[conversation_id].append(user_id)
    return result


async def get_message(session: AsyncSession, message_id: uuid.UUID) -> Message | None:
    return await session.get(Message, message_id)


async def find_by_client_id(
    session: AsyncSession, sender_id: uuid.UUID, client_message_id: uuid.UUID
) -> Message | None:
    statement = select(Message).where(
        Message.sender_id == sender_id, Message.client_message_id == client_message_id
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def history(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    before_seq: int | None,
    after_seq: int | None,
    limit: int,
) -> list[Message]:
    """Messages oldest-first. ``after_seq`` catches up a reconnecting client; ``before_seq`` pages back."""
    statement = select(Message).where(Message.conversation_id == conversation_id)
    if after_seq is not None:
        rows = (
            (
                await session.execute(
                    statement.where(Message.seq > after_seq).order_by(Message.seq.asc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
    if before_seq is not None:
        statement = statement.where(Message.seq < before_seq)
    rows = (await session.execute(statement.order_by(Message.seq.desc()).limit(limit))).scalars().all()
    return list(reversed(rows))


async def has_professional_reply(
    session: AsyncSession, conversation_id: uuid.UUID, professional_user_id: uuid.UUID, before_seq: int
) -> bool:
    statement = select(Message.id).where(
        Message.conversation_id == conversation_id,
        Message.sender_id == professional_user_id,
        Message.seq < before_seq,
    )
    return (await session.execute(statement.limit(1))).first() is not None


async def first_customer_message_at(
    session: AsyncSession, conversation_id: uuid.UUID, customer_id: uuid.UUID
) -> datetime | None:
    statement = (
        select(Message.created_at)
        .where(Message.conversation_id == conversation_id, Message.sender_id == customer_id)
        .order_by(Message.seq.asc())
        .limit(1)
    )
    return await session.scalar(statement)


async def median_response_seconds(session: AsyncSession, professional_id: uuid.UUID) -> float | None:
    statement = select(func.percentile_cont(0.5).within_group(Conversation.first_response_seconds)).where(
        Conversation.professional_id == professional_id, Conversation.first_response_seconds.is_not(None)
    )
    value = await session.scalar(statement)
    return float(value) if value is not None else None


async def attachment_visible_to(session: AsyncSession, file_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    statement = (
        select(Message.id)
        .join(ConversationMember, ConversationMember.conversation_id == Message.conversation_id)
        .where(Message.attachment_file_id == file_id, ConversationMember.user_id == user_id)
        .limit(1)
    )
    return (await session.execute(statement)).first() is not None


async def find_report(
    session: AsyncSession, reporter_id: uuid.UUID, target_type: str, target_id: uuid.UUID
) -> Report | None:
    statement = select(Report).where(
        Report.reporter_id == reporter_id, Report.target_type == target_type, Report.target_id == target_id
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def consume_ticket(session: AsyncSession, token_hash: str, now: datetime) -> WebSocketTicket | None:
    """Atomically mark a ticket used; returns it only if it was unused and unexpired."""
    statement = (
        update(WebSocketTicket)
        .where(
            WebSocketTicket.token_hash == token_hash,
            WebSocketTicket.used_at.is_(None),
            WebSocketTicket.expires_at > now,
        )
        .values(used_at=now)
        .returning(WebSocketTicket)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def prune_tickets(session: AsyncSession, older_than: datetime) -> None:
    await session.execute(delete(WebSocketTicket).where(WebSocketTicket.expires_at < older_than))
