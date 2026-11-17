"""Response assembly that spans several modules (kept in the API layer so modules stay acyclic)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.campuses import service as campuses
from app.modules.campuses.schemas import CampusOut
from app.modules.professionals import repository as professionals
from app.modules.uploads import repository as uploads_repository
from app.modules.uploads import service as uploads
from app.modules.users.models import User
from app.modules.users.schemas import UserOut
from app.modules.wallets import service as wallets


async def user_out(session: AsyncSession, user: User) -> UserOut:
    campus = await campuses.get_active(session, user.campus_id) if user.campus_id else None
    avatar = await uploads_repository.get(session, user.avatar_file_id) if user.avatar_file_id else None
    out = UserOut.from_user(
        user,
        campus=CampusOut.model_validate(campus) if campus else None,
        professional_id=await professionals.id_for_user(session, user.id),
        avatar_url=uploads.public_url(avatar),
    )
    out.wallet_address = await wallets.primary_address(session, user.id)
    out.wallet_verified = out.wallet_address is not None
    return out
