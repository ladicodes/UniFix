"""Test helpers and test doubles (never used by application code)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.email import OutgoingEmail

ALLOWED_ORIGIN = "https://app.unifix.test"
API_BASE_URL = "https://api.unifix.test"
API = "/api/v1"
PASSWORD = "correct horse battery staple"
COOKIE_HEADERS = {"Origin": ALLOWED_ORIGIN, "X-CSRF-Protection": "1"}


@dataclass
class RecordingEmailSender:
    """Test double for the email backend: records messages instead of delivering them."""

    sent: list[OutgoingEmail] = field(default_factory=list)

    async def send(self, message: OutgoingEmail) -> None:
        self.sent.append(message)

    def token_for(self, to: str, path: str) -> str:
        for message in reversed(self.sent):
            if message.to == to:
                found = re.search(rf"{re.escape(path)}\?token=([A-Za-z0-9_-]+)", message.text_body)
                if found:
                    return found.group(1)
        raise AssertionError(f"No {path} email for {to}")


@dataclass
class Account:
    id: uuid.UUID
    email: str
    access_token: str
    refresh_cookie: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def refresh_cookie_value(response: httpx.Response, name: str = "__Secure-unifix_rt") -> str:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{name}="):
            return header.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"No {name} cookie in response")


async def register(
    client: httpx.AsyncClient,
    *,
    email: str | None = None,
    role: str = "CUSTOMER",
    name: str = "Ada Obi",
    password: str = PASSWORD,
    **extra: Any,
) -> Account:
    email = email or f"user-{uuid.uuid4().hex[:12]}@example.com"
    body = {"name": name, "email": email, "password": password, "role": role, "country": "NG", **extra}
    response = await client.post(f"{API}/auth/register", json=body, headers=COOKIE_HEADERS)
    assert response.status_code == 201, response.text
    data = response.json()
    return Account(
        id=uuid.UUID(data["user"]["id"]),
        email=email,
        access_token=data["access_token"],
        refresh_cookie=refresh_cookie_value(response),
    )


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post(
        f"{API}/auth/login", json={"email": email, "password": password}, headers=COOKIE_HEADERS
    )


async def refresh_with(client: httpx.AsyncClient, cookie: str) -> httpx.Response:
    """Refresh with an explicit cookie value (independent of the client's cookie jar)."""
    client.cookies.clear()
    return await client.post(
        f"{API}/auth/refresh", headers={**COOKIE_HEADERS, "Cookie": f"__Secure-unifix_rt={cookie}"}
    )
