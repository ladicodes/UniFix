"""Mounts every module router under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)
