"""Escrow orchestration: prepare → (wallet signs) → submit, for every chain action.

Rules (STELLAR_ESCROW_DESIGN §6, §9; ARCHITECTURE §8.2):

* The backend builds and simulates transactions with the **user's wallet as source**; the user
  signs in Freighter. Only ``fund`` carries the operator's co-signature (an auth entry).
* A submitted envelope must hash to exactly the prepared transaction (``TX_MISMATCH``).
* Nothing here changes a booking's financial state. Confirmation comes only from the reconciler,
  from verified on-chain events (``payments.reconciler``).
* The amount comes only from the agreement and the locked rate; no client amount is accepted.
* Lock order everywhere: booking → escrow → chain transaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from stellar_sdk import TransactionEnvelope
from stellar_sdk import xdr as stellar_xdr

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.modules.audit import service as audit
from app.modules.auth.context import AuthContext
from app.modules.bookings import service as bookings
from app.modules.bookings.models import Booking, BookingStatus, TimelineActor
from app.modules.chat import service as chat
from app.modules.notifications import service as notifications
from app.modules.notifications.models import NotificationType
from app.modules.payments import fx, repository, terms
from app.modules.payments.models import (
    CancellationRequest,
    CancellationStatus,
    ChainTransaction,
    Escrow,
    EscrowState,
    Reconciliation,
    TxKind,
    TxStatus,
)
from app.modules.payments.schemas import (
    AssetOut,
    CancellationRequestOut,
    EscrowOut,
    EscrowTransactionOut,
    FiatOut,
    FxOut,
    PreparedOut,
    ReceiptOut,
)
from app.modules.quotes import agreement as agreements
from app.modules.quotes import repository as quotes_repository
from app.modules.stellar import contract, signing
from app.modules.stellar.context import StellarContext
from app.modules.stellar.contract import Function
from app.modules.stellar.errors import ChainUnavailable, TxExpired
from app.modules.wallets import service as wallets

logger = logging.getLogger(__name__)

CANCELLATION_WINDOW = timedelta(hours=48)
SEND_RETRIES = 3
_send_backoff_seconds = 0.25  # module-level so tests can shorten it

# Issue 7 registers a guard: an open dispute record blocks ordinary release/refund preparation.
DisputeGuard = Callable[[AsyncSession, uuid.UUID], Awaitable[bool]]
_dispute_open: DisputeGuard | None = None


def register_dispute_guard(guard: DisputeGuard) -> None:
    global _dispute_open
    _dispute_open = guard


async def _has_open_dispute(session: AsyncSession, booking_id: uuid.UUID) -> bool:
    return _dispute_open is not None and await _dispute_open(session, booking_id)


# ---------------------------------------------------------------- presentation


_IN_FLIGHT_VALUES = {s.value for s in (TxStatus.PREPARED, TxStatus.SUBMITTED, TxStatus.PENDING)}
_DISPLAY_STATUS = {
    TxStatus.PREPARED.value: "PENDING",
    TxStatus.SUBMITTED.value: "PENDING",
    TxStatus.PENDING.value: "PENDING",
}


def _units(value: Decimal | int | None) -> str | None:
    return None if value is None else str(int(value))


def escrow_out(stellar: StellarContext, escrow: Escrow, txs: Sequence[ChainTransaction]) -> EscrowOut:
    fees = [t.fee_stroops for t in txs if t.fee_stroops is not None]
    return EscrowOut(
        id=escrow.id,
        booking_id=escrow.booking_id,
        contract_id=escrow.contract_id,
        escrow_id_hex=escrow.escrow_key.hex(),
        state=EscrowState(escrow.state),
        asset=AssetOut(
            code=escrow.asset_code,
            issuer=escrow.asset_issuer,
            sac_contract_id=escrow.asset_sac_contract_id,
            decimals=escrow.asset_decimals,
        ),
        asset_amount=str(int(escrow.asset_units)),
        fiat=FiatOut(amount_minor=escrow.fiat_amount_minor, currency=escrow.fiat_currency),
        fx=FxOut(
            rate=f"{escrow.fx_rate:.8f}",
            base=escrow.fx_base,
            quote=escrow.fx_quote,
            source=escrow.fx_source,
            is_demo_rate=escrow.is_demo_rate,
            locked_at=escrow.fx_locked_at,
        ),
        fee_stroops=str(int(sum(fees))) if fees else None,
        customer_wallet=escrow.customer_wallet,
        professional_wallet=escrow.professional_wallet,
        refund_after=escrow.refund_after,
        review_deadline=escrow.review_deadline,
        disputed_at=escrow.disputed_at,
        reconciliation=Reconciliation(escrow.reconciliation),
        failure_reason=escrow.verification_error or escrow.failure_reason,
        settled_by=escrow.settled_by,
        professional_payout=_units(escrow.professional_payout_units),
        customer_refund=_units(escrow.customer_refund_units),
        terms_hash=escrow.terms_hash,
        transactions=[
            EscrowTransactionOut(
                kind=TxKind(t.kind),
                hash=t.tx_hash,
                ledger=t.ledger,
                at=t.confirmed_at or t.submitted_at or t.created_at,
                status=_DISPLAY_STATUS.get(t.status, t.status),
                explorer_url=stellar.explorer_tx_url(t.tx_hash),
            )
            for t in txs
        ],
        created_at=escrow.created_at,
    )


async def present(session: AsyncSession, stellar: StellarContext, escrow: Escrow) -> EscrowOut:
    return escrow_out(stellar, escrow, await repository.transactions(session, [escrow.id]))


@dataclass(frozen=True, slots=True)
class Participant:
    booking: Booking
    actor: TimelineActor  # CUSTOMER | PROFESSIONAL | ADMIN


async def _participant(
    session: AsyncSession, services: Services, caller: AuthContext, booking_id: uuid.UUID, *, for_update: bool
) -> Participant:
    booking, professional_user_id = await bookings.visible_booking(
        session, services, caller, booking_id, for_update=for_update
    )
    if caller.user_id == booking.customer_id:
        return Participant(booking, TimelineActor.CUSTOMER)
    if caller.user_id == professional_user_id:
        return Participant(booking, TimelineActor.PROFESSIONAL)
    return Participant(booking, TimelineActor.ADMIN)


def _require(participant: Participant, actor: TimelineActor, what: str) -> None:
    if participant.actor is not actor:
        raise Forbidden(f"Only the booking's {actor.value.lower()} can {what}.", code="ROLE_FORBIDDEN")


# ---------------------------------------------------------------- bookings integration (hooks)


def _actions(
    booking: Booking,
    escrow: Escrow | None,
    txs: Sequence[ChainTransaction],
    actor: TimelineActor,
    cancellation: CancellationRequest | None,
    now: int,
) -> list[str]:
    status = BookingStatus(booking.status)
    in_flight = {t.kind for t in txs if t.status in {s.value for s in (TxStatus.SUBMITTED, TxStatus.PENDING)}}
    state = EscrowState(escrow.state) if escrow else None
    actions: list[str] = []
    if actor is TimelineActor.CUSTOMER:
        if status is BookingStatus.PENDING_PAYMENT and TxKind.FUND.value not in in_flight:
            actions.append("FUND")
        if status is BookingStatus.COMPLETION_SUBMITTED and not in_flight & {"RELEASE", "REFUND"}:
            actions.append("APPROVE_RELEASE")
        if status in {BookingStatus.FUNDED, BookingStatus.IN_PROGRESS} and cancellation is None:
            actions.append("REQUEST_CANCELLATION")
        if state is EscrowState.FUNDED and escrow and now < escrow.refund_after and "EXTEND" not in in_flight:
            actions.append("EXTEND_DEADLINE")
    elif actor is TimelineActor.PROFESSIONAL:
        refundable = {BookingStatus.FUNDED, BookingStatus.IN_PROGRESS, BookingStatus.COMPLETION_SUBMITTED}
        if (
            status in {BookingStatus.FUNDED, BookingStatus.IN_PROGRESS}
            and escrow
            and now < escrow.refund_after
        ):
            actions.append("SUBMIT_COMPLETION")
        if status in refundable and not in_flight & {"RELEASE", "REFUND"}:
            actions.append("REFUND")
        if cancellation is not None:
            actions.append("DECLINE_CANCELLATION")
    return actions


async def bundle_extension(
    session: AsyncSession,
    stellar: StellarContext,
    booking: Booking,
    actor: TimelineActor | None,
    now: datetime,
) -> tuple[EscrowOut | None, list[str]]:
    escrow = await repository.escrow_for_booking(session, booking.id)
    txs = await repository.transactions(session, [escrow.id]) if escrow else []
    cancellation = await repository.open_cancellation(session, booking.id)
    actions = (
        _actions(booking, escrow, txs, actor, cancellation, int(now.timestamp()))
        if actor in {TimelineActor.CUSTOMER, TimelineActor.PROFESSIONAL}
        else []
    )
    return (escrow_out(stellar, escrow, txs) if escrow else None), actions


async def funding_in_flight(session: AsyncSession, booking_id: uuid.UUID) -> bool:
    """A booking cannot be cancelled or expire while a funding transaction may still land."""
    escrow = await repository.escrow_for_booking(session, booking_id)
    if escrow is None:
        return False
    if escrow.state != EscrowState.CREATED.value:
        return True
    tx = await repository.in_flight(session, escrow.id, TxKind.FUND)
    return tx is not None and tx.status != TxStatus.PREPARED.value


async def terms_for_booking(session: AsyncSession, booking_id: uuid.UUID) -> tuple[str, str] | None:
    escrow = await repository.escrow_for_booking(session, booking_id)
    return (escrow.terms_canonical_json, escrow.terms_hash) if escrow else None


async def wallet_in_active_escrow(session: AsyncSession, address: str) -> bool:
    return await repository.wallet_in_active_escrow(session, address)


# ---------------------------------------------------------------- the generic tx machinery


async def refresh_reconciliation(session: AsyncSession, escrow: Escrow) -> None:
    await session.flush()  # sessions do not autoflush; the query below must see pending changes
    txs = [t for t in await repository.any_in_flight(session, escrow.id) if t.status in _IN_FLIGHT_VALUES]
    if escrow.verification_error:
        escrow.reconciliation = Reconciliation.FAILED.value
    elif any(t.status in {TxStatus.SUBMITTED.value, TxStatus.PENDING.value} for t in txs):
        escrow.reconciliation = Reconciliation.PENDING_CONFIRMATION.value
    elif txs:
        escrow.reconciliation = Reconciliation.AWAITING_SIGNATURE.value
    elif escrow.state == EscrowState.CREATED.value and escrow.failure_reason:
        escrow.reconciliation = Reconciliation.FAILED.value
    elif escrow.state == EscrowState.CREATED.value:
        escrow.reconciliation = Reconciliation.AWAITING_SIGNATURE.value
    else:
        escrow.reconciliation = Reconciliation.CONFIRMED.value


async def prepare_tx(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    *,
    escrow: Escrow,
    kind: TxKind,
    source: str,
    function: Function,
    args: list[stellar_xdr.SCVal],
    requested_by: uuid.UUID | None,
    data: dict[str, Any] | None = None,
    operator: bool = False,
    replace_prepared: bool = False,
) -> ChainTransaction:
    """Build + simulate a call and store it as PREPARED. Idempotent while the prepared tx is valid.

    The caller holds the booking and escrow row locks and commits.
    """
    gateway = stellar.require()
    now = services.clock.now()
    await repository.expire_stale_prepared(session, escrow.id, now)
    existing = await repository.in_flight(session, escrow.id, kind, for_update=True)
    if existing is not None:
        if existing.status != TxStatus.PREPARED.value:
            raise Conflict("A transaction for this action is already being confirmed.", code="TX_IN_FLIGHT")
        same = existing.requested_by == requested_by and existing.data == (data or {})
        if same and not replace_prepared:
            return existing
        existing.status, existing.error = TxStatus.EXPIRED.value, "Replaced by a new preparation"
        await session.flush()
    valid_until = int(now.timestamp()) + services.settings.escrow_tx_valid_seconds
    prepared = await gateway.prepare_call(
        source=source,
        function=function,
        args=args,
        valid_until=valid_until,
        operator=stellar.operator() if operator else None,
    )
    tx = ChainTransaction(
        escrow_id=escrow.id,
        kind=kind.value,
        tx_hash=prepared.tx_hash,
        source_account=source,
        unsigned_envelope_xdr=prepared.xdr,
        valid_until=datetime.fromtimestamp(valid_until, UTC),
        status=TxStatus.PREPARED.value,
        data=data or {},
        requested_by=requested_by,
    )
    repository.add(session, tx)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_chain_transactions_in_flight":
            raise Conflict("This action is already being prepared.", code="TX_IN_FLIGHT") from exc
        raise
    await refresh_reconciliation(session, escrow)
    return tx


async def submit_signed(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    *,
    escrow_id: uuid.UUID,
    kind: TxKind,
    signed_xdr: str,
) -> EscrowOut:
    """Verify the signed envelope equals the prepared one, store it, then send it."""
    gateway = stellar.require()
    unlocked = await repository.escrow(session, escrow_id)
    if unlocked is None:
        raise NotFound("Escrow not found.")
    participant = await _participant(session, services, caller, unlocked.booking_id, for_update=True)
    escrow = await repository.escrow(session, escrow_id, for_update=True)
    assert escrow is not None
    now = services.clock.now()
    tx = await repository.in_flight(session, escrow.id, kind, for_update=True)
    if tx is None or tx.requested_by != caller.user_id:
        raise Conflict("Nothing is prepared for this action; prepare it first.", code="NOTHING_PREPARED")
    if tx.status != TxStatus.PREPARED.value:
        if tx.signed_envelope_xdr == signed_xdr:  # a retry of the same submission
            return await present(session, stellar, escrow)
        raise Conflict("A transaction for this action is already being confirmed.", code="TX_IN_FLIGHT")
    if now >= tx.valid_until:
        tx.status, tx.error = TxStatus.EXPIRED.value, "Signed after the transaction expired"
        await refresh_reconciliation(session, escrow)
        await session.commit()
        raise TxExpired()
    envelope = signing.verify_signed_envelope(
        signed_xdr, prepared_hash=tx.tx_hash, source=tx.source_account, passphrase=stellar.passphrase
    )
    tx.status = TxStatus.SUBMITTED.value
    tx.signed_envelope_xdr = signed_xdr
    tx.submitted_at = now
    tx.attempts += 1
    escrow.reconciliation = Reconciliation.PENDING_CONFIRMATION.value
    await audit.record(
        session,
        action=f"escrow.{kind.value.lower()}_submitted",
        entity_type="booking",
        entity_id=participant.booking.id,
        actor_user_id=caller.user_id,
        data={"tx_hash": tx.tx_hash},
    )
    await session.commit()  # stored before sending: a crash here is resent by the reconciler
    await send(services, stellar, tx.id, envelope, gateway_send=gateway.send)
    await session.refresh(escrow)
    return await present(session, stellar, escrow)


async def send(
    services: Services,
    stellar: StellarContext,
    tx_id: uuid.UUID,
    envelope: TransactionEnvelope,
    *,
    gateway_send: Callable[[TransactionEnvelope], Awaitable[Any]] | None = None,
) -> None:
    """sendTransaction with TRY_AGAIN_LATER backoff; records the outcome on the tx row."""
    sender = gateway_send or stellar.require().send
    result = None
    for attempt in range(SEND_RETRIES):
        try:
            result = await sender(envelope)
        except ChainUnavailable:
            logger.warning("payments.send_unavailable", extra={"tx_id": str(tx_id)})
            return  # stays SUBMITTED; the reconciler resends it
        if result.status != "TRY_AGAIN_LATER":
            break
        await asyncio.sleep(_send_backoff_seconds * 2**attempt)
    async with services.session_factory() as session:
        tx = await repository.tx(session, tx_id, for_update=True)
        assert tx is not None
        if tx.status != TxStatus.SUBMITTED.value or result is None:
            return
        tx.last_checked_at = services.clock.now()
        if result.status in {"PENDING", "DUPLICATE"}:
            tx.status = TxStatus.PENDING.value
        elif result.status == "ERROR":
            tx.status, tx.result_code, tx.error = TxStatus.FAILED.value, "SEND_ERROR", result.error
            escrow = await repository.escrow(session, tx.escrow_id, for_update=True)
            assert escrow is not None
            if escrow.state == EscrowState.CREATED.value:
                escrow.failure_reason = "The funding transaction was rejected by the network."
            await refresh_reconciliation(session, escrow)
        await session.commit()


# ---------------------------------------------------------------- funding


async def _lock_booking_escrow(
    session: AsyncSession, services: Services, caller: AuthContext, escrow_id: uuid.UUID
) -> tuple[Participant, Escrow]:
    unlocked = await repository.escrow(session, escrow_id)
    if unlocked is None:
        raise NotFound("Escrow not found.")
    participant = await _participant(session, services, caller, unlocked.booking_id, for_update=True)
    escrow = await repository.escrow(session, escrow_id, for_update=True)
    assert escrow is not None
    return participant, escrow


async def _prepared_out(
    session: AsyncSession, stellar: StellarContext, escrow: Escrow, tx: ChainTransaction
) -> PreparedOut:
    return PreparedOut(
        escrow=await present(session, stellar, escrow),
        unsigned_xdr=tx.unsigned_envelope_xdr,
        tx_hash=tx.tx_hash,
        valid_until=tx.valid_until,
    )


async def prepare_funding(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    booking_id: uuid.UUID,
    customer_wallet: str | None,
) -> PreparedOut:
    gateway = stellar.require()
    settings = services.settings
    participant = await _participant(session, services, caller, booking_id, for_update=True)
    _require(participant, TimelineActor.CUSTOMER, "fund the escrow")
    booking = participant.booking
    if booking.status != BookingStatus.PENDING_PAYMENT.value:
        raise Conflict("This booking is not awaiting payment.", code="BOOKING_NOT_PAYABLE")
    if caller.user.email_verified_at is None:
        raise Forbidden("Verify your email address before paying.", code="EMAIL_NOT_VERIFIED")

    wallet = customer_wallet or await wallets.primary_address(session, caller.user_id, stellar.network)
    if wallet is None or not await wallets.owns(session, caller.user_id, wallet, stellar.network):
        raise Conflict("Link and verify a Stellar wallet before paying.", code="WALLET_REQUIRED")
    professional_user = await bookings.professional_user_id(session, booking)
    professional_wallet = await wallets.primary_address(session, professional_user, stellar.network)
    if professional_wallet is None:
        raise Conflict("The professional has not linked a wallet yet.", code="PROFESSIONAL_WALLET_MISSING")
    if professional_wallet == wallet:
        raise Conflict("The customer and professional wallets must differ.", code="SAME_WALLET")
    for who, address in (("Your", wallet), ("The professional's", professional_wallet)):
        info = await gateway.account_info(address, stellar.asset)
        if not info.exists or not info.has_trustline:
            raise Conflict(
                f"{who} wallet needs a {stellar.asset.code} trustline before this escrow can be funded.",
                code="WALLET_NO_TRUSTLINE",
            )

    escrow = await repository.escrow_for_booking(session, booking.id, for_update=True)
    if escrow is not None:
        if escrow.state != EscrowState.CREATED.value:
            raise Conflict("This escrow is already funded.", code="ALREADY_FUNDED")
        await repository.expire_stale_prepared(session, escrow.id, services.clock.now())
        existing = await repository.in_flight(session, escrow.id, TxKind.FUND)
        if existing is not None:
            if existing.status != TxStatus.PREPARED.value:
                raise Conflict("A funding transaction is already being confirmed.", code="TX_IN_FLIGHT")
            if existing.source_account == wallet and existing.requested_by == caller.user_id:
                return await _prepared_out(session, stellar, escrow, existing)  # idempotent

    now = services.clock.now()
    agreement = await quotes_repository.get_agreement(session, booking.agreement_id)
    quote = await quotes_repository.get(session, booking.quote_id)
    assert agreement is not None
    assert quote is not None
    try:
        rate = fx.lock_rate(settings, booking.currency, now)
    except fx.RateUnavailable as exc:
        raise Conflict(str(exc), code="FX_RATE_UNAVAILABLE") from exc
    units = fx.to_asset_units(
        booking.amount_minor, booking.currency, rate.rate, settings.escrow_token_decimals
    )
    unit = settings.escrow_deadline_unit_seconds
    refund_after = terms.refund_after(
        quote.completion_date, now=now, service_grace=settings.escrow_service_grace_seconds, unit=unit
    )
    if refund_after > terms.latest_allowed_refund_after(now, unit):
        raise Conflict(
            "The agreed completion date is too far in the future to escrow.", code="DEADLINE_TOO_FAR"
        )
    key = stellar.escrow_key(str(booking.id))
    assert settings.escrow_contract_id is not None
    document = terms.build(
        agreement_hash=agreement.agreement_hash,
        booking_id=str(booking.id),
        escrow_key_hex=key.hex(),
        passphrase=stellar.passphrase,
        contract_id=settings.escrow_contract_id,
        asset_code=settings.escrow_token_code,
        asset_issuer=settings.escrow_token_issuer,
        sac_contract_id=settings.escrow_token_contract_id,
        decimals=settings.escrow_token_decimals,
        asset_units=units,
        fiat_amount_minor=booking.amount_minor,
        fiat_currency=booking.currency,
        rate=rate,
        customer_wallet=wallet,
        professional_wallet=professional_wallet,
        refund_after_ts=refund_after,
        review_window=settings.escrow_review_window_seconds,
    )
    canonical = agreements.canonicalize(document)
    values: dict[str, Any] = {
        "network": stellar.network,
        "network_passphrase": stellar.passphrase,
        "network_epoch": settings.stellar_network_epoch,
        "contract_id": settings.escrow_contract_id,
        "escrow_key": key,
        "asset_code": settings.escrow_token_code,
        "asset_issuer": settings.escrow_token_issuer,
        "asset_sac_contract_id": settings.escrow_token_contract_id,
        "asset_decimals": settings.escrow_token_decimals,
        "asset_units": Decimal(units),
        "fiat_amount_minor": booking.amount_minor,
        "fiat_currency": booking.currency,
        "fx_rate": rate.rate,
        "fx_base": rate.base,
        "fx_quote": rate.quote,
        "fx_source": rate.source,
        "is_demo_rate": rate.is_demo_rate,
        "fx_locked_at": rate.locked_at,
        "customer_wallet": wallet,
        "professional_wallet": professional_wallet,
        "refund_after": refund_after,
        "review_window": settings.escrow_review_window_seconds,
        "terms_canonical_json": canonical,
        "terms_hash": agreements.digest(canonical),
        "agreement_hash": agreement.agreement_hash,
        "failure_reason": None,
    }
    if escrow is None:
        escrow = Escrow(
            booking_id=booking.id,
            state=EscrowState.CREATED.value,
            reconciliation=Reconciliation.AWAITING_SIGNATURE.value,
            **values,
        )
        repository.add(session, escrow)
    else:  # never funded: re-prepare with fresh terms (new rate lock and deadline)
        for name, value in values.items():
            setattr(escrow, name, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) in {
            "escrows_booking_id_key",
            "uq_escrows_booking_id",
            "uq_escrows_escrow_key",
        }:
            raise Conflict("This booking's escrow is being prepared; retry.", code="TX_IN_FLIGHT") from exc
        raise
    args = contract.fund_args(
        key, wallet, professional_wallet, units, bytes.fromhex(escrow.terms_hash), refund_after
    )
    tx = await prepare_tx(
        session,
        services,
        stellar,
        escrow=escrow,
        kind=TxKind.FUND,
        source=wallet,
        function=Function.FUND,
        args=args,
        requested_by=caller.user_id,
        operator=True,
        replace_prepared=True,
    )
    await audit.record(
        session,
        action="escrow.fund_prepared",
        entity_type="booking",
        entity_id=booking.id,
        actor_user_id=caller.user_id,
        data={
            "tx_hash": tx.tx_hash,
            "terms_hash": escrow.terms_hash,
            "asset_units": str(units),
            "fx_source": rate.source,
            "is_demo_rate": rate.is_demo_rate,
        },
    )
    await session.commit()
    return await _prepared_out(session, stellar, escrow, tx)


async def get_escrow(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    escrow_id: uuid.UUID,
) -> EscrowOut:
    escrow = await repository.escrow(session, escrow_id)
    if escrow is None:
        raise NotFound("Escrow not found.")
    await _participant(session, services, caller, escrow.booking_id, for_update=False)
    return await present(session, stellar, escrow)


async def submit_funding(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    escrow_id: uuid.UUID,
    signed_xdr: str,
) -> EscrowOut:
    return await submit_signed(
        session, services, stellar, caller, escrow_id=escrow_id, kind=TxKind.FUND, signed_xdr=signed_xdr
    )


# ---------------------------------------------------------------- release, refund, extend


_OPEN_FOR_SETTLEMENT = {EscrowState.FUNDED, EscrowState.COMPLETION_SUBMITTED, EscrowState.DISPUTED}


async def release(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    escrow_id: uuid.UUID,
    signed_xdr: str | None,
) -> PreparedOut | EscrowOut:
    """Customer approval (COMPLETION_SUBMITTED) or, while disputed, a concession (Issue 7)."""
    if signed_xdr is not None:
        return await submit_signed(
            session,
            services,
            stellar,
            caller,
            escrow_id=escrow_id,
            kind=TxKind.RELEASE,
            signed_xdr=signed_xdr,
        )
    participant, escrow = await _lock_booking_escrow(session, services, caller, escrow_id)
    _require(participant, TimelineActor.CUSTOMER, "release the payment")
    state = EscrowState(escrow.state)
    allowed = {EscrowState.COMPLETION_SUBMITTED} | (
        {EscrowState.DISPUTED} if _concessions_enabled() else set()
    )
    if state not in allowed:
        raise Conflict("Payment can be released once completion is submitted.", code="RELEASE_NOT_ALLOWED")
    if state is not EscrowState.DISPUTED and await _has_open_dispute(session, participant.booking.id):
        raise Conflict("A dispute is open; ordinary release is blocked.", code="DISPUTE_OPEN")
    await _refuse_if_settling(session, escrow)
    tx = await prepare_tx(
        session,
        services,
        stellar,
        escrow=escrow,
        kind=TxKind.RELEASE,
        source=escrow.customer_wallet,
        function=Function.RELEASE,
        args=contract.escrow_only_args(escrow.escrow_key),
        requested_by=caller.user_id,
    )
    await session.commit()
    return await _prepared_out(session, stellar, escrow, tx)


async def refund(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    escrow_id: uuid.UUID,
    signed_xdr: str | None,
) -> PreparedOut | EscrowOut:
    """Professional refund: cancellation, accepting a cancellation request, or a dispute concession."""
    if signed_xdr is not None:
        return await submit_signed(
            session, services, stellar, caller, escrow_id=escrow_id, kind=TxKind.REFUND, signed_xdr=signed_xdr
        )
    participant, escrow = await _lock_booking_escrow(session, services, caller, escrow_id)
    _require(participant, TimelineActor.PROFESSIONAL, "refund the customer")
    state = EscrowState(escrow.state)
    allowed = (
        _OPEN_FOR_SETTLEMENT if _concessions_enabled() else _OPEN_FOR_SETTLEMENT - {EscrowState.DISPUTED}
    )
    if state not in allowed:
        raise Conflict("This escrow cannot be refunded now.", code="REFUND_NOT_ALLOWED")
    if state is not EscrowState.DISPUTED and await _has_open_dispute(session, participant.booking.id):
        raise Conflict("A dispute is open; ordinary refund is blocked.", code="DISPUTE_OPEN")
    await _refuse_if_settling(session, escrow)
    tx = await prepare_tx(
        session,
        services,
        stellar,
        escrow=escrow,
        kind=TxKind.REFUND,
        source=escrow.professional_wallet,
        function=Function.REFUND,
        args=contract.escrow_only_args(escrow.escrow_key),
        requested_by=caller.user_id,
    )
    await session.commit()
    return await _prepared_out(session, stellar, escrow, tx)


async def extend(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    escrow_id: uuid.UUID,
    new_refund_after: int | None,
    signed_xdr: str | None,
) -> PreparedOut | EscrowOut:
    if signed_xdr is not None:
        return await submit_signed(
            session, services, stellar, caller, escrow_id=escrow_id, kind=TxKind.EXTEND, signed_xdr=signed_xdr
        )
    if new_refund_after is None:
        raise BadRequest("Provide new_refund_after to prepare, or signed_xdr to submit.", code="INVALID_BODY")
    participant, escrow = await _lock_booking_escrow(session, services, caller, escrow_id)
    _require(participant, TimelineActor.CUSTOMER, "extend the deadline")
    now = int(services.clock.now().timestamp())
    if escrow.state != EscrowState.FUNDED.value or now >= escrow.refund_after:
        raise Conflict(
            "The deadline can only be extended while funded and before it passes.", code="EXTEND_NOT_ALLOWED"
        )
    funded_at = escrow.funded_at_chain or now
    if (
        not escrow.refund_after
        < new_refund_after
        <= funded_at + 180 * services.settings.escrow_deadline_unit_seconds
    ):
        raise BadRequest(
            "new_refund_after must be later than the current deadline and within 180 days of funding.",
            code="INVALID_DEADLINE",
        )
    tx = await prepare_tx(
        session,
        services,
        stellar,
        escrow=escrow,
        kind=TxKind.EXTEND,
        source=escrow.customer_wallet,
        function=Function.EXTEND,
        args=contract.extend_args(escrow.escrow_key, new_refund_after),
        requested_by=caller.user_id,
        data={"new_refund_after": new_refund_after},
        replace_prepared=True,
    )
    await session.commit()
    return await _prepared_out(session, stellar, escrow, tx)


def _concessions_enabled() -> bool:
    """D17 concessions arrive with disputes (Issue 7), which registers the dispute guard."""
    return _dispute_open is not None


async def _refuse_if_settling(session: AsyncSession, escrow: Escrow) -> None:
    for tx in await repository.any_in_flight(session, escrow.id):
        if tx.kind in {
            TxKind.RELEASE.value,
            TxKind.REFUND.value,
            TxKind.RESOLVE.value,
            TxKind.FINALIZE.value,
        } and (tx.status != TxStatus.PREPARED.value):
            raise Conflict("A settlement is already being confirmed.", code="TX_IN_FLIGHT")


# ---------------------------------------------------------------- cancellation requests


def cancellation_out(row: CancellationRequest) -> CancellationRequestOut:
    return CancellationRequestOut.model_validate(row)


async def _expire_cancellation(session: AsyncSession, booking_id: uuid.UUID, now: datetime) -> None:
    row = await repository.open_cancellation(session, booking_id, for_update=True)
    if row is not None and row.expires_at <= now:
        row.status = CancellationStatus.EXPIRED.value
        await session.flush()


async def request_cancellation(
    session: AsyncSession, services: Services, caller: AuthContext, booking_id: uuid.UUID, reason: str
) -> CancellationRequestOut:
    participant = await _participant(session, services, caller, booking_id, for_update=True)
    _require(participant, TimelineActor.CUSTOMER, "request a cancellation")
    booking = participant.booking
    if booking.status not in {BookingStatus.FUNDED.value, BookingStatus.IN_PROGRESS.value}:
        raise Conflict("Cancellation requests apply to funded bookings.", code="CANCELLATION_NOT_ALLOWED")
    now = services.clock.now()
    await _expire_cancellation(session, booking.id, now)
    row = CancellationRequest(
        booking_id=booking.id,
        requested_by=caller.user_id,
        reason=reason,
        status=CancellationStatus.OPEN.value,
        expires_at=now + CANCELLATION_WINDOW,
    )
    repository.add(session, row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_cancellation_requests_open":
            raise Conflict("A cancellation request is already open.", code="CANCELLATION_OPEN") from exc
        raise
    await bookings.add_timeline_note(
        session,
        booking,
        label="Cancellation requested",
        actor=TimelineActor.CUSTOMER,
        actor_user_id=caller.user_id,
        now=now,
        data={"reason": reason},
    )
    await chat.add_system_message(
        session,
        booking.conversation_id,
        "The customer asked to cancel. The professional can accept by refunding, or decline.",
        now=now,
    )
    await notifications.notify(
        session,
        await bookings.professional_user_id(session, booking),
        NotificationType.CANCELLATION_REQUESTED,
        title="Cancellation requested",
        body=f"The customer asked to cancel '{booking.title}'. Refund to accept, or decline.",
        href=f"/bookings/{booking.id}",
        data={"booking_id": str(booking.id), "request_id": str(row.id)},
        now=now,
    )
    await session.commit()
    return cancellation_out(row)


async def decline_cancellation(
    session: AsyncSession, services: Services, caller: AuthContext, request_id: uuid.UUID, reason: str
) -> CancellationRequestOut:
    unlocked = await repository.cancellation(session, request_id)
    if unlocked is None:
        raise NotFound("Cancellation request not found.")
    participant = await _participant(session, services, caller, unlocked.booking_id, for_update=True)
    _require(participant, TimelineActor.PROFESSIONAL, "decline a cancellation")
    now = services.clock.now()
    await _expire_cancellation(session, unlocked.booking_id, now)
    row = await repository.cancellation(session, request_id, for_update=True)
    assert row is not None
    if row.status != CancellationStatus.OPEN.value:
        raise Conflict("This cancellation request is no longer open.", code="CANCELLATION_NOT_OPEN")
    row.status, row.responded_by, row.responded_at = CancellationStatus.DECLINED.value, caller.user_id, now
    row.decline_reason = reason
    await bookings.add_timeline_note(
        session,
        participant.booking,
        label="Cancellation declined",
        actor=TimelineActor.PROFESSIONAL,
        actor_user_id=caller.user_id,
        now=now,
        data={"reason": reason},
    )
    booking = participant.booking
    await notifications.notify(
        session,
        booking.customer_id,
        NotificationType.CANCELLATION_DECLINED,
        title="Cancellation declined",
        body=f"The professional declined to cancel '{booking.title}': {reason}",
        href=f"/bookings/{booking.id}",
        data={"booking_id": str(booking.id), "request_id": str(row.id)},
        now=now,
    )
    await session.commit()
    return cancellation_out(row)


async def accept_cancellation_on_refund(session: AsyncSession, booking_id: uuid.UUID, now: datetime) -> None:
    """Called by the reconciler when a professional's refund confirms (never from a request)."""
    row = await repository.open_cancellation(session, booking_id, for_update=True)
    if row is not None:
        row.status, row.responded_at = CancellationStatus.ACCEPTED.value, now


# ---------------------------------------------------------------- receipts


async def receipts(
    session: AsyncSession, services: Services, caller: AuthContext, booking_id: uuid.UUID
) -> list[ReceiptOut]:
    await _participant(session, services, caller, booking_id, for_update=False)
    escrow = await repository.escrow_for_booking(session, booking_id)
    result = []
    for row in await repository.receipts(session, booking_id):
        assert escrow is not None
        result.append(
            ReceiptOut(
                id=row.id,
                number=row.number,
                kind=row.kind,
                booking_id=row.booking_id,
                asset=AssetOut(
                    code=row.asset_code,
                    issuer=row.asset_issuer,
                    sac_contract_id=escrow.asset_sac_contract_id,
                    decimals=escrow.asset_decimals,
                ),
                asset_amount=str(int(row.asset_units)),
                fiat=FiatOut(amount_minor=row.fiat_amount_minor, currency=row.fiat_currency),
                fx={"rate": f"{row.fx_rate:.8f}", "source": row.fx_source, "is_demo_rate": row.is_demo_rate},
                tx_hash=row.tx_hash,
                ledger=row.ledger,
                issued_at=row.issued_at,
                payload_hash=row.payload_hash,
                payload_json=row.payload_canonical_json,
            )
        )
    return result


def terms_document(escrow: Escrow) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(escrow.terms_canonical_json)
    return document


# ---------------------------------------------------------------- deadline warnings (Issue 8)

DEADLINE_WARNING_LEAD = timedelta(hours=24)


async def warn_deadlines(services: Services) -> int:
    """Warn both parties 24 h before ``refund_after`` (Funded) and ``review_deadline`` (CompletionSubmitted).

    Idempotent: the dedupe key includes the deadline, so a warning is sent once per deadline and an
    extension produces a fresh warning for the new date.
    """
    now = services.clock.now()
    start, end = int(now.timestamp()), int((now + DEADLINE_WARNING_LEAD).timestamp())
    due = 0
    async with services.session_factory() as session:
        rows = (
            await session.execute(
                select(Escrow, Booking)
                .join(Booking, Booking.id == Escrow.booking_id)
                .where(
                    or_(
                        and_(
                            Escrow.state == EscrowState.FUNDED.value, Escrow.refund_after.between(start, end)
                        ),
                        and_(
                            Escrow.state == EscrowState.COMPLETION_SUBMITTED.value,
                            Escrow.review_deadline.between(start, end),
                        ),
                    )
                )
            )
        ).all()
        for escrow, booking in rows:
            professional = await bookings.professional_user_id(session, booking)
            if escrow.state == EscrowState.FUNDED.value:
                deadline, which = escrow.refund_after, "refund_after"
                bodies = {
                    booking.customer_id: f"'{booking.title}' refunds to you automatically within 24 hours "
                    "unless completion is submitted. You can extend the deadline.",
                    professional: f"Submit completion for '{booking.title}' within 24 hours, or the "
                    "escrow refunds to the customer.",
                }
            else:
                assert escrow.review_deadline is not None
                deadline, which = escrow.review_deadline, "review_deadline"
                bodies = {
                    booking.customer_id: f"The payment for '{booking.title}' releases automatically "
                    "within 24 hours unless you open a dispute.",
                    professional: f"The review window for '{booking.title}' ends within 24 hours; "
                    "the payment then releases to you.",
                }
            for user_id, body in bodies.items():
                await notifications.notify(
                    session,
                    user_id,
                    NotificationType.DEADLINE_APPROACHING,
                    title="Deadline in 24 hours",
                    body=body,
                    href=f"/bookings/{booking.id}",
                    data={"booking_id": str(booking.id), "deadline": deadline, "kind": which.upper()},
                    dedupe_key=f"deadline:{escrow.id}:{which}:{deadline}",
                    now=now,
                )
            due += 1
        await session.commit()
    return due
