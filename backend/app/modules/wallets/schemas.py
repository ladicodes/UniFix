from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.core.schemas import APIModel, ResponseModel


class ChallengeIn(APIModel):
    address: str = Field(min_length=56, max_length=56)


class ChallengeOut(ResponseModel):
    message: str
    nonce: str
    expires_at: datetime


class VerifyWalletIn(APIModel):
    address: str = Field(min_length=56, max_length=56)
    message: str = Field(min_length=1, max_length=1000)
    signature: str = Field(min_length=1, max_length=200, description="Base64 SEP-53 signature from Freighter")


class WalletOut(ResponseModel):
    id: uuid.UUID
    address: str
    network: str
    verified_at: datetime
    is_primary: bool
    account_exists: bool | None = Field(description="null when the network could not be reached")
    has_escrow_trustline: bool | None
