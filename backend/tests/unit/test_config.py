from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import EmailBackend, Environment, Settings, StorageBackend

BASE: dict[str, Any] = {
    "database_url": "postgresql+psycopg://u:p@localhost/db",
    "jwt_secret": "s" * 40,
}


def build(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def production(**overrides: Any) -> dict[str, Any]:
    return {
        "env": Environment.PRODUCTION,
        "cors_origins": ["https://app.unifix.ng"],
        "cookie_secure": True,
        "email_backend": EmailBackend.SMTP,
        "smtp_host": "smtp.example.com",
        "storage_backend": StorageBackend.S3,
        "s3_bucket": "unifix-uploads",
        "frontend_base_url": "https://app.unifix.ng",
        **overrides,
    }


def test_origins_are_parsed_and_normalised() -> None:
    settings = build(cors_origins="https://App.Unifix.ng/, http://localhost:3000")
    assert settings.cors_origins == ["https://app.unifix.ng", "http://localhost:3000"]


@pytest.mark.parametrize("origin", ["*", "app.unifix.ng", "https://app.unifix.ng/path", "ftp://x.y"])
def test_invalid_or_wildcard_origins_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        build(cors_origins=[origin])


def test_short_jwt_secret_rejected() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        build(jwt_secret="too-short")


def test_database_driver_enforced() -> None:
    with pytest.raises(ValidationError):
        build(database_url="postgresql://u:p@localhost/db")


def test_smtp_backend_requires_host() -> None:
    with pytest.raises(ValidationError, match="SMTP_HOST"):
        build(email_backend=EmailBackend.SMTP)


def test_valid_production_configuration_is_accepted() -> None:
    assert build(**production()).is_production


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"cors_origins": []}, "CORS_ORIGINS must not be empty"),
        ({"cors_origins": ["http://app.unifix.ng"]}, "https"),
        ({"email_backend": EmailBackend.CONSOLE}, "EMAIL_BACKEND"),
        ({"jwt_secret": "change-me-" + "x" * 40}, "example value"),
        ({"password_hash_memory_kib": 1024}, "password hashing"),
        ({"storage_backend": StorageBackend.LOCAL}, "STORAGE_BACKEND"),
    ],
)
def test_insecure_production_configuration_is_refused(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        build(**production(**overrides))


def test_cookie_name_depends_on_secure_flag() -> None:
    assert build(cookie_secure=True).refresh_cookie_name == "__Secure-unifix_rt"
    assert build(cookie_secure=False).refresh_cookie_name == "unifix_rt"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"cors_origins": []}, "CORS_ORIGINS must not be empty"),
        ({"cors_origins": ["http://app.unifix.ng"]}, "CORS_ORIGINS must all be https"),
        ({"jwt_secret": "change-me-to-a-long-random-value-at-least-32-bytes"}, "JWT_SECRET"),
        ({"email_backend": EmailBackend.CONSOLE}, "EMAIL_BACKEND"),
        ({"storage_backend": StorageBackend.LOCAL}, "STORAGE_BACKEND"),
        ({"password_hash_memory_kib": 1024}, "password hashing"),
        ({"frontend_base_url": "http://app.unifix.ng"}, "FRONTEND_BASE_URL must be https"),
        ({"frontend_base_url": "https://other.unifix.ng"}, "FRONTEND_BASE_URL must be one of CORS_ORIGINS"),
        ({"log_level": "DEBUG"}, "LOG_LEVEL"),
        ({"smtp_password": "change-me"}, "SMTP_PASSWORD"),
        ({"s3_secret_access_key": "change-me-please"}, "S3_SECRET_ACCESS_KEY"),
    ],
)
def test_each_insecure_production_setting_is_refused(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        build(**production(**overrides))


def test_api_docs_are_hidden_in_production_unless_enabled() -> None:
    assert build().api_docs_enabled
    assert not build(**production()).api_docs_enabled
    assert build(**production(expose_api_docs=True)).api_docs_enabled
