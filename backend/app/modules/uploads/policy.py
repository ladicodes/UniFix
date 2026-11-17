"""Who may read a stored file.

Public files are readable by anyone. Private files are readable by their owner and by
admins. Other modules register additional read rules for their purposes, for example
"conversation members may read message attachments". Registration happens explicitly
in ``app.api.v1`` so that ``uploads`` never imports the modules that use it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.context import AuthContext
from app.modules.uploads.models import FilePurpose, FileVisibility, StoredFile

ReadRule = Callable[[AsyncSession, AuthContext, StoredFile], Awaitable[bool]]

_rules: dict[FilePurpose, ReadRule] = {}


def register_read_rule(purpose: FilePurpose, rule: ReadRule) -> None:
    _rules[purpose] = rule


async def can_read(session: AsyncSession, caller: AuthContext | None, file: StoredFile) -> bool:
    if file.deleted_at is not None:
        return False
    if file.visibility == FileVisibility.PUBLIC.value:
        return True
    if caller is None:
        return False
    if caller.is_admin or caller.user_id == file.owner_user_id:
        return True
    rule = _rules.get(FilePurpose(file.purpose))
    return await rule(session, caller, file) if rule else False
