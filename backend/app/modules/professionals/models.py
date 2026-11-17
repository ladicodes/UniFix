from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    Uuid,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, enum_check


class Availability(StrEnum):
    NOW = "NOW"
    TODAY = "TODAY"
    THIS_WEEK = "THIS_WEEK"
    UNAVAILABLE = "UNAVAILABLE"


class Currency(StrEnum):
    NGN = "NGN"
    GHS = "GHS"


class VerificationStatus(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VerificationType(StrEnum):
    IDENTITY = "IDENTITY"
    TRADE = "TRADE"
    PHONE = "PHONE"


class SortOrder(StrEnum):
    BEST = "BEST"
    NEAREST = "NEAREST"
    MOST_JOBS = "MOST_JOBS"
    EXPERIENCE = "EXPERIENCE"


class CheckStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# The search document. Built with an IMMUTABLE helper (created in migration 0002) because
# array_to_string() is only STABLE and generated columns require immutable expressions.
SEARCH_VECTOR_SQL = (
    "to_tsvector('simple', coalesce(headline, '') || ' ' || coalesce(bio, '') || ' ' || "
    "coalesce(area, '') || ' ' || coalesce(city, '') || ' ' || unifix_join_text_array(skills))"
)


class ProfessionalProfile(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "professional_profiles"
    __table_args__ = (
        CheckConstraint(enum_check("availability", Availability), name="availability_valid"),
        CheckConstraint(enum_check("currency", Currency), name="currency_valid"),
        CheckConstraint(
            enum_check("verification_status", VerificationStatus), name="verification_status_valid"
        ),
        CheckConstraint("country IN ('NG', 'GH')", name="country_valid"),
        CheckConstraint("years_experience BETWEEN 0 AND 60", name="years_experience_range"),
        CheckConstraint("starting_price_minor >= 0", name="starting_price_non_negative"),
        CheckConstraint("rating_avg BETWEEN 0 AND 5", name="rating_avg_range"),
        CheckConstraint("rating_count >= 0 AND completed_jobs >= 0", name="counters_non_negative"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_paired"),
        Index("ix_professional_profiles_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_professional_profiles_primary_category_listed", "primary_category_id", "is_listed"),
        Index("ix_professional_profiles_rating_avg", "rating_avg"),
        Index("ix_professional_profiles_completed_jobs", "completed_jobs"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    primary_category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_categories.id", ondelete="RESTRICT"), nullable=False
    )
    headline: Mapped[str] = mapped_column(String(120), nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    area: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    # Approximate (rounded to ~1 km) and never returned by any endpoint.
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    years_experience: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    availability: Mapped[str] = mapped_column(String(16), nullable=False)
    starting_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    skills: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    languages: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    coverage: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    is_listed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=VerificationStatus.NOT_SUBMITTED.value
    )
    rating_avg: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default="0")
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rating_quality: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default="0")
    rating_punctuality: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default="0")
    rating_communication: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default="0")
    rating_professionalism: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default="0")
    rating_value: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default="0")
    completed_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    response_minutes: Mapped[int | None] = mapped_column(Integer)
    search_vector: Mapped[str] = mapped_column(TSVECTOR, Computed(SEARCH_VECTOR_SQL, persisted=True))


professional_categories = Table(
    "professional_categories",
    Base.metadata,
    Column("professional_id", ForeignKey("professional_profiles.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", ForeignKey("service_categories.id", ondelete="RESTRICT"), primary_key=True),
    Index("ix_professional_categories_category_id", "category_id"),
)

professional_campuses = Table(
    "professional_campuses",
    Base.metadata,
    Column("professional_id", ForeignKey("professional_profiles.id", ondelete="CASCADE"), primary_key=True),
    Column("campus_id", ForeignKey("campuses.id", ondelete="RESTRICT"), primary_key=True),
    Index("ix_professional_campuses_campus_id", "campus_id"),
)


class ProfessionalVerification(UUIDPrimaryKey, Timestamps, Base):
    """One verification check per type. Resubmission resets it to PENDING; history is in audit_logs."""

    __tablename__ = "professional_verifications"
    __table_args__ = (
        CheckConstraint(enum_check("type", VerificationType), name="type_valid"),
        CheckConstraint(enum_check("status", CheckStatus), name="status_valid"),
        Index("uq_professional_verifications_professional_type", "professional_id", "type", unique=True),
        Index("ix_professional_verifications_status", "status", "submitted_at"),
    )

    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # PostgreSQL cannot FK array elements; the service validates ownership and purpose of every id.
    file_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), nullable=False, server_default="{}")
    note: Mapped[str | None] = mapped_column(String(1000))
    submitted_at: Mapped[datetime] = mapped_column(nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column()
    rejection_reason: Mapped[str | None] = mapped_column(String(500))


class PortfolioItem(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "portfolio_items"
    __table_args__ = (Index("ix_portfolio_items_professional_sort", "professional_id", "sort_order"),)

    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    caption: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_categories.id", ondelete="SET NULL")
    )
    image_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="RESTRICT"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
