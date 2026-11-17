"""Process-wide services built once by the app factory and shared via ``app.state``."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.core.email import EmailSender, build_email_sender
from app.core.ratelimit import RateLimiter
from app.core.security import AccessTokens, PasswordHashing
from app.core.storage import ObjectStorage, build_storage


@dataclass
class Services:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    passwords: PasswordHashing
    access_tokens: AccessTokens
    email: EmailSender
    rate_limiter: RateLimiter
    storage: ObjectStorage


def build_services(settings: Settings, *, clock: Clock | None = None) -> Services:
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    return Services(
        settings=settings,
        clock=clock or Clock(),
        engine=engine,
        session_factory=session_factory,
        passwords=PasswordHashing(settings),
        access_tokens=AccessTokens(settings),
        email=build_email_sender(settings),
        rate_limiter=RateLimiter(session_factory),
        storage=build_storage(settings),
    )
