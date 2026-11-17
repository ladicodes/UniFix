from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.ratelimit import rate_limit_key
from app.core.security import AccessTokens, InvalidAccessToken, PasswordHashing, hash_token, new_opaque_token
from app.modules.auth.sessions import ip_hint

SETTINGS = Settings(
    _env_file=None,  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost/db",
    jwt_secret="unit-test-secret-" + "y" * 32,
    password_hash_time_cost=1,
    password_hash_memory_kib=1024,
    password_hash_parallelism=1,
)
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def test_password_hash_roundtrip_and_mismatch() -> None:
    hashing = PasswordHashing(SETTINGS)
    hashed = hashing.hash("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert hashing.verify(hashed, "correct horse battery staple")
    assert not hashing.verify(hashed, "Correct horse battery staple")
    assert not hashing.verify(None, "anything")  # unknown account path
    assert not hashing.verify("not-a-hash", "anything")


def test_password_rehash_detected_when_parameters_change() -> None:
    weak = PasswordHashing(SETTINGS).hash("pw-1234567890")
    stronger = PasswordHashing(SETTINGS.model_copy(update={"password_hash_time_cost": 2}))
    assert stronger.needs_rehash(weak)


def test_access_token_roundtrip() -> None:
    tokens = AccessTokens(SETTINGS)
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    token = tokens.issue(user_id=user_id, session_id=session_id, role="CUSTOMER", now=NOW)
    claims = tokens.decode(token, now=NOW + timedelta(minutes=5))
    assert (claims.user_id, claims.session_id, claims.role) == (user_id, session_id, "CUSTOMER")


def test_access_token_expiry_uses_supplied_clock() -> None:
    tokens = AccessTokens(SETTINGS)
    token = tokens.issue(user_id=uuid.uuid4(), session_id=uuid.uuid4(), role="CUSTOMER", now=NOW)
    tokens.decode(token, now=NOW + timedelta(seconds=900))  # within 5 s leeway
    with pytest.raises(InvalidAccessToken, match="expired"):
        tokens.decode(token, now=NOW + timedelta(seconds=906))
    with pytest.raises(InvalidAccessToken, match="not yet valid"):
        tokens.decode(token, now=NOW - timedelta(seconds=60))


def test_access_token_rejects_tampering_wrong_key_audience_and_alg_none() -> None:
    tokens = AccessTokens(SETTINGS)
    token = tokens.issue(user_id=uuid.uuid4(), session_id=uuid.uuid4(), role="CUSTOMER", now=NOW)
    payload = jwt.decode(token, options={"verify_signature": False})
    forged_role = jwt.encode({**payload, "role": "ADMIN"}, "some-other-secret-" + "z" * 32, algorithm="HS256")
    wrong_audience = jwt.encode(
        {**payload, "aud": "someone-else"}, SETTINGS.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    unsigned = jwt.encode(payload, None, algorithm="none")  # type: ignore[arg-type]
    for bad in (forged_role, wrong_audience, unsigned, token + "x", "not.a.jwt"):
        with pytest.raises(InvalidAccessToken):
            tokens.decode(bad, now=NOW)


def test_opaque_tokens_are_random_and_hashes_deterministic() -> None:
    first, second = new_opaque_token(), new_opaque_token()
    assert first != second
    assert len(first) >= 43
    assert hash_token(first) == hash_token(first)
    assert len(hash_token(first)) == 64


def test_rate_limit_key_hides_raw_values() -> None:
    key = rate_limit_key("ada@example.com")
    assert "ada" not in key
    assert key == rate_limit_key("ada@example.com")


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("102.89.34.7", "102.89.0.0/16"),
        ("2001:db8:1234::1", "2001:db8::/32"),
        (None, None),
        ("garbage", None),
    ],
)
def test_ip_hint(ip: str | None, expected: str | None) -> None:
    assert ip_hint(ip) == expected
