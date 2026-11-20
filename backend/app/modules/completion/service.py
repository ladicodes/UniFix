"""Completion evidence and its on-chain declaration (ARCHITECTURE §8.2, STELLAR_ESCROW_DESIGN §5).

Evidence (notes, checklist, photos) is recorded off-chain first as a canonical document; its
SHA-256 is what the professional signs into ``submit_completion``. The booking becomes
COMPLETION_SUBMITTED only when the reconciler confirms that call on-chain.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.errors import Conflict, Forbidden, NotFound
from app.modules.auth.context import AuthContext
from app.modules.bookings import service as bookings
from app.modules.bookings.models import BookingStatus
from app.modules.completion.models import CompletionFile, CompletionSubmission, SubmissionStatus
from app.modules.completion.schemas import (
    ChecklistItem,
    CompletionOut,
    PrepareCompletionIn,
    PreparedCompletionOut,
)
from app.modules.payments import repository as payments_repository
from app.modules.payments import service as payments
from app.modules.payments.models import EscrowState, TxKind
from app.modules.payments.schemas import EscrowOut
from app.modules.quotes import agreement as agreements
from app.modules.stellar import contract
from app.modules.stellar.context import StellarContext
from app.modules.stellar.contract import Function
from app.modules.uploads import repository as uploads_repository
from app.modules.uploads import service as uploads
from app.modules.uploads.models import FilePurpose, StoredFile

EVIDENCE_SCHEMA = "unifix.completion-evidence.v1"


async def _files(session: AsyncSession, submission_id: uuid.UUID) -> list[StoredFile]:
    ids = (
        (
            await session.execute(
                select(CompletionFile.file_id).where(CompletionFile.submission_id == submission_id)
            )
        )
        .scalars()
        .all()
    )
    return list(await uploads_repository.get_many(session, list(ids)))


async def _out(session: AsyncSession, services: Services, row: CompletionSubmission) -> CompletionOut:
    return CompletionOut(
        id=row.id,
        booking_id=row.booking_id,
        notes=row.notes,
        checklist=[ChecklistItem.model_validate(item) for item in row.checklist],
        photos=[uploads.file_ref(services, f) for f in await _files(session, row.id)],
        evidence_hash=row.evidence_hash,
        evidence_json=row.evidence_canonical_json,
        status=row.status,
        prepared_at=row.prepared_at,
        submitted_at=row.submitted_at,
    )


async def prepare(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    booking_id: uuid.UUID,
    data: PrepareCompletionIn,
) -> PreparedCompletionOut:
    booking, professional_user_id = await bookings.visible_booking(
        session, services, caller, booking_id, for_update=True
    )
    if caller.user_id != professional_user_id:
        raise Forbidden("Only the booking's professional can submit completion.", code="ROLE_FORBIDDEN")
    if booking.status not in {BookingStatus.FUNDED.value, BookingStatus.IN_PROGRESS.value}:
        raise Conflict(
            "Completion can be submitted for funded or in-progress bookings.", code="COMPLETION_NOT_ALLOWED"
        )
    escrow = await payments_repository.escrow_for_booking(session, booking.id, for_update=True)
    now = services.clock.now()
    if escrow is None or escrow.state != EscrowState.FUNDED.value:
        raise Conflict("The escrow is not funded.", code="COMPLETION_NOT_ALLOWED")
    if int(now.timestamp()) >= escrow.refund_after:
        raise Conflict(
            "The refund deadline has passed; ask the customer for an extension.", code="DEADLINE_PASSED"
        )
    photos = await uploads.require_owned(
        session, caller, data.photo_file_ids, FilePurpose.COMPLETION_EVIDENCE
    )
    document = {
        "schema": EVIDENCE_SCHEMA,
        "booking_id": str(booking.id),
        "agreement_hash": escrow.agreement_hash,
        "submitted_by": str(caller.user_id),
        "notes": data.notes,
        "checklist": [item.model_dump() for item in data.checklist],
        "photos": sorted(
            ({"file_id": str(f.id), "sha256": f.sha256} for f in photos), key=lambda p: p["file_id"]
        ),
        "prepared_at": now.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    canonical = agreements.canonicalize(document)
    evidence_hash = agreements.digest(canonical)
    await session.execute(
        update(CompletionSubmission)
        .where(
            CompletionSubmission.booking_id == booking.id,
            CompletionSubmission.status == SubmissionStatus.PREPARED.value,
        )
        .values(status=SubmissionStatus.SUPERSEDED.value, decided_at=now)
    )
    row = CompletionSubmission(
        booking_id=booking.id,
        submitted_by=caller.user_id,
        notes=data.notes,
        checklist=document["checklist"],
        evidence_canonical_json=canonical,
        evidence_hash=evidence_hash,
        status=SubmissionStatus.PREPARED.value,
        prepared_at=now,
    )
    session.add(row)
    await session.flush()
    for photo in photos:
        session.add(CompletionFile(submission_id=row.id, file_id=photo.id))
    tx = await payments.prepare_tx(
        session,
        services,
        stellar,
        escrow=escrow,
        kind=TxKind.SUBMIT_COMPLETION,
        source=escrow.professional_wallet,
        function=Function.SUBMIT_COMPLETION,
        args=contract.submit_completion_args(escrow.escrow_key, bytes.fromhex(evidence_hash)),
        requested_by=caller.user_id,
        data={"evidence_hash": evidence_hash},
        replace_prepared=True,
    )
    await session.commit()
    return PreparedCompletionOut(
        submission=await _out(session, services, row),
        escrow=await payments.present(session, stellar, escrow),
        unsigned_xdr=tx.unsigned_envelope_xdr,
        tx_hash=tx.tx_hash,
        valid_until=tx.valid_until,
    )


async def submit(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    booking_id: uuid.UUID,
    signed_xdr: str,
) -> EscrowOut:
    escrow = await payments_repository.escrow_for_booking(session, booking_id)
    if escrow is None:
        raise NotFound("Booking not found.")
    return await payments.submit_signed(
        session,
        services,
        stellar,
        caller,
        escrow_id=escrow.id,
        kind=TxKind.SUBMIT_COMPLETION,
        signed_xdr=signed_xdr,
    )


async def latest(
    session: AsyncSession, services: Services, caller: AuthContext, booking_id: uuid.UUID
) -> CompletionOut | None:
    await bookings.visible_booking(session, services, caller, booking_id)
    row = (
        await session.execute(
            select(CompletionSubmission)
            .where(
                CompletionSubmission.booking_id == booking_id,
                CompletionSubmission.status != SubmissionStatus.SUPERSEDED.value,
            )
            .order_by(CompletionSubmission.prepared_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return await _out(session, services, row) if row else None


# ---------------------------------------------------------------- reconciler hooks


async def on_submitted(
    session: AsyncSession, booking_id: uuid.UUID, evidence_hash: str | None, now: datetime
) -> None:
    """``submit_completion`` confirmed: the matching evidence becomes SUBMITTED."""
    await session.execute(
        update(CompletionSubmission)
        .where(
            CompletionSubmission.booking_id == booking_id,
            CompletionSubmission.status == SubmissionStatus.PREPARED.value,
            CompletionSubmission.evidence_hash == evidence_hash,
        )
        .values(status=SubmissionStatus.SUBMITTED.value, submitted_at=now)
    )
    await session.execute(
        update(CompletionSubmission)
        .where(
            CompletionSubmission.booking_id == booking_id,
            CompletionSubmission.status == SubmissionStatus.PREPARED.value,
        )
        .values(status=SubmissionStatus.SUPERSEDED.value, decided_at=now)
    )


async def on_released(session: AsyncSession, booking_id: uuid.UUID, _: str | None, now: datetime) -> None:
    await _decide(session, booking_id, SubmissionStatus.APPROVED, now)


async def on_disputed(session: AsyncSession, booking_id: uuid.UUID, now: datetime) -> None:
    await _decide(session, booking_id, SubmissionStatus.DISPUTED, now)


async def _decide(
    session: AsyncSession, booking_id: uuid.UUID, status: SubmissionStatus, now: datetime
) -> None:
    await session.execute(
        update(CompletionSubmission)
        .where(
            CompletionSubmission.booking_id == booking_id,
            CompletionSubmission.status == SubmissionStatus.SUBMITTED.value,
        )
        .values(status=status.value, decided_at=now)
    )


async def can_read_evidence(session: AsyncSession, caller: AuthContext, file: object) -> bool:
    """Upload read rule: the booking's two parties and admins may see completion photos."""
    file_id = getattr(file, "id", None)
    if file_id is None:
        return False
    rows: Sequence[uuid.UUID] = (
        (
            await session.execute(
                select(CompletionSubmission.booking_id)
                .join(CompletionFile, CompletionFile.submission_id == CompletionSubmission.id)
                .where(CompletionFile.file_id == file_id)
            )
        )
        .scalars()
        .all()
    )
    for booking_id in rows:
        if caller.is_admin or await bookings.is_party(session, caller, booking_id):
            return True
    return False
