"""limit/offset pagination: list endpoints return a JSON array plus X-Total-Count / X-Next-Offset headers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Response

MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class Page:
    limit: int
    offset: int


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Page size")] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000, description="Items to skip")] = 0,
) -> Page:
    return Page(limit=limit, offset=offset)


PageDep = Annotated[Page, Depends(page_params)]


def set_page_headers(response: Response, *, page: Page, total: int, returned: int) -> None:
    response.headers["X-Total-Count"] = str(total)
    next_offset = page.offset + returned
    if returned and next_offset < total:
        response.headers["X-Next-Offset"] = str(next_offset)
