from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.wallets.models import Wallet, WalletChallenge


def add(session: AsyncSession, row: Wallet | WalletChallenge) -> None:
    session.add(row)


async def consume_challenge(
    session: AsyncSession, *, user_id: uuid.UUID, address: str, network: str, message: str, now: datetime
) -> WalletChallenge | None:
    """Atomic single use: only one caller can flip ``used_at`` on a live challenge."""
    result = await session.execute(
        update(WalletChallenge)
        .where(
            WalletChallenge.user_id == user_id,
            WalletChallenge.address == address,
            WalletChallenge.network == network,
            WalletChallenge.message == message,
            WalletChallenge.used_at.is_(None),
            WalletChallenge.expires_at > now,
        )
        .values(used_at=now)
        .returning(WalletChallenge)
    )
    return result.scalar_one_or_none()


async def active_by_address(session: AsyncSession, network: str, address: str) -> Wallet | None:
    return (
        await session.execute(
            select(Wallet).where(
                Wallet.network == network, Wallet.address == address, Wallet.revoked_at.is_(None)
            )
        )
    ).scalar_one_or_none()


async def active_for_user(session: AsyncSession, user_id: uuid.UUID, network: str) -> Sequence[Wallet]:
    return (
        (
            await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id, Wallet.network == network, Wallet.revoked_at.is_(None))
                .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def get(session: AsyncSession, wallet_id: uuid.UUID, *, for_update: bool = False) -> Wallet | None:
    statement = select(Wallet).where(Wallet.id == wallet_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def primary(session: AsyncSession, user_id: uuid.UUID, network: str | None) -> Wallet | None:
    statement = select(Wallet).where(
        Wallet.user_id == user_id, Wallet.is_primary.is_(True), Wallet.revoked_at.is_(None)
    )
    if network is not None:
        statement = statement.where(Wallet.network == network)
    return (await session.execute(statement.limit(1))).scalars().first()
