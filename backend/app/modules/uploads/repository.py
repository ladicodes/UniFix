from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.uploads.models import StoredFile


async def get(session: AsyncSession, file_id: uuid.UUID) -> StoredFile | None:
    return await session.get(StoredFile, file_id)


async def get_many(session: AsyncSession, file_ids: Sequence[uuid.UUID]) -> Sequence[StoredFile]:
    if not file_ids:
        return []
    return (await session.execute(select(StoredFile).where(StoredFile.id.in_(file_ids)))).scalars().all()


def add(session: AsyncSession, file: StoredFile) -> None:
    session.add(file)
