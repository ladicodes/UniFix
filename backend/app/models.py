"""Imports every ORM model so that SQLAlchemy metadata (and Alembic) sees all tables."""

from app.core.ratelimit import RateLimitEvent
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthRefreshToken, AuthSessionFamily, UserToken
from app.modules.campuses.models import Campus
from app.modules.catalog.models import ServiceCategory
from app.modules.professionals.models import PortfolioItem, ProfessionalProfile, ProfessionalVerification
from app.modules.uploads.models import StoredFile
from app.modules.users.models import User

__all__ = [
    "AuditLog",
    "AuthRefreshToken",
    "AuthSessionFamily",
    "Campus",
    "PortfolioItem",
    "ProfessionalProfile",
    "ProfessionalVerification",
    "RateLimitEvent",
    "ServiceCategory",
    "StoredFile",
    "User",
    "UserToken",
]
