"""Idempotent reference data: service categories and an initial set of Nigerian campuses.

Inserts missing rows by slug and never overwrites existing rows, so admin edits survive re-seeding.
Campus coordinates are approximate campus centroids, used only for "nearest" sorting.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.campuses.models import Campus
from app.modules.catalog.models import ServiceCategory

# (slug, name, parent_slug, description)
CATEGORIES: list[tuple[str, str, str | None, str]] = [
    ("electronics", "Electronics & gadgets", None, "Phones, laptops and other devices"),
    ("phone-repair", "Phone repair", "electronics", "Screens, batteries, charging ports, software"),
    ("laptop-repair", "Laptop repair", "electronics", "Hardware faults, upgrades, OS reinstalls"),
    ("electronics-repair", "Electronics repair", "electronics", "TVs, speakers, chargers and small devices"),
    ("home", "Home & hostel", None, "Repairs and maintenance where you live"),
    ("electrician", "Electrician", "home", "Wiring, sockets, lighting, inverters"),
    ("plumber", "Plumber", "home", "Leaks, taps, toilets, water pumps"),
    ("ac-technician", "AC technician", "home", "Installation, servicing and gas refills"),
    ("generator", "Generator repair", "home", "Servicing and repair of generators"),
    ("carpenter", "Carpenter", "home", "Furniture, doors, wardrobes"),
    ("painter", "Painter", "home", "Interior and exterior painting"),
    ("everyday", "Everyday services", None, "Services students use every week"),
    ("laundry", "Laundry", "everyday", "Washing, ironing, dry cleaning"),
    ("cleaner", "Cleaning", "everyday", "Room, apartment and move-out cleaning"),
    ("tailor", "Tailoring", "everyday", "Alterations, repairs and custom clothing"),
    ("mechanic", "Mechanic", None, "Cars, motorcycles and bicycles"),
]

# (slug, name, short_name, city, state, lat, lng)
CAMPUSES: list[tuple[str, str, str, str, str, str, str]] = [
    ("unilag", "University of Lagos", "UNILAG", "Lagos", "Lagos", "6.515800", "3.389700"),
    ("lasu", "Lagos State University", "LASU", "Lagos", "Lagos", "6.469800", "3.199300"),
    ("ui", "University of Ibadan", "UI", "Ibadan", "Oyo", "7.444300", "3.899500"),
    ("oau", "Obafemi Awolowo University", "OAU", "Ile-Ife", "Osun", "7.518500", "4.527400"),
    ("unn", "University of Nigeria, Nsukka", "UNN", "Nsukka", "Enugu", "6.867600", "7.408700"),
    ("abu", "Ahmadu Bello University", "ABU", "Zaria", "Kaduna", "11.153000", "7.653800"),
    ("uniben", "University of Benin", "UNIBEN", "Benin City", "Edo", "6.398800", "5.610500"),
    ("covenant", "Covenant University", "CU", "Ota", "Ogun", "6.671800", "3.158100"),
]


async def seed(session: AsyncSession) -> tuple[int, int]:
    created_categories = 0
    ids: dict[str, uuid.UUID | None] = {}
    for sort_order, (slug, name, parent_slug, description) in enumerate(CATEGORIES):
        statement = (
            insert(ServiceCategory)
            .values(
                slug=slug,
                name=name,
                description=description,
                sort_order=sort_order,
                parent_id=ids.get(parent_slug) if parent_slug else None,
            )
            .on_conflict_do_nothing(index_elements=["slug"])
            .returning(ServiceCategory.id)
        )
        inserted = (await session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            created_categories += 1
        ids[slug] = inserted or await session.scalar(
            select(ServiceCategory.id).where(ServiceCategory.slug == slug)
        )
    created_campuses = 0
    for slug, name, short_name, city, state, lat, lng in CAMPUSES:
        statement = (
            insert(Campus)
            .values(
                slug=slug,
                name=name,
                short_name=short_name,
                city=city,
                state=state,
                country="NG",
                latitude=Decimal(lat),
                longitude=Decimal(lng),
            )
            .on_conflict_do_nothing(index_elements=["slug"])
            .returning(Campus.id)
        )
        if (await session.execute(statement)).scalar_one_or_none() is not None:
            created_campuses += 1
    await session.commit()
    return created_categories, created_campuses
