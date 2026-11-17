"""Discovery search, filters, sorting and pagination against real PostgreSQL data."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import update

from app.core.container import Services
from app.modules.professionals.models import ProfessionalProfile
from tests.support import API, register_professional


async def _campus_id(client: httpx.AsyncClient, slug: str) -> str:
    return next(c["id"] for c in (await client.get(f"{API}/campuses")).json() if c["slug"] == slug)


async def _set(services: Services, professional_id: str, **values: Any) -> None:
    async with services.session_factory() as session:
        target = ProfessionalProfile.id == uuid.UUID(professional_id)
        await session.execute(update(ProfessionalProfile).where(target).values(**values))
        await session.commit()


async def _catalogue(client: httpx.AsyncClient, services: Services) -> dict[str, str]:
    unilag, ui = await _campus_id(client, "unilag"), await _campus_id(client, "ui")
    _, phone = await register_professional(
        client, name="Tunde Phones", campus_ids=[unilag], skills=["iPhone screens"], years_experience=2
    )
    _, laptop = await register_professional(
        client, name="Bisi Laptops", category_slug="laptop-repair", campus_ids=[unilag],
        skills=["MacBook keyboards"], availability="NOW", years_experience=9,
    )  # fmt: skip
    _, laundry = await register_professional(
        client, name="Kemi Laundry", category_slug="laundry", campus_ids=[ui], city="Ibadan",
        area="Agbowo", skills=["ironing"], availability="THIS_WEEK", years_experience=4,
    )  # fmt: skip
    await _set(services, phone, rating_avg=4.9, rating_count=2, completed_jobs=3)
    await _set(services, laptop, rating_avg=4.6, rating_count=40, completed_jobs=55)
    await _set(
        services, laundry, rating_avg=4.0, rating_count=10, completed_jobs=12, verification_status="VERIFIED"
    )
    return {"phone": phone, "laptop": laptop, "laundry": laundry}


def _ids(response: httpx.Response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()]


async def test_filters(client: httpx.AsyncClient, seeded: Services) -> None:
    pros = await _catalogue(client, seeded)
    get = client.get
    assert set(_ids(await get(f"{API}/professionals", params={"category": "phone-repair"}))) == {
        pros["phone"]
    }
    assert set(_ids(await get(f"{API}/professionals", params={"category": "electronics"}))) == {
        pros["phone"],
        pros["laptop"],
    }  # parent category includes its sub-services
    assert set(_ids(await get(f"{API}/professionals", params={"campus": "ui"}))) == {pros["laundry"]}
    assert set(_ids(await get(f"{API}/professionals", params={"city": "ibadan"}))) == {pros["laundry"]}
    assert set(_ids(await get(f"{API}/professionals", params={"availability": "NOW"}))) == {pros["laptop"]}
    assert set(_ids(await get(f"{API}/professionals", params={"availability": "TODAY"}))) == {
        pros["phone"],
        pros["laptop"],
    }
    assert set(_ids(await get(f"{API}/professionals", params={"min_rating": 4.5}))) == {
        pros["phone"],
        pros["laptop"],
    }
    assert _ids(await get(f"{API}/professionals", params={"verified_only": "true"})) == [pros["laundry"]]
    assert _ids(await get(f"{API}/professionals", params={"category": "unknown-slug"})) == []
    assert _ids(await get(f"{API}/professionals", params={"campus": "unknown-campus"})) == []


async def test_full_text_and_name_search(client: httpx.AsyncClient, seeded: Services) -> None:
    pros = await _catalogue(client, seeded)
    assert _ids(await client.get(f"{API}/professionals", params={"q": "macbook"})) == [pros["laptop"]]
    assert _ids(await client.get(f"{API}/professionals", params={"q": "Kemi"})) == [pros["laundry"]]
    hostile = await client.get(f"{API}/professionals", params={"q": "'; DROP TABLE users; -- & | !"})
    assert hostile.status_code == 200


async def test_sorting(client: httpx.AsyncClient, seeded: Services) -> None:
    pros = await _catalogue(client, seeded)
    # BEST is Bayesian: 4.6 over 40 reviews outranks 4.9 over 2 reviews.
    assert _ids(await client.get(f"{API}/professionals"))[0] == pros["laptop"]
    assert _ids(await client.get(f"{API}/professionals", params={"sort": "MOST_JOBS"})) == [
        pros["laptop"],
        pros["laundry"],
        pros["phone"],
    ]
    assert _ids(await client.get(f"{API}/professionals", params={"sort": "EXPERIENCE"}))[0] == pros["laptop"]
    near_ibadan = await client.get(
        f"{API}/professionals", params={"sort": "NEAREST", "lat": 7.44, "lng": 3.90}
    )
    assert _ids(near_ibadan)[0] == pros["laundry"]
    distances = [item["distance_km"] for item in near_ibadan.json()]
    assert distances[0] < 5 < distances[1]
    assert all(item["distance_km"] is None for item in (await client.get(f"{API}/professionals")).json())


async def test_pagination_headers(client: httpx.AsyncClient, seeded: Services) -> None:
    await _catalogue(client, seeded)
    first = await client.get(f"{API}/professionals", params={"limit": 2})
    assert len(first.json()) == 2
    assert first.headers["x-total-count"] == "3"
    assert first.headers["x-next-offset"] == "2"
    last = await client.get(f"{API}/professionals", params={"limit": 2, "offset": 2})
    assert len(last.json()) == 1
    assert "x-next-offset" not in last.headers
    assert (await client.get(f"{API}/professionals", params={"limit": 101})).status_code == 422


async def test_unknown_query_parameters_use_snake_case(client: httpx.AsyncClient, seeded: Services) -> None:
    await _catalogue(client, seeded)
    response = await client.get(f"{API}/professionals", params={"minRating": 5})  # camelCase is not a filter
    assert len(response.json()) == 3
