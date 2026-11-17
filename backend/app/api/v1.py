"""Mounts every module router under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.campuses.router import router as campuses_router
from app.modules.catalog.router import router as catalog_router
from app.modules.professionals.router import router as professionals_router
from app.modules.uploads.router import router as uploads_router
from app.modules.users.router import router as users_router

router = APIRouter()
for module_router in (
    auth_router,
    users_router,
    campuses_router,
    catalog_router,
    professionals_router,
    uploads_router,
):
    router.include_router(module_router)
