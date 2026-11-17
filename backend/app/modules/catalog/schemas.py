from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.schemas import APIModel, ResponseModel
from app.modules.campuses.schemas import Slug

CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class CategoryOut(ResponseModel):
    id: uuid.UUID
    slug: str
    name: str
    parent_id: uuid.UUID | None
    description: str | None


class AdminCategoryOut(CategoryOut):
    is_active: bool
    sort_order: int


class CategoryCreateIn(APIModel):
    slug: Slug
    name: CategoryName
    parent_id: uuid.UUID | None = None
    description: Description | None = None
    sort_order: Annotated[int, Field(ge=0, le=10_000)] = 0


class CategoryUpdateIn(APIModel):
    name: CategoryName | None = None
    parent_id: uuid.UUID | None = None
    description: Description | None = None
    sort_order: Annotated[int, Field(ge=0, le=10_000)] | None = None
    is_active: bool | None = None
