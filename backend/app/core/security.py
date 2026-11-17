"""Password hashing, opaque token generation and access-token (JWT) handling."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

_ACCESS_TOKEN_ALGORITHM = "HS256"  # noqa: S105  (algorithm name)
_CLOCK_LEEWAY = timedelta(seconds=5)


class PasswordHashing:
    """Argon2id hashing with a constant-time path for unknown accounts."""

    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.password_hash_time_cost,
            memory_cost=settings.password_hash_memory_kib,
            parallelism=settings.password_hash_parallelism,
        )
        # Verified against when an account does not exist so timing does not reveal existence.
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(16))

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str | None, password: str) -> bool:
        try:
            return (
                self._hasher.verify(password_hash or self._dummy_hash, password) and password_hash is not None
            )
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)


def new_opaque_token() -> str:
    """256-bit URL-safe random token (refresh tokens, email links, WebSocket tickets)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest. Opaque tokens are only ever stored hashed."""
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    role: str
    expires_at: datetime


class InvalidAccessToken(Exception):
    pass


class AccessTokens:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret.get_secret_value()
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._ttl = timedelta(seconds=settings.access_token_ttl_seconds)

    @property
    def ttl_seconds(self) -> int:
        return int(self._ttl.total_seconds())

    def issue(self, *, user_id: uuid.UUID, session_id: uuid.UUID, role: str, now: datetime) -> str:
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(user_id),
            "sid": str(session_id),
            "role": role,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + self._ttl).timestamp()),
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(payload, self._secret, algorithm=_ACCESS_TOKEN_ALGORITHM)

    def decode(self, token: str, *, now: datetime) -> AccessTokenClaims:
        """Verify signature, issuer and audience; check ``exp``/``nbf`` against the app clock."""
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[_ACCESS_TOKEN_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": ["exp", "iat", "nbf", "sub", "sid", "iss", "aud", "jti"],
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                },
            )
            expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
            not_before = datetime.fromtimestamp(int(payload["nbf"]), tz=UTC)
            claims = AccessTokenClaims(
                user_id=uuid.UUID(payload["sub"]),
                session_id=uuid.UUID(payload["sid"]),
                role=str(payload["role"]),
                expires_at=expires_at,
            )
        except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
            raise InvalidAccessToken(str(exc)) from exc
        if now >= expires_at + _CLOCK_LEEWAY:
            raise InvalidAccessToken("token expired")
        if now + _CLOCK_LEEWAY < not_before:
            raise InvalidAccessToken("token not yet valid")
        return claims
