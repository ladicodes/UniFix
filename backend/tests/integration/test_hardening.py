"""Security hardening at the HTTP edge: headers, request size limits, docs exposure."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from app.core.config import Environment, Settings
from app.core.container import Services, build_services
from app.main import create_app
from app.modules.stellar.context import StellarContext
from tests.conftest import make_settings
from tests.support import API, API_BASE_URL, register, upload


async def test_api_responses_carry_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/categories")
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in headers["permissions-policy"]
    assert headers["content-security-policy"].startswith("default-src 'none'")
    assert "strict-transport-security" not in headers  # only in production
    docs = await client.get(f"{API}/docs")
    assert "content-security-policy" not in docs.headers  # Swagger UI needs its scripts


async def test_oversized_json_body_is_rejected_before_parsing(client: httpx.AsyncClient) -> None:
    huge = "x" * (1024 * 1024 + 10)
    response = await client.post(
        f"{API}/auth/login", content=f'{{"email": "{huge}"}}', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


async def test_chunked_body_without_length_is_counted(client: httpx.AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(20):
            yield b"x" * 65_536

    response = await client.post(
        f"{API}/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


async def test_uploads_get_a_larger_outer_limit(client: httpx.AsyncClient, seeded: Services) -> None:
    account = await register(client)
    assert (await upload(client, account, "AVATAR")).status_code == 201
    too_big = await client.post(
        f"{API}/uploads",
        files={"file": ("big.png", b"0" * (12 * 1024 * 1024), "image/png")},
        data={"purpose": "AVATAR"},
        headers=account.headers,
    )
    assert too_big.status_code == 413


@pytest.fixture
async def production_like_client(
    settings: Settings, stellar: StellarContext
) -> AsyncIterator[httpx.AsyncClient]:
    """Same app with ``env=production`` semantics for the edge (HSTS, docs hidden)."""
    prod = make_settings(
        settings.database_url, expose_api_docs=False, email_backend="smtp", smtp_host="smtp.example.com"
    )
    prod.env = Environment.PRODUCTION  # assignment skips the full production validator
    services = build_services(prod)
    app = create_app(prod, services=services, stellar=StellarContext(prod, stellar.gateway))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=API_BASE_URL) as http:
        yield http
    await services.engine.dispose()


async def test_production_adds_hsts_and_hides_docs(production_like_client: httpx.AsyncClient) -> None:
    response = await production_like_client.get(f"{API}/categories")
    assert response.headers["strict-transport-security"].startswith("max-age=63072000")
    assert (await production_like_client.get(f"{API}/docs")).status_code == 404
    assert (await production_like_client.get(f"{API}/openapi.json")).status_code == 404


async def test_authenticated_writes_have_a_per_user_backstop_limit(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    account = await register(client)
    seeded.settings.user_write_rate_limit_per_minute = 3
    try:
        for _ in range(3):
            response = await client.patch(f"{API}/auth/me", json={"city": "Lagos"}, headers=account.headers)
            assert response.status_code == 200
        limited = await client.patch(f"{API}/auth/me", json={"city": "Lagos"}, headers=account.headers)
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0
        # Reads are not counted.
        assert (await client.get(f"{API}/auth/me", headers=account.headers)).status_code == 200
    finally:
        seeded.settings.user_write_rate_limit_per_minute = 10_000


def _png_header_only() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _bomb() -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("1", (12_000, 12_000)).save(out, format="PNG")  # 144 MP, compresses to a few KB
    return out.getvalue()


@pytest.mark.parametrize(
    ("name", "payload", "content_type"),
    [
        ("html-as-png", b"<html><script>alert(1)</script></html>", "image/png"),
        ("svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "image/svg+xml"),
        ("truncated-png", _png_header_only(), "image/png"),
        ("png-pdf-polyglot", _png_header_only() + b"%PDF-1.4\n%%EOF\n", "image/png"),
        ("exe", b"MZ\x90\x00" + b"\x00" * 200, "image/png"),
        ("empty", b"", "image/png"),
        ("decompression-bomb", _bomb(), "image/png"),
    ],
)
async def test_upload_fuzz_cases_are_rejected_cleanly(
    client: httpx.AsyncClient, seeded: Services, name: str, payload: bytes, content_type: str
) -> None:
    account = await register(client)
    response = await client.post(
        f"{API}/uploads",
        files={"file": (f"{name}.png", payload, content_type)},
        data={"purpose": "AVATAR"},
        headers=account.headers,
    )
    assert 400 <= response.status_code < 500, (name, response.status_code, response.text)
    assert response.json()["code"]
