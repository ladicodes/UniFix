from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import EmailBackend, Environment, Settings

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
    ],
)
def test_insecure_production_configuration_is_refused(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        build(**production(**overrides))


def test_cookie_name_depends_on_secure_flag() -> None:
    assert build(cookie_secure=True).refresh_cookie_name == "__Secure-unifix_rt"
    assert build(cookie_secure=False).refresh_cookie_name == "unifix_rt"
