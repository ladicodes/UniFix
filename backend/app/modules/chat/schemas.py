from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import APIModel, ResponseModel
from app.modules.campuses.schemas import CampusOut
from app.modules.chat.models import MessageKind, TicketScope
from app.modules.professionals.schemas import ProfessionalOut
from app.modules.uploads.schemas import FileRef

MessageBody = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


class PublicUser(ResponseModel):
    id: uuid.UUID
    name: str
    avatar_url: str | None
    city: str | None
    campus: CampusOut | None


class ConversationOut(ResponseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    professional_id: uuid.UUID
    booking_id: uuid.UUID | None = None
    service_request_id: uuid.UUID | None = None
    last_message_at: datetime | None
    last_message_preview: str
    unread_for: list[uuid.UUID]
    created_at: datetime


class MessageOut(ResponseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID | None = Field(description="null for system messages")
    kind: MessageKind
    body: str
    quote_id: uuid.UUID | None = None
    attachment: FileRef | None
    created_at: datetime
    read_at: datetime | None = Field(description="When the other participant read it")


class ConversationSummary(ResponseModel):
    conversation: ConversationOut
    professional: ProfessionalOut
    customer: PublicUser
    unread: bool


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut] = Field(description="Most recent messages, oldest first")
    quotes: list[dict[str, Any]] = Field(
        default_factory=list, description="Quotes in this conversation (Issue 3)"
    )


class OpenConversationIn(APIModel):
    professional_id: uuid.UUID


class SendMessageIn(APIModel):
    body: MessageBody = ""
    attachment_file_id: uuid.UUID | None = Field(
        default=None, description="A MESSAGE_ATTACHMENT upload of yours"
    )
    client_message_id: uuid.UUID | None = Field(
        default=None, description="Client-generated id; resending the same id returns the original message"
    )

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.body and self.attachment_file_id is None:
            raise ValueError("a message needs a body or an attachment")
        return self


class MarkReadIn(APIModel):
    last_read_message_id: uuid.UUID


class ReportIn(APIModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    details: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    message_id: uuid.UUID | None = None


class ReportOut(ResponseModel):
    id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    status: str
    created_at: datetime


class TicketIn(APIModel):
    scope: Literal[TicketScope.CONVERSATION] = TicketScope.CONVERSATION
    conversation_id: uuid.UUID


class TicketOut(ResponseModel):
    ticket: str = Field(description="Single use; valid for 30 seconds")
    expires_at: datetime
    ws_path: str
