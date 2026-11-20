"""Mounts every module router under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.bookings import service as bookings_service
from app.modules.bookings.router import router as bookings_router
from app.modules.calls.router import router as calls_router
from app.modules.campuses.router import router as campuses_router
from app.modules.catalog.router import router as catalog_router
from app.modules.chat import service as chat_service
from app.modules.chat.router import router as chat_router
from app.modules.completion import service as completion_service
from app.modules.completion.router import router as completion_router
from app.modules.disputes import service as disputes_service
from app.modules.disputes.router import router as disputes_router
from app.modules.notifications.router import router as notifications_router
from app.modules.payments import reconciler
from app.modules.payments import service as payments_service
from app.modules.payments.router import router as payments_router
from app.modules.professionals.router import router as professionals_router
from app.modules.quotes.router import router as quotes_router
from app.modules.requests import service as requests_service
from app.modules.requests.router import router as requests_router
from app.modules.reviews.router import router as reviews_router
from app.modules.uploads import policy as upload_policy
from app.modules.uploads.models import FilePurpose
from app.modules.uploads.router import router as uploads_router
from app.modules.users.router import router as users_router
from app.modules.wallets import service as wallets_service
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
    payments_router,
    completion_router,
    disputes_router,
    reviews_router,
    notifications_router,
    admin_router,
):
    router.include_router(module_router)

# Explicit cross-module wiring: conversation members may read message attachments.
upload_policy.register_read_rule(FilePurpose.MESSAGE_ATTACHMENT, chat_service.can_read_attachment)
# Eligible professionals may see a service request's photos.
upload_policy.register_read_rule(FilePurpose.REQUEST_MEDIA, requests_service.can_read_request_media)
# Conversations show their active booking.
chat_service.register_booking_lookup(bookings_service.active_bookings_hook)
# Completion photos are visible to the booking's parties and admins.
upload_policy.register_read_rule(FilePurpose.COMPLETION_EVIDENCE, completion_service.can_read_evidence)
# A wallet that is party to a live escrow cannot be unlinked.
wallets_service.register_active_escrow_check(payments_service.wallet_in_active_escrow)
# Confirmed submit_completion / release events update the completion evidence.
reconciler.register_completion_hooks(
    submitted=completion_service.on_submitted, released=completion_service.on_released
)
# Disputes (Issue 7): an active record blocks ordinary settlement and enables concessions; the
# reconciler confirms locks and settlements; overdue disputes escalate (never auto-settle).
payments_service.register_dispute_guard(disputes_service.has_active_dispute)
reconciler.register_dispute_hook("disputed", disputes_service.on_locked)
reconciler.register_dispute_hook("settled", disputes_service.on_settled)
reconciler.register_periodic(disputes_service.escalate_overdue)
# Notifications (Issue 8): 24 h deadline warnings and dispute SLA reminders, sent once each.
reconciler.register_periodic(payments_service.warn_deadlines)
reconciler.register_periodic(disputes_service.remind_sla)
upload_policy.register_read_rule(FilePurpose.DISPUTE_EVIDENCE, disputes_service.can_read_evidence)
