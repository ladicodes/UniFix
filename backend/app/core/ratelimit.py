"""PostgreSQL-backed sliding-window rate limiter.

State lives in the database, so limits hold across processes and instances without Redis.
Every operation runs in its **own** short transaction: a request that later fails (for
example a wrong password) must still leave its rate-limit record behind. A
transaction-scoped advisory lock per (bucket, key) makes check-and-record atomic.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import BigInteger, Index, String, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import RateLimited


class RateLimitEvent(Base):
    __tablename__ = "rate_limit_events"
    __table_args__ = (Index("ix_rate_limit_events_bucket_key_at", "bucket", "key", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    at: Mapped[datetime] = mapped_column(nullable=False)


def rate_limit_key(*parts: str | None) -> str:
    """Stable, privacy-preserving key: raw emails and IPs are never stored."""
    joined = "|".join(part or "-" for part in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


class RateLimiter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    async def _lock(session: AsyncSession, bucket: str, key: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"{bucket}:{key}"}
        )

    @staticmethod
    async def _retry_after(
        session: AsyncSession, bucket: str, key: str, limit: int, window: timedelta, now: datetime
    ) -> int | None:
        in_window = (
            RateLimitEvent.bucket == bucket,
            RateLimitEvent.key == key,
            RateLimitEvent.at > now - window,
        )
        count = int((await session.execute(select(func.count()).where(*in_window))).scalar_one())
        if count < limit:
            return None
        oldest = await session.scalar(select(func.min(RateLimitEvent.at)).where(*in_window))
        return int(((oldest or now) + window - now).total_seconds()) + 1

    async def hit(self, *, bucket: str, key: str, limit: int, window: timedelta, now: datetime) -> None:
        """Record one event; raise ``RateLimited`` if the window already holds ``limit`` events."""
        async with self._session_factory() as session, session.begin():
            await self._lock(session, bucket, key)
            await session.execute(
                delete(RateLimitEvent).where(
                    RateLimitEvent.bucket == bucket,
                    RateLimitEvent.key == key,
                    RateLimitEvent.at <= now - window,
                )
            )
            retry_after = await self._retry_after(session, bucket, key, limit, window, now)
            if retry_after is not None:
                raise RateLimited(retry_after)
            session.add(RateLimitEvent(bucket=bucket, key=key, at=now))

    async def record(self, *, bucket: str, key: str, now: datetime) -> None:
        """Record an event without checking (e.g. a failed login, counted after the fact)."""
        async with self._session_factory() as session, session.begin():
            await self._lock(session, bucket, key)
            session.add(RateLimitEvent(bucket=bucket, key=key, at=now))

    async def retry_after(
        self, *, bucket: str, key: str, limit: int, window: timedelta, now: datetime
    ) -> int | None:
        """Seconds until the window frees up if ``limit`` is reached, otherwise None."""
        async with self._session_factory() as session:
            return await self._retry_after(session, bucket, key, limit, window, now)

    async def clear(self, *, bucket: str, key: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(RateLimitEvent).where(RateLimitEvent.bucket == bucket, RateLimitEvent.key == key)
            )
