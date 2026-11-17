"""Centralised, validated application settings.

Every runtime option is read from the environment (or ``backend/.env``) exactly once,
validated here, and passed around as a ``Settings`` instance. Production refuses to
start with insecure values instead of silently degrading.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

API_PREFIX = "/api/v1"
REFRESH_COOKIE_PATH = f"{API_PREFIX}/auth"
_EXAMPLE_SECRET_MARKER = "change-me"  # noqa: S105  (marker searched for, not a secret)


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class EmailBackend(StrEnum):
    CONSOLE = "console"
    SMTP = "smtp"


class SmtpTlsMode(StrEnum):
    STARTTLS = "starttls"
    TLS = "tls"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Environment = Environment.DEVELOPMENT
    app_name: str = "UniFix API"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = Field(
        description="SQLAlchemy URL using the psycopg driver, e.g. postgresql+psycopg://user:pw@host/db",
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)

    jwt_secret: SecretStr
    jwt_issuer: str = "unifix"
    jwt_audience: str = "unifix-api"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_idle_ttl_seconds: int = Field(default=14 * 24 * 3600, ge=3600)
    session_absolute_ttl_seconds: int = Field(default=30 * 24 * 3600, ge=3600)
    refresh_race_grace_seconds: int = Field(default=30, ge=0, le=120)

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    cookie_secure: bool = True

    password_hash_time_cost: int = Field(default=3, ge=1)
    password_hash_memory_kib: int = Field(default=65536, ge=8)
    password_hash_parallelism: int = Field(default=4, ge=1)

    login_max_failures: int = Field(default=5, ge=1)
    login_lockout_seconds: int = Field(default=900, ge=60)
    auth_ip_rate_limit_per_minute: int = Field(default=30, ge=1)
    email_action_rate_limit_per_hour: int = Field(default=5, ge=1)

    email_backend: EmailBackend = EmailBackend.CONSOLE
    email_from: str = "UniFix <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_tls_mode: SmtpTlsMode = SmtpTlsMode.STARTTLS
    smtp_timeout_seconds: float = 10.0

    frontend_base_url: str = "http://localhost:3000"
    email_verification_ttl_seconds: int = Field(default=24 * 3600, ge=600)
    password_reset_ttl_seconds: int = Field(default=3600, ge=600)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        normalised: list[str] = []
        for origin in origins:
            if origin == "*":
                raise ValueError(
                    "CORS_ORIGINS must list explicit origins; '*' is not allowed with credentials"
                )
            parts = urlsplit(origin)
            if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
                raise ValueError(f"Invalid CORS origin {origin!r}: expected scheme://host[:port]")
            normalised.append(f"{parts.scheme}://{parts.netloc}".lower())
        return normalised

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, url: str) -> str:
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use the postgresql+psycopg:// driver")
        return url

    @model_validator(mode="after")
    def _validate_security(self) -> Self:
        secret = self.jwt_secret.get_secret_value()
        if len(secret.encode()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 bytes")
        if self.session_absolute_ttl_seconds < self.refresh_idle_ttl_seconds:
            raise ValueError("SESSION_ABSOLUTE_TTL_SECONDS must be >= REFRESH_IDLE_TTL_SECONDS")
        if self.email_backend is EmailBackend.SMTP and not self.smtp_host:
            raise ValueError("EMAIL_BACKEND=smtp requires SMTP_HOST")
        if self.env is Environment.PRODUCTION:
            self._validate_production(secret)
        return self

    def _validate_production(self, secret: str) -> None:
        problems: list[str] = []
        if _EXAMPLE_SECRET_MARKER in secret:
            problems.append("JWT_SECRET still contains the example value")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true")
        if not self.cors_origins:
            problems.append("CORS_ORIGINS must not be empty")
        if any(not origin.startswith("https://") for origin in self.cors_origins):
            problems.append("CORS_ORIGINS must all be https")
        if self.email_backend is not EmailBackend.SMTP:
            problems.append("EMAIL_BACKEND must be smtp (console is development/test only)")
        if self.password_hash_memory_kib < 65536 or self.password_hash_time_cost < 3:
            problems.append("password hashing parameters are below the production minimum")
        if problems:
            raise ValueError("Insecure production configuration: " + "; ".join(problems))

    @property
    def refresh_cookie_name(self) -> str:
        # The __Secure- prefix makes browsers reject the cookie unless it is Secure.
        return "__Secure-unifix_rt" if self.cookie_secure else "unifix_rt"

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from the environment / .env
