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


# ---------------------------------------------------------------- Issue 2 helpers


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (64, 48), *, exif_make: str | None = None) -> bytes:
    import io

    from PIL import Image

    image = Image.new("RGB", size, (200, 30, 60))
    output = io.BytesIO()
    if exif_make is not None:
        exif = Image.Exif()
        exif[0x010F] = exif_make  # Make
        exif[0x8825] = {1: "N", 2: (6.0, 30.0, 52.0), 3: "E", 4: (3.0, 23.0, 0.0)}  # GPS IFD
        image.save(output, format=fmt, exif=exif)
    else:
        image.save(output, format=fmt)
    return output.getvalue()


PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


async def upload(
    client: httpx.AsyncClient,
    account: Account,
    purpose: str,
    data: bytes | None = None,
    *,
    filename: str = "photo.png",
    content_type: str = "image/png",
) -> httpx.Response:
    return await client.post(
        f"{API}/uploads",
        files={"file": (filename, data if data is not None else image_bytes(), content_type)},
        data={"purpose": purpose},
        headers=account.headers,
    )


async def create_admin_account(client: httpx.AsyncClient, services: Any) -> Account:
    from app.modules.users import service as users_service

    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    async with services.session_factory() as session:
        await users_service.create_admin(session, services, email=email, name="Ops Admin", password=PASSWORD)
    response = await login(client, email)
    assert response.status_code == 200, response.text
    data = response.json()
    return Account(
        id=uuid.UUID(data["user"]["id"]), email=email, access_token=data["access_token"], refresh_cookie=""
    )


def professional_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "category_slug": "phone-repair",
        "headline": "Phone screens fixed same day",
        "bio": "Five years repairing iPhones and Androids near campus.",
        "city": "Lagos",
        "area": "Akoka",
        "country": "NG",
        "coverage": ["Akoka", "Yaba"],
        "years_experience": 5,
        "starting_price_minor": 1_500_000,
        "currency": "NGN",
        "availability": "TODAY",
        "skills": ["iPhone screens", "battery replacement"],
        "languages": ["English", "Yoruba"],
    }
    payload.update(overrides)
    return payload


async def register_professional(
    client: httpx.AsyncClient, *, name: str = "Tunde Bakare", **profile: Any
) -> tuple[Account, str]:
    account = await register(
        client, role="PROFESSIONAL", name=name, professional=professional_payload(**profile)
    )
    me = (await client.get(f"{API}/auth/me", headers=account.headers)).json()
    return account, me["professional_id"]


# ---------------------------------------------------------------- Issue 4 helpers


async def open_conversation(client: httpx.AsyncClient, customer: Account, professional_id: str) -> str:
    response = await client.post(
        f"{API}/conversations", json={"professional_id": professional_id}, headers=customer.headers
    )
    assert response.status_code in {200, 201}, response.text
    return str(response.json()["id"])


async def send(
    client: httpx.AsyncClient, account: Account, conversation_id: str, body: str, **extra: Any
) -> httpx.Response:
    return await client.post(
        f"{API}/conversations/{conversation_id}/messages",
        json={"body": body, **extra},
        headers=account.headers,
    )


async def ticket(client: httpx.AsyncClient, account: Account, conversation_id: str) -> str:
    response = await client.post(
        f"{API}/ws/tickets", json={"conversation_id": conversation_id}, headers=account.headers
    )
    assert response.status_code == 201, response.text
    return str(response.json()["ticket"])


# ---------------------------------------------------------------- Issue 3 helpers


async def verify_email(client: httpx.AsyncClient, outbox: RecordingEmailSender, account: Account) -> None:
    token = outbox.token_for(account.email, "/verify-email")
    response = await client.post(f"{API}/auth/verify-email/confirm", json={"token": token})
    assert response.status_code == 200, response.text


def quote_payload(conversation_id: str, **overrides: Any) -> dict[str, Any]:
    import datetime as _dt

    payload: dict[str, Any] = {
        "conversation_id": conversation_id,
        "title": "Replace iPhone 13 screen",
        "description": "Original-quality screen with 3-month warranty",
        "labour_minor": 2_500_000,
        "materials_minor": 1_000_000,
        "currency": "NGN",
        "completion_date": (_dt.date.today() + _dt.timedelta(days=3)).isoformat(),
        "payment_terms": "Single payment held in escrow",
        "service_method": "PRO_TO_CUSTOMER",
    }
    payload.update(overrides)
    return payload


async def category_id(client: httpx.AsyncClient, slug: str) -> str:
    return next(c["id"] for c in (await client.get(f"{API}/categories")).json() if c["slug"] == slug)


async def campus_id(client: httpx.AsyncClient, slug: str) -> str:
    return next(c["id"] for c in (await client.get(f"{API}/campuses")).json() if c["slug"] == slug)


async def relogin(client: httpx.AsyncClient, account: Account) -> Account:
    """Fresh access token (e.g. after moving the test clock past the 15-minute lifetime)."""
    response = await login(client, account.email)
    assert response.status_code == 200, response.text
    return Account(
        id=account.id, email=account.email, access_token=response.json()["access_token"], refresh_cookie=""
    )


async def link_wallet(
    client: httpx.AsyncClient, chain: Any, account: Account, keypair: Any | None = None, *, balance: int = 0
) -> Any:
    """Create the account on the chain double, then link it through the real SEP-53 flow."""
    import base64

    from stellar_sdk import Keypair

    keypair = keypair or Keypair.random()
    if keypair.public_key not in chain.accounts:
        chain.create_account(keypair.public_key, balance=balance)
    challenge = await client.post(
        f"{API}/wallets/challenge", json={"address": keypair.public_key}, headers=account.headers
    )
    assert challenge.status_code == 201, challenge.text
    message = challenge.json()["message"]
    signature = base64.b64encode(keypair.sign_message(message)).decode()
    linked = await client.post(
        f"{API}/wallets",
        json={"address": keypair.public_key, "message": message, "signature": signature},
        headers=account.headers,
    )
    assert linked.status_code == 200, linked.text
    return keypair


# ---------------------------------------------------------------- Issue 6 helpers


@dataclass
class Deal:
    customer: Account
    professional: Account
    professional_id: str
    customer_wallet: Any
    professional_wallet: Any
    booking_id: str
    conversation_id: str


def sign(unsigned_xdr: str, keypair: Any) -> str:
    from stellar_sdk import Network, TransactionEnvelope

    envelope = TransactionEnvelope.from_xdr(unsigned_xdr, Network.TESTNET_NETWORK_PASSPHRASE)
    envelope.sign(keypair)
    return str(envelope.to_xdr())


async def make_deal(
    client: httpx.AsyncClient,
    chain: Any,
    outbox: RecordingEmailSender,
    *,
    balance: int = 10**12,
    wallets: bool = True,
    **quote: Any,
) -> Deal:
    """Customer + verified professional, both wallets linked, a quote accepted: PENDING_PAYMENT."""
    customer = await register(client)
    professional, professional_id = await register_professional(client)
    await verify_email(client, outbox, customer)
    await verify_email(client, outbox, professional)
    customer_wallet = professional_wallet = None
    if wallets:
        customer_wallet = await link_wallet(client, chain, customer, balance=balance)
        professional_wallet = await link_wallet(client, chain, professional)
    conversation_id = await open_conversation(client, customer, professional_id)
    created = await client.post(
        f"{API}/quotes", json=quote_payload(conversation_id, **quote), headers=professional.headers
    )
    assert created.status_code == 201, created.text
    accepted = await client.post(
        f"{API}/quotes/{created.json()['id']}/accept",
        json={"service_address": "Room 214, Moremi Hall"},
        headers=customer.headers,
    )
    assert accepted.status_code == 201, accepted.text
    return Deal(
        customer,
        professional,
        professional_id,
        customer_wallet,
        professional_wallet,
        accepted.json()["booking"]["id"],
        conversation_id,
    )


async def booking(client: httpx.AsyncClient, deal: Deal, account: Account | None = None) -> dict[str, Any]:
    response = await client.get(
        f"{API}/bookings/{deal.booking_id}", headers=(account or deal.customer).headers
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def fund(client: httpx.AsyncClient, chain: Any, reconciler: Any, deal: Deal) -> dict[str, Any]:
    """prepare → sign → submit → ledger closes → reconciler: the booking is FUNDED."""
    prepared = await client.post(
        f"{API}/bookings/{deal.booking_id}/escrow", json={}, headers=deal.customer.headers
    )
    assert prepared.status_code == 200, prepared.text
    escrow_id = prepared.json()["escrow"]["id"]
    submitted = await client.post(
        f"{API}/escrows/{escrow_id}/funding",
        json={"signed_xdr": sign(prepared.json()["unsigned_xdr"], deal.customer_wallet)},
        headers=deal.customer.headers,
    )
    assert submitted.status_code == 200, submitted.text
    chain.close_ledger()
    await reconciler.tick()
    bundle = await booking(client, deal)
    assert bundle["booking"]["status"] == "FUNDED", bundle["escrow"]
    return bundle


async def chain_action(
    client: httpx.AsyncClient,
    chain: Any,
    reconciler: Any,
    path: str,
    account: Account,
    keypair: Any,
    body: dict[str, Any] | None = None,
    *,
    submit_path: str | None = None,
) -> httpx.Response:
    """Prepare at ``path``, sign, submit (same path unless ``submit_path``), confirm, reconcile."""
    prepared = await client.post(f"{API}{path}", json=body or {}, headers=account.headers)
    assert prepared.status_code == 200, prepared.text
    signed = sign(prepared.json()["unsigned_xdr"], keypair)
    submitted = await client.post(
        f"{API}{submit_path or path}", json={"signed_xdr": signed}, headers=account.headers
    )
    assert submitted.status_code == 200, submitted.text
    chain.close_ledger()
    await reconciler.tick()
    return submitted
