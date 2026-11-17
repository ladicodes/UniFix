"""Campuses, categories, professional onboarding and profile authorization (PostgreSQL)."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import text

from app.core.container import Services
from tests.support import (
    API,
    COOKIE_HEADERS,
    PASSWORD,
    create_admin_account,
    professional_payload,
    register,
    register_professional,
)

PRIVATE_KEYS = {"latitude", "longitude", "verifications", "is_listed", "email", "phone"}


async def test_categories_and_campuses_are_public(client: httpx.AsyncClient, seeded: Services) -> None:
    categories = (await client.get(f"{API}/categories")).json()
    slugs = {item["slug"] for item in categories}
    assert {"phone-repair", "laptop-repair", "laundry", "tailor", "electrician"} <= slugs
    phone = next(item for item in categories if item["slug"] == "phone-repair")
    electronics = next(item for item in categories if item["slug"] == "electronics")
    assert phone["parent_id"] == electronics["id"]
    campuses = (await client.get(f"{API}/campuses", params={"q": "lagos"})).json()
    assert {item["slug"] for item in campuses} == {"unilag", "lasu"}
    assert set(campuses[0]) == {"id", "slug", "name", "short_name", "city", "state", "country"}


async def test_admin_manages_categories_and_campuses(client: httpx.AsyncClient, seeded: Services) -> None:
    admin = await create_admin_account(client, seeded)
    customer = await register(client)
    body = {"slug": "hair-braiding", "name": "Hair braiding", "description": "Braids and styling"}
    assert (
        await client.post(f"{API}/admin/categories", json=body, headers=customer.headers)
    ).status_code == 403
    created = await client.post(f"{API}/admin/categories", json=body, headers=admin.headers)
    assert created.status_code == 201
    duplicate = await client.post(f"{API}/admin/categories", json=body, headers=admin.headers)
    assert duplicate.status_code == 409
    category_id = created.json()["id"]
    disabled = await client.patch(
        f"{API}/admin/categories/{category_id}", json={"is_active": False}, headers=admin.headers
    )
    assert disabled.json()["is_active"] is False
    assert "hair-braiding" not in {item["slug"] for item in (await client.get(f"{API}/categories")).json()}
    campus = await client.post(
        f"{API}/admin/campuses",
        json={"slug": "futa", "name": "Federal University of Technology, Akure", "short_name": "FUTA",
              "city": "Akure", "country": "NG", "latitude": "7.3000", "longitude": "5.1350"},
        headers=admin.headers,
    )  # fmt: skip
    assert campus.status_code == 201
    assert campus.json()["latitude"] == "7.300000"


async def test_register_professional_with_profile_in_one_step(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    account, professional_id = await register_professional(client)
    assert professional_id is not None
    profile = await client.get(f"{API}/professionals/me", headers=account.headers)
    assert profile.status_code == 200
    body = profile.json()
    assert body["category"] == "phone-repair"
    assert body["verification_status"] == "NOT_SUBMITTED"
    assert body["verifications"] == []
    assert body["starting_price_minor"] == 1_500_000


async def test_registration_is_atomic_when_profile_is_invalid(
    client: httpx.AsyncClient, seeded: Services, unique_email: str
) -> None:
    response = await client.post(
        f"{API}/auth/register",
        json={"name": "Bad Pro", "email": unique_email, "password": PASSWORD, "role": "PROFESSIONAL",
              "country": "NG", "professional": professional_payload(category_slug="no-such-category")},
        headers=COOKIE_HEADERS,
    )  # fmt: skip
    assert response.status_code == 400
    assert response.json()["code"] == "UNKNOWN_CATEGORY"
    async with seeded.session_factory() as session:
        count = await session.scalar(text("SELECT count(*) FROM users WHERE email = :e"), {"e": unique_email})
    assert count == 0


async def test_customer_cannot_send_professional_object(client: httpx.AsyncClient, seeded: Services) -> None:
    response = await client.post(
        f"{API}/auth/register",
        json={"name": "Ada", "email": "c@example.com", "password": PASSWORD, "role": "CUSTOMER",
              "country": "NG", "professional": professional_payload()},
        headers=COOKIE_HEADERS,
    )  # fmt: skip
    assert response.status_code == 422


async def test_register_with_campus_and_update_campus(client: httpx.AsyncClient, seeded: Services) -> None:
    unilag = next(c for c in (await client.get(f"{API}/campuses")).json() if c["slug"] == "unilag")
    account = await register(client, campus_id=unilag["id"])
    assert (await client.get(f"{API}/auth/me", headers=account.headers)).json()["campus"]["slug"] == "unilag"
    bad = await client.patch(f"{API}/auth/me", json={"campus_id": str(uuid.uuid4())}, headers=account.headers)
    assert bad.status_code == 400
    cleared = await client.patch(f"{API}/auth/me", json={"campus_id": None}, headers=account.headers)
    assert cleared.json()["campus"] is None


async def test_create_profile_later_and_only_once(client: httpx.AsyncClient, seeded: Services) -> None:
    account = await register(client, role="PROFESSIONAL")
    created = await client.post(
        f"{API}/professionals/me", json=professional_payload(), headers=account.headers
    )
    assert created.status_code == 201
    again = await client.post(f"{API}/professionals/me", json=professional_payload(), headers=account.headers)
    assert again.status_code == 409
    assert again.json()["code"] == "PROFILE_EXISTS"


async def test_customers_cannot_create_or_edit_professional_profiles(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    _, professional_id = await register_professional(client)
    customer = await register(client)
    create = await client.post(
        f"{API}/professionals/me", json=professional_payload(), headers=customer.headers
    )
    assert create.status_code == 403
    edit = await client.patch(
        f"{API}/professionals/{professional_id}", json={"headline": "Hijacked"}, headers=customer.headers
    )
    assert edit.status_code == 403


async def test_professional_cannot_edit_another_professionals_profile(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    _, victim_id = await register_professional(client)
    attacker, _ = await register_professional(client, name="Other Pro")
    response = await client.patch(
        f"{API}/professionals/{victim_id}", json={"headline": "Hijacked headline"}, headers=attacker.headers
    )
    assert response.status_code == 404
    assert (await client.get(f"{API}/professionals/{victim_id}")).json()["headline"] != "Hijacked headline"


async def test_owner_updates_profile_but_cannot_claim_verification_or_ratings(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    account, professional_id = await register_professional(client)
    unilag = next(c for c in (await client.get(f"{API}/campuses")).json() if c["slug"] == "unilag")
    updated = await client.patch(
        f"{API}/professionals/{professional_id}",
        json={"headline": "Screens and batteries", "availability": "NOW", "campus_ids": [unilag["id"]],
              "category_slugs": ["laptop-repair"], "latitude": "6.517412", "longitude": "3.391288"},
        headers=account.headers,
    )  # fmt: skip
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["availability"] == "NOW"
    assert body["campuses"][0]["short_name"] == "UNILAG"
    assert set(body["categories"]) == {"phone-repair", "laptop-repair"}
    assert body["latitude"] == "6.520000"  # rounded to ~1 km before storage
    for forbidden in ({"verification_status": "VERIFIED"}, {"rating": 5}, {"completed_jobs": 99}):
        response = await client.patch(
            f"{API}/professionals/{professional_id}", json=forbidden, headers=account.headers
        )
        assert response.status_code == 422


async def test_public_profile_hides_private_fields(client: httpx.AsyncClient, seeded: Services) -> None:
    account, professional_id = await register_professional(client)
    await client.patch(
        f"{API}/professionals/{professional_id}",
        json={"latitude": "6.5", "longitude": "3.4"},
        headers=account.headers,
    )
    public = (await client.get(f"{API}/professionals/{professional_id}")).json()
    assert PRIVATE_KEYS.isdisjoint(public)
    assert public["name"] == "Tunde Bakare"
    assert public["verification"] == {"identity": False, "trade": False, "phone": False}


async def test_unlisted_and_suspended_professionals_are_hidden(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    account, professional_id = await register_professional(client)
    await client.patch(
        f"{API}/professionals/{professional_id}", json={"is_listed": False}, headers=account.headers
    )
    assert (await client.get(f"{API}/professionals/{professional_id}")).status_code == 404
    assert (
        await client.get(f"{API}/professionals/{professional_id}", headers=account.headers)
    ).status_code == 200
    assert (await client.get(f"{API}/professionals")).json() == []

    await client.patch(
        f"{API}/professionals/{professional_id}", json={"is_listed": True}, headers=account.headers
    )
    admin = await create_admin_account(client, seeded)
    await client.patch(
        f"{API}/admin/users/{account.id}/status",
        json={"status": "SUSPENDED", "reason": "test"},
        headers=admin.headers,
    )
    assert (await client.get(f"{API}/professionals/{professional_id}")).status_code == 404
    assert (await client.get(f"{API}/professionals")).json() == []
    assert (
        await client.get(f"{API}/professionals/{professional_id}", headers=admin.headers)
    ).status_code == 200
