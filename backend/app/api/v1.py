"""Mounts every module router under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.bookings import service as bookings_service
from app.modules.bookings.router import router as bookings_router
from app.modules.calls.router import router as calls_router
from app.modules.campuses.router import router as campuses_router
from app.modules.catalog.router import router as catalog_router
from app.modules.chat import service as chat_service
from app.modules.chat.router import router as chat_router
from app.modules.professionals.router import router as professionals_router
from app.modules.quotes.router import router as quotes_router
from app.modules.requests import service as requests_service
from app.modules.requests.router import router as requests_router
from app.modules.uploads import policy as upload_policy
from app.modules.uploads.models import FilePurpose
from app.modules.uploads.router import router as uploads_router
from app.modules.users.router import router as users_router
from app.modules.wallets.router import router as wallets_router

router = APIRouter()
for module_router in (
    auth_router,
    users_router,
    campuses_router,
    catalog_router,
    professionals_router,
    uploads_router,
    chat_router,
    calls_router,
    requests_router,
    quotes_router,
    bookings_router,
    wallets_router,
):
    router.include_router(module_router)

# Explicit cross-module wiring: conversation members may read message attachments.
upload_policy.register_read_rule(FilePurpose.MESSAGE_ATTACHMENT, chat_service.can_read_attachment)
# Eligible professionals may see a service request's photos.
upload_policy.register_read_rule(FilePurpose.REQUEST_MEDIA, requests_service.can_read_request_media)
# Conversations show their active booking.
chat_service.register_booking_lookup(bookings_service.active_bookings_hook)
