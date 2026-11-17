"""Imports every ORM model so that SQLAlchemy metadata (and Alembic) sees all tables."""

from app.core.ratelimit import RateLimitEvent
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthRefreshToken, AuthSessionFamily, UserToken
from app.modules.bookings.models import Booking, BookingEvent, IdempotencyKey
from app.modules.calls.models import CallSession
from app.modules.campuses.models import Campus
from app.modules.catalog.models import ServiceCategory
from app.modules.chat.models import Conversation, ConversationMember, Message, Report, WebSocketTicket
from app.modules.professionals.models import PortfolioItem, ProfessionalProfile, ProfessionalVerification
from app.modules.quotes.models import Agreement, Quote
from app.modules.requests.models import ServiceRequest
from app.modules.uploads.models import StoredFile
from app.modules.users.models import User
from app.modules.wallets.models import Wallet, WalletChallenge

__all__ = [
    "Agreement",
    "AuditLog",
    "AuthRefreshToken",
    "AuthSessionFamily",
    "Booking",
    "BookingEvent",
    "CallSession",
    "Campus",
    "Conversation",
    "ConversationMember",
    "IdempotencyKey",
    "Message",
    "PortfolioItem",
    "ProfessionalProfile",
    "ProfessionalVerification",
    "Quote",
    "RateLimitEvent",
    "Report",
    "ServiceCategory",
    "ServiceRequest",
    "StoredFile",
    "User",
    "UserToken",
    "Wallet",
    "WalletChallenge",
    "WebSocketTicket",
]
