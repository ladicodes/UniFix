"""TEST DOUBLE — an in-memory Stellar network running the escrow contract's rules.

It implements ``ChainGateway`` so PostgreSQL integration tests can drive every payment path
deterministically: prepared transactions are real, hashable Stellar envelopes; submitted
envelopes are queued and only applied when the test closes a ledger; the contract rules
(auth, states, deadlines, splits) mirror ``contracts/escrow/src/lib.rs``, whose behaviour is
verified by ``cargo test`` and by the testnet smoke run. Nothing here is a real network.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from stellar_sdk import Account, Asset, Keypair, StrKey, TransactionBuilder, TransactionEnvelope, scval
from stellar_sdk import xdr as stellar_xdr

from app.core.clock import Clock
from app.modules.stellar import contract
from app.modules.stellar.contract import Function, OnchainConfig, OnchainEscrow
from app.modules.stellar.contract import OnchainStatus as St
from app.modules.stellar.errors import ChainRejected, ChainUnavailable
from app.modules.stellar.gateway import (
    BASE_FEE,
    AccountInfo,
    EventsPage,
    Health,
    PreparedTx,
    RawEvent,
    SendResult,
    TxStatus,
)

DAY = 86_400


class ContractFailure(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(name)


@dataclass
class _Account:
    sequence: int = 1_000
    trustline: bool = True


@dataclass
class _Pending:
    envelope: TransactionEnvelope
    source: str
    function: str
    args: list[Any]
    operator_signed: bool


@dataclass
class FakeChain:
    clock: Clock
    passphrase: str
    contract_id: str
    token_contract_id: str
    arbiter: str
    operator: str
    review_window: int = 72 * 3600
    accounts: dict[str, _Account] = field(default_factory=dict)
    balances: dict[str, int] = field(default_factory=dict)
    escrows: dict[bytes, OnchainEscrow] = field(default_factory=dict)
    events: list[RawEvent] = field(default_factory=list)
    txs: dict[str, TxStatus] = field(default_factory=dict)
    pending: list[_Pending] = field(default_factory=list)
    ledger: int = 100
    offline: bool = False
    try_again_later: int = 0  # the next N sends answer TRY_AGAIN_LATER
    oldest_ledger: int = 1
    _operator_prepared: set[str] = field(default_factory=set)

    # ---- test controls ------------------------------------------------------------------

    def create_account(self, address: str, *, trustline: bool = True, balance: int = 0) -> None:
        self.accounts[address] = _Account(trustline=trustline)
        self.balances[address] = balance

    def now(self) -> int:
        return int(self.clock.now().timestamp())

    def close_ledger(self) -> list[str]:
        """Apply every queued transaction in submission order, as one new ledger. Returns hashes."""
        self.ledger += 1
        applied = []
        for index, item in enumerate(self.pending):
            tx_hash = item.envelope.hash_hex()
            try:
                self._apply(item, tx_hash, index)
                status = TxStatus("SUCCESS", self.ledger, self.clock.now(), 100_123)
            except ContractFailure as failure:
                status = TxStatus(
                    "FAILED", self.ledger, self.clock.now(), 100_123, f"contract:{failure.name}"
                )
            self.txs[tx_hash] = status
            applied.append(tx_hash)
        self.pending.clear()
        return applied

    def invoke(self, function: Function, args: list[stellar_xdr.SCVal], *, signer: str) -> str:
        """An out-of-band transaction (another wallet or tool), confirmed in the next ledger."""
        account = self.accounts.setdefault(signer, _Account())
        envelope = self._build(signer, account.sequence + 1, function, args, self.now() + 300)
        account.sequence += 1
        self.pending.append(
            _Pending(envelope, signer, function.value, _natives(args), signer == self.operator)
        )
        return envelope.hash_hex()

    # ---- ChainGateway -------------------------------------------------------------------

    async def account_info(self, address: str, asset: Asset) -> AccountInfo:
        self._online()
        account = self.accounts.get(address)
        return AccountInfo(exists=account is not None, has_trustline=bool(account and account.trustline))

    async def prepare_call(
        self,
        *,
        source: str,
        function: Function,
        args: list[stellar_xdr.SCVal],
        valid_until: int,
        operator: Keypair | None = None,
    ) -> PreparedTx:
        self._online()
        account = self.accounts.get(source)
        if account is None:
            raise ChainRejected(
                "The Stellar account does not exist on this network.", code="ACCOUNT_NOT_FOUND"
            )
        # Simulation: run the call against a copy of the state, as RPC simulation would.
        trial = copy.deepcopy(self)
        try:
            trial._run(function.value, _natives(args), source, operator is not None)
        except ContractFailure as failure:
            raise ChainRejected(
                f"The escrow contract refused this {function.value}: {failure.name}.",
                code=f"CONTRACT_{_snake(failure.name)}",
            ) from failure
        envelope = self._build(source, account.sequence + 1, function, args, valid_until)
        if operator is not None:
            assert operator.public_key == self.operator, "wrong operator key"
            self._operator_prepared.add(envelope.hash_hex())
        return PreparedTx(envelope=envelope, tx_hash=envelope.hash_hex(), valid_until=valid_until)

    async def send(self, envelope: TransactionEnvelope) -> SendResult:
        self._online()
        if self.try_again_later:
            self.try_again_later -= 1
            return SendResult("TRY_AGAIN_LATER")
        tx_hash = envelope.hash_hex()
        if tx_hash in self.txs or any(p.envelope.hash_hex() == tx_hash for p in self.pending):
            return SendResult("DUPLICATE")
        source = envelope.transaction.source.account_id
        account = self.accounts.get(source)
        if account is None or envelope.transaction.sequence != account.sequence + 1:
            return SendResult("ERROR", "txBAD_SEQ")
        bounds = envelope.transaction.preconditions
        if bounds and bounds.time_bounds and self.now() > bounds.time_bounds.max_time:
            return SendResult("ERROR", "txTOO_LATE")
        if not envelope.signatures:
            return SendResult("ERROR", "txBAD_AUTH")
        account.sequence += 1
        op = envelope.transaction.operations[0]
        invoke = op.host_function.invoke_contract  # type: ignore[attr-defined]
        function = invoke.function_name.sc_symbol.decode()
        self.pending.append(
            _Pending(
                envelope, source, function, _natives(list(invoke.args)), tx_hash in self._operator_prepared
            )
        )
        return SendResult("PENDING")

    async def get_transaction(self, tx_hash: str) -> TxStatus:
        self._online()
        return self.txs.get(tx_hash, TxStatus("NOT_FOUND"))

    async def get_events(self, *, start_ledger: int | None, cursor: str | None, limit: int) -> EventsPage:
        self._online()
        if cursor is not None:
            start = int(cursor)
        else:
            start = next(
                (i for i, e in enumerate(self.events) if e.ledger >= (start_ledger or 0)), len(self.events)
            )
        page = self.events[start : start + limit]
        return EventsPage(page, str(start + len(page)), self.ledger, self.oldest_ledger)

    async def get_escrow(self, escrow_id: bytes) -> OnchainEscrow | None:
        self._online()
        return self.escrows.get(escrow_id)

    async def get_config(self, source: str) -> OnchainConfig:
        self._online()
        return OnchainConfig(
            admin=self.arbiter, arbiter=self.arbiter, operator=self.operator,
            token=self.token_contract_id, review_window=self.review_window,
        )  # fmt: skip

    async def contract_exists(self, contract_id: str) -> bool:
        self._online()
        return contract_id in {self.contract_id, self.token_contract_id}

    async def latest_ledger(self) -> int:
        self._online()
        return self.ledger

    async def health(self) -> Health:
        if self.offline:
            return Health(False, None, None, "offline")
        return Health(True, self.ledger, self.oldest_ledger)

    async def close(self) -> None:
        return None

    # ---- internals -------------------------------------------------------------------------

    def _online(self) -> None:
        if self.offline:
            raise ChainUnavailable()

    def _build(
        self, source: str, sequence: int, function: Function, args: list[stellar_xdr.SCVal], valid_until: int
    ) -> TransactionEnvelope:
        return (
            TransactionBuilder(Account(source, sequence - 1), self.passphrase, base_fee=BASE_FEE)
            .append_invoke_contract_function_op(self.contract_id, function.value, args)
            .add_time_bounds(0, valid_until)
            .build()
        )

    def _apply(self, item: _Pending, tx_hash: str, tx_index: int) -> None:
        emitted = self._run(item.function, item.args, item.source, item.operator_signed)
        for event_index, (name, escrow_key, payload) in enumerate(emitted):
            topics = [scval.to_symbol("unifix"), scval.to_symbol(name)]
            if escrow_key is not None:
                topics.append(scval.to_bytes(escrow_key))
            self.events.append(
                RawEvent(
                    contract_id=self.contract_id,
                    ledger=self.ledger,
                    ledger_closed_at=self.clock.now().astimezone(UTC),
                    tx_hash=tx_hash,
                    tx_index=tx_index,
                    event_index=event_index,
                    topics=topics,
                    value=_payload_scval(payload),
                )
            )

    def _run(self, function: str, args: list[Any], signer: str, operator_signed: bool) -> list[Any]:
        """The contract rules (mirrors lib.rs). Raises ContractFailure, or 'Auth' for a bad signer."""
        now = self.now()
        key = args[0] if args else None
        if function == "fund":
            _, customer, professional, amount, terms_hash, refund_after = args
            if signer != customer or not operator_signed:
                raise ContractFailure("Auth")
            if key in self.escrows:
                raise ContractFailure("AlreadyExists")
            if amount <= 0:
                raise ContractFailure("InvalidAmount")
            if customer == professional:
                raise ContractFailure("SameParty")
            if not now + DAY <= refund_after <= now + 180 * DAY:
                raise ContractFailure("InvalidDeadline")
            if self.balances.get(customer, 0) < amount:
                raise ContractFailure("InsufficientBalance")
            self.escrows[key] = OnchainEscrow(
                customer=customer, professional=professional, amount=amount, terms_hash=terms_hash.hex(),
                status=St.FUNDED, funded_at=now, refund_after=refund_after, review_window=self.review_window,
                review_deadline=None, disputed_at=None, evidence_hash=None, disputed_by=None,
                professional_payout=0, customer_refund=0, settled_by=None,
            )  # fmt: skip
            self._move(customer, self.contract_id, amount)
            return [("funded", key, {"amount": amount, "customer": customer, "professional": professional,
                                     "refund_after": refund_after, "review_window": self.review_window,
                                     "terms_hash": terms_hash})]  # fmt: skip
        escrow = self.escrows.get(key)  # type: ignore[arg-type]
        if escrow is None:
            raise ContractFailure("NotFound")
        open_states = {St.FUNDED, St.COMPLETION_SUBMITTED, St.DISPUTED}
        if function == "submit_completion":
            self._auth(signer, escrow.professional)
            if escrow.status is not St.FUNDED:
                raise ContractFailure("InvalidState")
            if now >= escrow.refund_after:
                raise ContractFailure("DeadlinePassed")
            deadline = now + escrow.review_window
            self.escrows[key] = replace(
                escrow, status=St.COMPLETION_SUBMITTED, review_deadline=deadline, evidence_hash=args[1].hex()
            )
            return [("completion_submitted", key, {"evidence_hash": args[1], "review_deadline": deadline})]
        if function == "release":
            self._auth(signer, escrow.customer)
            if escrow.status not in open_states:
                raise ContractFailure("InvalidState")
            return [("released", key, self._settle(key, escrow, St.RELEASED, escrow.amount, "Customer"))]
        if function == "refund":
            self._auth(signer, escrow.professional)
            if escrow.status not in open_states:
                raise ContractFailure("InvalidState")
            return [("refunded", key, self._settle(key, escrow, St.REFUNDED, 0, "Professional"))]
        if function == "extend":
            self._auth(signer, escrow.customer)
            if escrow.status is not St.FUNDED:
                raise ContractFailure("InvalidState")
            if now >= escrow.refund_after:
                raise ContractFailure("DeadlinePassed")
            if not escrow.refund_after < args[1] <= escrow.funded_at + 180 * DAY:
                raise ContractFailure("InvalidDeadline")
            self.escrows[key] = replace(escrow, refund_after=args[1])
            return [("extended", key, {"refund_after": args[1]})]
        if function == "open_dispute":
            caller = args[1]
            self._auth(signer, caller)
            if caller not in {escrow.customer, escrow.professional}:
                raise ContractFailure("NotParty")
            if escrow.status is St.FUNDED:
                deadline = escrow.refund_after
            elif escrow.status is St.COMPLETION_SUBMITTED and escrow.review_deadline is not None:
                deadline = escrow.review_deadline
            else:
                raise ContractFailure("InvalidState")
            if now >= deadline:
                raise ContractFailure("DeadlinePassed")
            self.escrows[key] = replace(escrow, status=St.DISPUTED, disputed_at=now, disputed_by=caller)
            return [("disputed", key, {"disputed_at": now, "disputed_by": caller})]
        if function == "resolve":
            self._auth(signer, self.arbiter)
            if escrow.status is not St.DISPUTED:
                raise ContractFailure("InvalidState")
            payout = args[1]
            if not 0 <= payout <= escrow.amount:
                raise ContractFailure("InvalidSplit")
            status = St.RELEASED if payout == escrow.amount else St.REFUNDED if payout == 0 else St.RESOLVED
            return [("resolved", key, self._settle(key, escrow, status, payout, "Arbiter"))]
        if function == "finalize_expired":
            if escrow.status is St.FUNDED:
                deadline, status, payout = escrow.refund_after, St.REFUNDED, 0
            elif escrow.status is St.COMPLETION_SUBMITTED and escrow.review_deadline is not None:
                deadline, status, payout = escrow.review_deadline, St.RELEASED, escrow.amount
            else:
                raise ContractFailure("InvalidState")
            if now < deadline:
                raise ContractFailure("NotExpired")
            payload = self._settle(key, escrow, status, payout, "Timeout")
            return [("expired", key, {**payload, "status": [status.value]})]
        raise ContractFailure("UnknownFunction")

    @staticmethod
    def _auth(signer: str, required: str) -> None:
        if signer != required:
            raise ContractFailure("Auth")

    def _settle(self, key: bytes, escrow: OnchainEscrow, status: St, payout: int, by: str) -> dict[str, Any]:
        refund = escrow.amount - payout
        self.escrows[key] = replace(
            escrow, status=status, professional_payout=payout, customer_refund=refund,
            settled_by=contract.settled_by_name(by),
        )  # fmt: skip
        if payout:
            self._move(self.contract_id, escrow.professional, payout)
        if refund:
            self._move(self.contract_id, escrow.customer, refund)
        return {"professional_payout": payout, "customer_refund": refund, "settled_by": [by]}

    def _move(self, source: str, destination: str, amount: int) -> None:
        self.balances[source] = self.balances.get(source, 0) - amount
        self.balances[destination] = self.balances.get(destination, 0) + amount


def _natives(args: list[stellar_xdr.SCVal]) -> list[Any]:
    result: list[Any] = []
    for arg in args:
        value = scval.to_native(arg)
        result.append(value.address if hasattr(value, "address") and not isinstance(value, bytes) else value)
    return result


def _payload_scval(payload: dict[str, Any]) -> stellar_xdr.SCVal:
    entries: dict[stellar_xdr.SCVal, stellar_xdr.SCVal] = {}
    for name in sorted(payload):
        value = payload[name]
        if isinstance(value, bytes):
            encoded = scval.to_bytes(value)
        elif isinstance(value, list):
            encoded = scval.to_vec([scval.to_symbol(v) for v in value])
        elif isinstance(value, str):
            encoded = scval.to_address(value)
        elif name in {"amount", "professional_payout", "customer_refund"}:
            encoded = scval.to_int128(value)
        else:
            encoded = scval.to_uint64(value)
        entries[scval.to_symbol(name)] = encoded
    return scval.to_map(entries)


def _snake(name: str) -> str:
    return "".join(f"_{c}" if c.isupper() and i else c for i, c in enumerate(name)).upper()


def contract_strkey(seed: str) -> str:
    return StrKey.encode_contract(hashlib.sha256(seed.encode()).digest())


def timestamp(at: datetime) -> int:
    return int(at.timestamp())
