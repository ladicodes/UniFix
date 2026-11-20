"""Conversations and messages.

Write path: persist in PostgreSQL, commit, then publish to the hub. A message never exists
only in memory. Sends lock the conversation row, so within one conversation the ``seq``
order equals commit order and reconnecting clients can safely catch up with ``after=``.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.ratelimit import rate_limit_key
from app.core.security import hash_token, new_opaque_token
from app.modules.audit import service as audit
from app.modules.auth.context import AuthContext
from app.modules.campuses import service as campuses
from app.modules.campuses.schemas import CampusOut
from app.modules.chat import repository
from app.modules.chat.hub import ConversationHub
from app.modules.chat.models import (
    Conversation,
    ConversationMember,
    MemberRole,
    Message,
    MessageKind,
    Report,
    ReportTarget,
    TicketScope,
    WebSocketTicket,
)
from app.modules.chat.schemas import (
    ConversationDetail,
    ConversationOut,
    ConversationSummary,
    MessageOut,
    PublicUser,
    ReportIn,
    SendMessageIn,
)
from app.modules.notifications import service as notifications
from app.modules.professionals import repository as professionals_repository
from app.modules.professionals import service as professionals
from app.modules.professionals.repository import SearchRow
from app.modules.uploads import repository as uploads_repository
from app.modules.uploads import service as uploads
from app.modules.uploads.models import FilePurpose
from app.modules.users import repository as users_repository
from app.modules.users.models import Role

# Later workflows (quotes, bookings) attach data to conversations through these hooks, which
# app.api.v1 registers explicitly. Chat never imports those modules (keeps the graph acyclic).
BookingLookup = Callable[[AsyncSession, Sequence[uuid.UUID]], Awaitable[dict[uuid.UUID, uuid.UUID]]]
QuotesLookup = Callable[[AsyncSession, uuid.UUID], Awaitable[list[dict[str, Any]]]]
_hooks: dict[str, Any] = {}


def register_booking_lookup(lookup: BookingLookup) -> None:
    _hooks["bookings"] = lookup


def register_quotes_lookup(lookup: QuotesLookup) -> None:
    _hooks["quotes"] = lookup


async def _active_bookings(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    lookup: BookingLookup | None = _hooks.get("bookings")
    return await lookup(session, ids) if lookup else {}


async def _quotes(session: AsyncSession, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    lookup: QuotesLookup | None = _hooks.get("quotes")
    return await lookup(session, conversation_id) if lookup else []


TICKET_TTL = timedelta(seconds=30)
PREVIEW_LENGTH = 140
MESSAGE_RATE_PER_MINUTE = 60


# ---------------------------------------------------------------- access


async def require_member(
    session: AsyncSession, caller: AuthContext, conversation_id: uuid.UUID, *, for_update: bool = False
) -> tuple[Conversation, ConversationMember]:
    """The conversation if the caller participates in it; otherwise 404 (no existence leak)."""
    conversation = await repository.get_conversation(session, conversation_id, for_update=for_update)
    member = await repository.get_member(session, conversation_id, caller.user_id) if conversation else None
    if conversation is None or member is None:
        raise NotFound("Conversation not found.")
    return conversation, member


async def lock_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conversation = await repository.get_conversation(session, conversation_id, for_update=True)
    if conversation is None:
        raise NotFound("Conversation not found.")
    return conversation


async def is_member(session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return await repository.get_member(session, conversation_id, user_id) is not None


async def can_read_attachment(session: AsyncSession, caller: AuthContext, file: object) -> bool:
    """Upload read rule: conversation members may read message attachments."""
    file_id = getattr(file, "id", None)
    return file_id is not None and await repository.attachment_visible_to(session, file_id, caller.user_id)


# ---------------------------------------------------------------- conversations


async def create_conversation(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    professional_id: uuid.UUID,
    professional_user_id: uuid.UUID,
    service_request_id: uuid.UUID | None = None,
) -> Conversation:
    """Insert a conversation and its two members (no commit)."""
    conversation = Conversation(
        id=uuid.uuid4(),
        customer_id=customer_id,
        professional_id=professional_id,
        service_request_id=service_request_id,
    )
    repository.add(session, conversation)
    await session.flush()
    repository.add(
        session,
        ConversationMember(
            conversation_id=conversation.id, user_id=customer_id, role=MemberRole.CUSTOMER.value
        ),
        ConversationMember(
            conversation_id=conversation.id, user_id=professional_user_id, role=MemberRole.PROFESSIONAL.value
        ),
    )
    await session.flush()
    return conversation


async def open_conversation(
    session: AsyncSession, caller: AuthContext, professional_id: uuid.UUID
) -> tuple[Conversation, bool]:
    """The caller's direct thread with a professional, created if needed. Returns (conversation, created)."""
    if caller.role is not Role.CUSTOMER:
        raise Forbidden("Only customers can start a conversation with a professional.", code="ROLE_FORBIDDEN")
    found = await professionals_repository.get_with_user(session, professional_id)
    if found is None or not found[0].is_listed or not found[1].is_active:
        raise NotFound("Professional not found.")
    profile, professional_user = found
    if professional_user.id == caller.user_id:
        raise BadRequest("You cannot message yourself.", code="SELF_CONVERSATION")
    existing = await repository.find_direct(session, caller.user_id, profile.id)
    if existing is not None:
        return existing, False
    try:
        conversation = await create_conversation(
            session,
            customer_id=caller.user_id,
            professional_id=profile.id,
            professional_user_id=professional_user.id,
        )
        await audit.record(
            session,
            action="chat.conversation_opened",
            entity_type="conversation",
            entity_id=conversation.id,
            actor_user_id=caller.user_id,
        )
        await session.commit()
    except IntegrityError as exc:  # a concurrent request created it first
        await session.rollback()
        if violated_constraint(exc) != "uq_conversations_direct":
            raise
        existing = await repository.find_direct(session, caller.user_id, profile.id)
        assert existing is not None
        return existing, False
    return conversation, True


# ---------------------------------------------------------------- presentation


async def public_users(session: AsyncSession, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, PublicUser]:
    users = {user_id: await users_repository.get(session, user_id) for user_id in dict.fromkeys(user_ids)}
    result: dict[uuid.UUID, PublicUser] = {}
    for user_id, user in users.items():
        if user is None:
            continue
        campus = await campuses.get_active(session, user.campus_id) if user.campus_id else None
        avatar = await uploads_repository.get(session, user.avatar_file_id) if user.avatar_file_id else None
        result[user_id] = PublicUser(
            id=user.id,
            name=user.full_name,
            avatar_url=uploads.public_url(avatar),
            city=user.city,
            campus=CampusOut.model_validate(campus) if campus else None,
        )
    return result


async def unread_for(session: AsyncSession, conversation_id: uuid.UUID) -> list[uuid.UUID]:
    return await repository.unread_user_ids(session, conversation_id)


def conversation_out(
    conversation: Conversation, unread_for: list[uuid.UUID], booking_id: uuid.UUID | None = None
) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        customer_id=conversation.customer_id,
        professional_id=conversation.professional_id,
        service_request_id=conversation.service_request_id,
        booking_id=booking_id,
        last_message_at=conversation.last_message_at,
        last_message_preview=conversation.last_message_preview,
        unread_for=unread_for,
        created_at=conversation.created_at,
    )


async def messages_out(
    session: AsyncSession,
    services: Services,
    messages: Sequence[Message],
    members: Sequence[ConversationMember],
) -> list[MessageOut]:
    files = {
        file.id: file
        for file in await uploads_repository.get_many(
            session, [m.attachment_file_id for m in messages if m.attachment_file_id]
        )
    }
    result = []
    for message in messages:
        # 1:1 read receipt: read once the *other* participant's read pointer has passed it.
        others = [m for m in members if m.user_id != message.sender_id]
        read_at = None
        if message.sender_id is not None and others and others[0].last_read_seq >= message.seq:
            read_at = others[0].last_read_at
        attachment = files.get(message.attachment_file_id) if message.attachment_file_id else None
        result.append(
            MessageOut(
                id=message.id,
                conversation_id=message.conversation_id,
                sender_id=message.sender_id,
                kind=MessageKind(message.kind),
                body=message.body,
                quote_id=message.quote_id,
                attachment=uploads.file_ref(services, attachment) if attachment else None,
                created_at=message.created_at,
                read_at=read_at,
            )
        )
    return result


async def summaries(
    session: AsyncSession, caller: AuthContext, conversations: Sequence[Conversation]
) -> list[ConversationSummary]:
    ids = [c.id for c in conversations]
    unread = await repository.unread_for_many(session, ids)
    bookings = await _active_bookings(session, ids)
    rows: list[SearchRow] = []
    for conversation in conversations:
        found = await professionals_repository.get_with_user(session, conversation.professional_id)
        assert found is not None
        rows.append(SearchRow(profile=found[0], user=found[1], distance_km=None))
    profiles = {item.id: item for item in await professionals.present_many(session, rows)}
    customers = await public_users(session, [c.customer_id for c in conversations])
    return [
        ConversationSummary(
            conversation=conversation_out(
                conversation, unread[conversation.id], bookings.get(conversation.id)
            ),
            professional=profiles[conversation.professional_id],
            customer=customers[conversation.customer_id],
            unread=caller.user_id in unread[conversation.id],
        )
        for conversation in conversations
    ]


async def list_conversations(
    session: AsyncSession, caller: AuthContext, *, limit: int, offset: int
) -> tuple[list[ConversationSummary], int]:
    conversations, total = await repository.list_for_user(session, caller.user_id, limit=limit, offset=offset)
    return await summaries(session, caller, conversations), total


async def detail(
    session: AsyncSession,
    services: Services,
    caller: AuthContext,
    conversation_id: uuid.UUID,
    *,
    messages_limit: int,
) -> ConversationDetail:
    conversation, _ = await require_member(session, caller, conversation_id)
    summary = (await summaries(session, caller, [conversation]))[0]
    members = await repository.members(session, conversation_id)
    history = await repository.history(
        session, conversation_id, before_seq=None, after_seq=None, limit=messages_limit
    )
    return ConversationDetail(
        **summary.model_dump(),
        messages=await messages_out(session, services, history, members),
        quotes=await _quotes(session, conversation_id),
    )


async def history(
    session: AsyncSession,
    services: Services,
    caller: AuthContext,
    conversation_id: uuid.UUID,
    *,
    before: uuid.UUID | None,
    after: uuid.UUID | None,
    limit: int,
) -> list[MessageOut]:
    await require_member(session, caller, conversation_id)
    before_seq = await _seq_of(session, conversation_id, before)
    after_seq = await _seq_of(session, conversation_id, after)
    messages = await repository.history(
        session, conversation_id, before_seq=before_seq, after_seq=after_seq, limit=limit
    )
    return await messages_out(session, services, messages, await repository.members(session, conversation_id))


async def _seq_of(
    session: AsyncSession, conversation_id: uuid.UUID, message_id: uuid.UUID | None
) -> int | None:
    if message_id is None:
        return None
    message = await repository.get_message(session, message_id)
    if message is None or message.conversation_id != conversation_id:
        raise BadRequest("Unknown message cursor.", code="INVALID_CURSOR")
    return message.seq


# ---------------------------------------------------------------- messages


def _preview(message: Message) -> str:
    if message.kind == MessageKind.IMAGE.value and not message.body:
        return "📷 Photo"
    return message.body[:PREVIEW_LENGTH]


def _touch(conversation: Conversation, message: Message) -> None:
    conversation.last_message_at = message.created_at
    conversation.last_message_preview = _preview(message)


async def _record_response_time(
    session: AsyncSession, conversation: Conversation, sender: AuthContext, message: Message
) -> None:
    """When a professional replies for the first time, update their median response time."""
    if sender.role is not Role.PROFESSIONAL or conversation.first_response_seconds is not None:
        return
    if await repository.has_professional_reply(session, conversation.id, sender.user_id, message.seq):
        return
    first_customer = await repository.first_customer_message_at(
        session, conversation.id, conversation.customer_id
    )
    if first_customer is None:
        return
    conversation.first_response_seconds = max(0, int((message.created_at - first_customer).total_seconds()))
    await session.flush()
    median = await repository.median_response_seconds(session, conversation.professional_id)
    profile = await professionals_repository.get(session, conversation.professional_id, for_update=True)
    if profile is not None and median is not None:
        profile.response_minutes = max(1, math.ceil(median / 60))


async def send_message(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    conversation_id: uuid.UUID,
    data: SendMessageIn,
) -> tuple[MessageOut, bool]:
    """Persist, commit, then publish. Returns (message, created); resent client ids are not duplicated."""
    now = services.clock.now()
    await services.rate_limiter.hit(
        bucket="chat_messages",
        key=rate_limit_key(str(caller.user_id)),
        limit=MESSAGE_RATE_PER_MINUTE,
        window=timedelta(minutes=1),
        now=now,
    )
    conversation, member = await require_member(session, caller, conversation_id, for_update=True)
    if data.client_message_id is not None:
        existing = await repository.find_by_client_id(session, caller.user_id, data.client_message_id)
        if existing is not None:
            if existing.conversation_id != conversation_id:
                raise Conflict(
                    "client_message_id was already used in another conversation.", code="CLIENT_ID_REUSED"
                )
            members = await repository.members(session, conversation_id)
            return (await messages_out(session, services, [existing], members))[0], False
    if data.attachment_file_id is not None:
        await uploads.require_owned(
            session, caller, [data.attachment_file_id], FilePurpose.MESSAGE_ATTACHMENT
        )
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        sender_id=caller.user_id,
        kind=(MessageKind.IMAGE if data.attachment_file_id else MessageKind.TEXT).value,
        body=data.body,
        attachment_file_id=data.attachment_file_id,
        client_message_id=data.client_message_id,
        created_at=now,
    )
    repository.add(session, message)
    await session.flush()
    _touch(conversation, message)
    # Your own message counts as read by you.
    member.last_read_seq = message.seq
    member.last_read_message_id = message.id
    member.last_read_at = now
    await _record_response_time(session, conversation, caller, message)
    members = await repository.members(session, conversation_id)
    await notifications.notify_message(
        session,
        [m.user_id for m in members if m.user_id != caller.user_id],
        conversation_id=conversation_id,
        sender_name=caller.user.full_name,
        preview=_preview(message),
        now=now,
    )
    await session.commit()
    out = (await messages_out(session, services, [message], members))[0]
    await hub.publish(
        conversation_id,
        {
            "type": "MESSAGE_CREATED",
            "conversation_id": str(conversation_id),
            "data": out.model_dump(mode="json"),
        },
    )
    return out, True


async def insert_message(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    sender: AuthContext | None,
    body: str,
    kind: MessageKind,
    now: datetime,
    quote_id: uuid.UUID | None = None,
) -> Message:
    """Append a message inside the caller's transaction (no commit). The caller publishes after commit."""
    conversation = await repository.get_conversation(session, conversation_id, for_update=True)
    if conversation is None:
        raise NotFound("Conversation not found.")
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        sender_id=sender.user_id if sender else None,
        kind=kind.value,
        body=body,
        quote_id=quote_id,
        created_at=now,
    )
    repository.add(session, message)
    await session.flush()
    _touch(conversation, message)
    if sender is not None:
        member = await repository.get_member(session, conversation_id, sender.user_id, for_update=True)
        if member is not None:
            member.last_read_seq, member.last_read_message_id, member.last_read_at = (
                message.seq,
                message.id,
                now,
            )
        await _record_response_time(session, conversation, sender, message)
    return message


async def publish_event(
    hub: ConversationHub, conversation_id: uuid.UUID, event_type: str, data: dict[str, Any]
) -> None:
    await hub.publish(
        conversation_id, {"type": event_type, "conversation_id": str(conversation_id), "data": data}
    )


async def add_system_message(
    session: AsyncSession, conversation_id: uuid.UUID, body: str, *, now: datetime
) -> Message:
    """Append a system message (no sender) inside the caller's transaction."""
    return await insert_message(
        session, conversation_id, sender=None, body=body, kind=MessageKind.SYSTEM, now=now
    )


async def publish_message(
    session: AsyncSession, services: Services, hub: ConversationHub, message: Message
) -> None:
    members = await repository.members(session, message.conversation_id)
    out = (await messages_out(session, services, [message], members))[0]
    await hub.publish(
        message.conversation_id,
        {
            "type": "MESSAGE_CREATED",
            "conversation_id": str(message.conversation_id),
            "data": out.model_dump(mode="json"),
        },
    )


async def mark_read(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
) -> None:
    await require_member(session, caller, conversation_id)
    member = await repository.get_member(session, conversation_id, caller.user_id, for_update=True)
    assert member is not None
    message = await repository.get_message(session, message_id)
    if message is None or message.conversation_id != conversation_id:
        raise BadRequest("Unknown message.", code="INVALID_MESSAGE")
    if message.seq <= member.last_read_seq:
        await session.rollback()
        return  # read pointers only move forward
    now = services.clock.now()
    member.last_read_seq = message.seq
    member.last_read_message_id = message.id
    member.last_read_at = now
    await session.commit()
    await hub.publish(
        conversation_id,
        {
            "type": "MESSAGE_READ",
            "conversation_id": str(conversation_id),
            "data": {
                "user_id": str(caller.user_id),
                "last_read_message_id": str(message.id),
                "at": now.isoformat(),
            },
        },
    )


async def report(
    session: AsyncSession, caller: AuthContext, conversation_id: uuid.UUID, data: ReportIn
) -> Report:
    await require_member(session, caller, conversation_id)
    target_type, target_id = ReportTarget.CONVERSATION, conversation_id
    if data.message_id is not None:
        message = await repository.get_message(session, data.message_id)
        if message is None or message.conversation_id != conversation_id:
            raise BadRequest("Unknown message.", code="INVALID_MESSAGE")
        target_type, target_id = ReportTarget.MESSAGE, message.id
    return await create_report(
        session,
        caller,
        target_type=target_type,
        target_id=target_id,
        conversation_id=conversation_id,
        reason=data.reason,
        details=data.details,
    )


async def create_report(
    session: AsyncSession,
    caller: AuthContext,
    *,
    target_type: ReportTarget,
    target_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    reason: str,
    details: str | None,
) -> Report:
    """One report per (reporter, target); reused for reviews (Issue 7)."""
    if await repository.find_report(session, caller.user_id, target_type.value, target_id):
        raise Conflict("You have already reported this.", code="ALREADY_REPORTED")
    row = Report(
        reporter_id=caller.user_id,
        target_type=target_type.value,
        target_id=target_id,
        conversation_id=conversation_id,
        reason=reason,
        details=details,
    )
    repository.add(session, row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_reports_reporter_target":
            raise Conflict("You have already reported this.", code="ALREADY_REPORTED") from exc
        raise
    await audit.record(
        session,
        action=f"{target_type.value.lower()}.reported",
        entity_type=target_type.value.lower(),
        entity_id=target_id,
        actor_user_id=caller.user_id,
        data={"reason": reason},
    )
    await session.commit()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------- WebSocket tickets


async def issue_ticket(
    session: AsyncSession, services: Services, caller: AuthContext, conversation_id: uuid.UUID
) -> tuple[str, datetime]:
    now = services.clock.now()
    await services.rate_limiter.hit(
        bucket="ws_tickets",
        key=rate_limit_key(str(caller.user_id)),
        limit=60,
        window=timedelta(minutes=1),
        now=now,
    )
    await require_member(session, caller, conversation_id)
    raw = new_opaque_token()
    expires_at = now + TICKET_TTL
    repository.add(
        session,
        WebSocketTicket(
            token_hash=hash_token(raw),
            user_id=caller.user_id,
            family_id=caller.session_id,
            scope=TicketScope.CONVERSATION.value,
            conversation_id=conversation_id,
            expires_at=expires_at,
        ),
    )
    await repository.prune_tickets(session, now - timedelta(hours=1))
    await session.commit()
    return raw, expires_at


async def consume_ticket(session: AsyncSession, raw: str, now: datetime) -> WebSocketTicket | None:
    ticket = await repository.consume_ticket(session, hash_token(raw), now)
    await session.commit()
    return ticket
