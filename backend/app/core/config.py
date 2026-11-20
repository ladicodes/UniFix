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


class StorageBackend(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class StellarNetwork(StrEnum):
    TESTNET = "TESTNET"
    PUBLIC = "PUBLIC"


NETWORK_PASSPHRASES = {
    StellarNetwork.TESTNET: "Test SDF Network ; September 2015",
    StellarNetwork.PUBLIC: "Public Global Stellar Network ; September 2015",
}


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
    # Backstop for every authenticated write (POST/PATCH/PUT/DELETE), per user, on top of the
    # route-specific limits (login, chat, uploads, requests, wallet challenges, WS tickets).
    user_write_rate_limit_per_minute: int = Field(default=120, ge=1)

    email_backend: EmailBackend = EmailBackend.CONSOLE
    email_from: str = "UniFix <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_tls_mode: SmtpTlsMode = SmtpTlsMode.STARTTLS
    smtp_timeout_seconds: float = 10.0

    storage_backend: StorageBackend = StorageBackend.LOCAL
    local_storage_dir: str = "var/uploads"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    signed_url_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    upload_rate_limit_per_hour: int = Field(default=120, ge=1)

    webrtc_stun_urls: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["stun:stun.l.google.com:19302"]
    )

    # --- Stellar / Soroban escrow (STELLAR_ESCROW_DESIGN). Unset contract id = payments disabled (503).
    stellar_network: StellarNetwork = StellarNetwork.TESTNET
    stellar_rpc_url: str = "https://soroban-testnet.stellar.org"
    stellar_horizon_url: str = "https://horizon-testnet.stellar.org"
    stellar_network_epoch: str = Field(default="1", min_length=1, max_length=32)
    stellar_explorer_url: str = "https://stellar.expert/explorer/testnet"
    stellar_check_on_startup: bool = True
    stellar_rpc_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    escrow_contract_id: str | None = None
    # Circle testnet USDC, verified 2026-11-17 (STELLAR_ESCROW_DESIGN §8.1). Public identifiers.
    escrow_token_code: str = "USDC"  # noqa: S105
    escrow_token_issuer: str = "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"  # noqa: S105
    escrow_token_contract_id: str = "CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"  # noqa: S105
    escrow_token_decimals: int = Field(default=7, ge=0, le=18)
    escrow_id_secret: SecretStr | None = None
    stellar_operator_secret: SecretStr | None = None
    stellar_operator_address: str | None = None
    escrow_review_window_seconds: int = Field(default=72 * 3600, ge=60, le=14 * 24 * 3600)
    escrow_service_grace_seconds: int = Field(default=3 * 24 * 3600, ge=0, le=30 * 24 * 3600)
    # Must match the contract build: 86400 (production) or 60 (the test-only short-windows build).
    escrow_deadline_unit_seconds: int = 86_400
    escrow_tx_valid_seconds: int = Field(default=300, ge=60, le=900)
    # D14: fixed demo rate (fiat major units per 1 whole token unit); refused off testnet.
    fx_demo_rate_ngn: str | None = None
    fx_demo_rate_ghs: str | None = None
    # Reconciler and keeper (STELLAR_ESCROW_DESIGN §10, D16b).
    reconciler_enabled: bool = True
    reconciler_interval_seconds: float = Field(default=5.0, gt=0, le=300)
    reconciler_start_ledger: int | None = Field(
        default=None, ge=1, description="First scan; default oldest retained"
    )
    keeper_delay_seconds: int = Field(default=15 * 60, ge=0, le=24 * 3600)
    wallet_challenge_ttl_seconds: int = Field(default=300, ge=60, le=900)
    wallet_challenge_rate_limit_per_hour: int = Field(default=20, ge=1)

    frontend_base_url: str = "http://localhost:3000"
    # Request size limits (enforced in middleware before the body is parsed).
    max_request_body_bytes: int = Field(default=1024 * 1024, ge=16 * 1024, le=16 * 1024 * 1024)
    max_upload_body_bytes: int = Field(default=11 * 1024 * 1024, ge=1024 * 1024, le=64 * 1024 * 1024)
    # Swagger UI and the OpenAPI document; off by default in production.
    expose_api_docs: bool | None = None
    email_verification_ttl_seconds: int = Field(default=24 * 3600, ge=600)
    password_reset_ttl_seconds: int = Field(default=3600, ge=600)

    @field_validator("webrtc_stun_urls", mode="before")
    @classmethod
    def _split_stun(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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
        if self.storage_backend is StorageBackend.S3 and not self.s3_bucket:
            raise ValueError("STORAGE_BACKEND=s3 requires S3_BUCKET")
        self._validate_stellar()
        if self.env is Environment.PRODUCTION:
            self._validate_production(secret)
        return self

    def _validate_stellar(self) -> None:
        from stellar_sdk import Asset, Keypair, StrKey

        if not StrKey.is_valid_ed25519_public_key(self.escrow_token_issuer):
            raise ValueError("ESCROW_TOKEN_ISSUER is not a valid Stellar account address")
        expected = Asset(self.escrow_token_code, self.escrow_token_issuer).contract_id(
            self.network_passphrase
        )
        if self.escrow_token_contract_id != expected:
            raise ValueError(
                "ESCROW_TOKEN_CONTRACT_ID does not match Asset(code, issuer).contract_id(passphrase)"
            )
        if self.stellar_network is not StellarNetwork.TESTNET and (
            self.fx_demo_rate_ngn or self.fx_demo_rate_ghs
        ):
            raise ValueError("A demo FX rate (FX_DEMO_RATE_*) is only allowed on TESTNET")
        if self.escrow_deadline_unit_seconds not in {60, 86_400}:
            raise ValueError(
                "ESCROW_DEADLINE_UNIT_SECONDS must be 86400 (or 60 for the short-windows test build)"
            )
        if self.escrow_deadline_unit_seconds != 86_400 and self.env is Environment.PRODUCTION:
            raise ValueError("The short-windows test contract build is not allowed in production")
        if self.escrow_contract_id is None:
            return
        if not StrKey.is_valid_contract(self.escrow_contract_id):
            raise ValueError("ESCROW_CONTRACT_ID is not a valid contract address")
        if self.escrow_id_secret is None or len(self.escrow_id_secret.get_secret_value().encode()) < 32:
            raise ValueError("ESCROW_ID_SECRET (>= 32 bytes) is required when ESCROW_CONTRACT_ID is set")
        unit = self.escrow_deadline_unit_seconds
        if not unit <= self.escrow_review_window_seconds <= 14 * unit:
            raise ValueError(
                "ESCROW_REVIEW_WINDOW_SECONDS must be within the contract's bounds (1 to 14 units)"
            )
        if self.stellar_operator_secret is None or self.stellar_operator_address is None:
            raise ValueError("STELLAR_OPERATOR_SECRET and STELLAR_OPERATOR_ADDRESS are required for escrow")
        try:
            operator = Keypair.from_secret(self.stellar_operator_secret.get_secret_value())
        except Exception as exc:  # the secret itself must never appear in the message
            raise ValueError("STELLAR_OPERATOR_SECRET is not a valid Stellar secret seed") from exc
        if operator.public_key != self.stellar_operator_address:
            raise ValueError("STELLAR_OPERATOR_SECRET does not match STELLAR_OPERATOR_ADDRESS")

    @property
    def network_passphrase(self) -> str:
        return NETWORK_PASSPHRASES[self.stellar_network]

    @property
    def escrow_enabled(self) -> bool:
        return self.escrow_contract_id is not None

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
        if self.storage_backend is not StorageBackend.S3:
            problems.append("STORAGE_BACKEND must be s3 (local is development/test only)")
        if self.password_hash_memory_kib < 65536 or self.password_hash_time_cost < 3:
            problems.append("password hashing parameters are below the production minimum")
        for name, value in (
            ("ESCROW_ID_SECRET", self.escrow_id_secret),
            ("SMTP_PASSWORD", self.smtp_password),
            ("S3_SECRET_ACCESS_KEY", self.s3_secret_access_key),
        ):
            if value is not None and _EXAMPLE_SECRET_MARKER in value.get_secret_value():
                problems.append(f"{name} still contains the example value")
        if not self.frontend_base_url.startswith("https://"):
            problems.append("FRONTEND_BASE_URL must be https")
        if self.frontend_base_url.rstrip("/").lower() not in self.cors_origins:
            problems.append("FRONTEND_BASE_URL must be one of CORS_ORIGINS (the CSRF origin allowlist)")
        if self.log_level.upper() == "DEBUG":
            problems.append("LOG_LEVEL=DEBUG is not allowed in production")
        if problems:
            raise ValueError("Insecure production configuration: " + "; ".join(problems))

    @property
    def refresh_cookie_name(self) -> str:
        # The __Secure- prefix makes browsers reject the cookie unless it is Secure.
        return "__Secure-unifix_rt" if self.cookie_secure else "unifix_rt"

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    @property
    def api_docs_enabled(self) -> bool:
        return (not self.is_production) if self.expose_api_docs is None else self.expose_api_docs


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from the environment / .env
