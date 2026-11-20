"""The chain boundary: Soroban RPC + Horizon, behind one small interface.

``ChainGateway`` is what the rest of the app depends on. ``RpcGateway`` is the real
implementation. Tests substitute a clearly labelled double (``tests/chain.py``) that runs the
same contract rules in memory; real-network behaviour is verified separately against testnet.

Every failure here raises a ``ChainUnavailable``/``ChainRejected`` before any database write,
so callers never change state on a chain error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
from stellar_sdk import (
    Account,
    Address,
    Asset,
    Keypair,
    StrKey,
    TransactionBuilder,
    TransactionEnvelope,
    scval,
)
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.auth import authorize_entry
from stellar_sdk.exceptions import (
    BaseRequestError,
    NotFoundError,
    PrepareTransactionException,
    SorobanRpcErrorResponse,
)
from stellar_sdk.exceptions import ConnectionError as StellarConnectionError
from stellar_sdk.soroban_rpc import EventFilter, EventFilterType, GetTransactionStatus, SendTransactionStatus
from stellar_sdk.soroban_server_async import Durability, SorobanServerAsync

from app.modules.stellar import contract
from app.modules.stellar.contract import OnchainConfig, OnchainEscrow
from app.modules.stellar.errors import ChainRejected, ChainUnavailable
from app.modules.stellar.http import HttpxAsyncClient

logger = logging.getLogger(__name__)

BASE_FEE = 100_000  # stroops; the resource fee from simulation is added on top


@dataclass(frozen=True, slots=True)
class AccountInfo:
    exists: bool
    has_trustline: bool


@dataclass(frozen=True, slots=True)
class PreparedTx:
    envelope: TransactionEnvelope
    tx_hash: str
    valid_until: int  # unix seconds (max time bound)

    @property
    def xdr(self) -> str:
        return self.envelope.to_xdr()


@dataclass(frozen=True, slots=True)
class SendResult:
    status: str  # PENDING | DUPLICATE | TRY_AGAIN_LATER | ERROR
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TxStatus:
    status: str  # SUCCESS | FAILED | NOT_FOUND
    ledger: int | None = None
    closed_at: datetime | None = None
    fee_stroops: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RawEvent:
    contract_id: str
    ledger: int
    ledger_closed_at: datetime
    tx_hash: str
    tx_index: int
    event_index: int
    topics: list[stellar_xdr.SCVal]
    value: stellar_xdr.SCVal


@dataclass(frozen=True, slots=True)
class EventsPage:
    events: list[RawEvent]
    cursor: str
    latest_ledger: int
    oldest_ledger: int


@dataclass(frozen=True, slots=True)
class Health:
    healthy: bool
    latest_ledger: int | None
    oldest_ledger: int | None
    error: str | None = None


class ChainGateway(Protocol):
    passphrase: str
    contract_id: str

    async def account_info(self, address: str, asset: Asset) -> AccountInfo: ...
    async def prepare_call(
        self,
        *,
        source: str,
        function: contract.Function,
        args: list[stellar_xdr.SCVal],
        valid_until: int,
        operator: Keypair | None = None,
    ) -> PreparedTx: ...
    async def send(self, envelope: TransactionEnvelope) -> SendResult: ...
    async def get_transaction(self, tx_hash: str) -> TxStatus: ...
    async def get_events(self, *, start_ledger: int | None, cursor: str | None, limit: int) -> EventsPage: ...
    async def get_escrow(self, escrow_id: bytes) -> OnchainEscrow | None: ...
    async def get_config(self, source: str) -> OnchainConfig: ...
    async def contract_exists(self, contract_id: str) -> bool: ...
    async def latest_ledger(self) -> int: ...
    async def health(self) -> Health: ...
    async def close(self) -> None: ...


def _chain_error(exc: Exception, action: str) -> Exception:
    if isinstance(exc, StellarConnectionError | httpx.HTTPError):
        return ChainUnavailable()
    if isinstance(exc, PrepareTransactionException):
        error = exc.simulate_transaction_response.error or ""
        name = contract.contract_error_name(error)
        if name:
            return ChainRejected(
                f"The escrow contract refused this {action}: {name}.", code=f"CONTRACT_{_snake(name)}"
            )
        return ChainRejected(f"Simulation of this {action} failed.")
    if isinstance(exc, SorobanRpcErrorResponse | BaseRequestError):
        return ChainUnavailable("The Stellar RPC returned an error. Nothing was changed; please retry.")
    return exc


def _snake(name: str) -> str:
    return "".join(f"_{c}" if c.isupper() and i else c for i, c in enumerate(name)).upper()


class RpcGateway:
    """Soroban RPC (simulate, send, getTransaction, getEvents, ledger entries) + Horizon (accounts)."""

    def __init__(
        self, *, rpc_url: str, horizon_url: str, passphrase: str, contract_id: str, timeout: float
    ) -> None:
        self.passphrase = passphrase
        self.contract_id = contract_id
        self._http = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "unifix-backend"})
        self._rpc = SorobanServerAsync(rpc_url, client=HttpxAsyncClient(self._http))
        self._horizon_url = horizon_url.rstrip("/")

    async def close(self) -> None:
        await self._http.aclose()

    async def account_info(self, address: str, asset: Asset) -> AccountInfo:
        if not StrKey.is_valid_ed25519_public_key(address):
            return AccountInfo(exists=False, has_trustline=False)
        try:
            response = await self._http.get(f"{self._horizon_url}/accounts/{address}")
        except httpx.HTTPError as exc:
            raise ChainUnavailable() from exc
        if response.status_code == 404:
            return AccountInfo(exists=False, has_trustline=False)
        if response.status_code != 200:
            raise ChainUnavailable("Horizon returned an error. Nothing was changed; please retry.")
        balances = response.json().get("balances", [])
        trusted = any(
            b.get("asset_code") == asset.code and b.get("asset_issuer") == asset.issuer for b in balances
        )
        return AccountInfo(exists=True, has_trustline=trusted)

    async def _load_account(self, address: str) -> Account:
        try:
            return await self._rpc.load_account(address)
        except NotFoundError as exc:
            raise ChainRejected(
                "The Stellar account does not exist on this network.", code="ACCOUNT_NOT_FOUND"
            ) from exc
        except Exception as exc:
            raise _chain_error(exc, "account lookup") from exc

    async def prepare_call(
        self,
        *,
        source: str,
        function: contract.Function,
        args: list[stellar_xdr.SCVal],
        valid_until: int,
        operator: Keypair | None = None,
    ) -> PreparedTx:
        """Build → simulate → (operator signs its auth entry, re-simulate) → assembled envelope.

        The source account (the user's wallet, or the operator for keeper calls) signs the
        whole transaction later; with source-account credentials it needs no separate auth entry.
        """
        account = await self._load_account(source)
        builder = (
            TransactionBuilder(account, self.passphrase, base_fee=BASE_FEE)
            .append_invoke_contract_function_op(self.contract_id, function.value, args)
            .add_time_bounds(0, valid_until)
        )
        tx = builder.build()
        try:
            simulated = await self._rpc.simulate_transaction(tx, use_upgraded_auth=False)
            if simulated.error:
                raise PrepareTransactionException("simulation failed", simulated)
            if operator is not None:
                latest = simulated.latest_ledger
                op = tx.transaction.operations[0]
                entries = [
                    stellar_xdr.SorobanAuthorizationEntry.from_xdr(raw)
                    for result in simulated.results or []
                    for raw in result.auth or []
                ]
                signed = [
                    authorize_entry(entry, operator, latest + _ledgers(valid_until), self.passphrase)
                    if _is_address_entry(entry, operator.public_key)
                    else entry
                    for entry in entries
                ]
                op.auth = signed  # type: ignore[attr-defined]
                tx = await self._rpc.prepare_transaction(tx, use_upgraded_auth=False)
            else:
                tx = await self._rpc.prepare_transaction(tx, simulated, use_upgraded_auth=False)
        except Exception as exc:
            raise _chain_error(exc, function.value) from exc
        return PreparedTx(envelope=tx, tx_hash=tx.hash_hex(), valid_until=valid_until)

    async def send(self, envelope: TransactionEnvelope) -> SendResult:
        try:
            response = await self._rpc.send_transaction(envelope)
        except Exception as exc:
            raise _chain_error(exc, "submission") from exc
        error = None
        if response.status is SendTransactionStatus.ERROR:
            error = response.error_result_xdr
        return SendResult(status=response.status.value, error=error)

    async def get_transaction(self, tx_hash: str) -> TxStatus:
        try:
            response = await self._rpc.get_transaction(tx_hash)
        except Exception as exc:
            raise _chain_error(exc, "status check") from exc
        if response.status is GetTransactionStatus.NOT_FOUND:
            return TxStatus(status="NOT_FOUND")
        fee = None
        error = None
        if response.result_xdr:
            result = stellar_xdr.TransactionResult.from_xdr(response.result_xdr)
            fee = result.fee_charged.int64
            if response.status is GetTransactionStatus.FAILED:
                error = result.result.code.name
        closed = datetime.fromtimestamp(response.create_at, UTC) if response.create_at else None
        return TxStatus(
            status=response.status.value,
            ledger=response.ledger,
            closed_at=closed,
            fee_stroops=fee,
            error=error,
        )

    async def get_events(self, *, start_ledger: int | None, cursor: str | None, limit: int) -> EventsPage:
        filters = [EventFilter(event_type=EventFilterType.CONTRACT, contract_ids=[self.contract_id])]
        try:
            response = await self._rpc.get_events(
                start_ledger=None if cursor else start_ledger, filters=filters, cursor=cursor, limit=limit
            )
        except Exception as exc:
            raise _chain_error(exc, "event scan") from exc
        events = [
            RawEvent(
                contract_id=e.contract_id,
                ledger=e.ledger,
                ledger_closed_at=e.ledger_close_at,
                tx_hash=e.transaction_hash,
                tx_index=e.transaction_index,
                event_index=int(e.id.rsplit("-", 1)[1]),
                topics=[stellar_xdr.SCVal.from_xdr(t) for t in e.topic],
                value=stellar_xdr.SCVal.from_xdr(e.value),
            )
            for e in response.events
        ]
        return EventsPage(
            events=events,
            cursor=response.cursor,
            latest_ledger=response.latest_ledger,
            oldest_ledger=response.oldest_ledger,
        )

    async def get_escrow(self, escrow_id: bytes) -> OnchainEscrow | None:
        key = scval.to_vec([scval.to_symbol("Escrow"), scval.to_bytes(escrow_id)])
        try:
            entry = await self._rpc.get_contract_data(self.contract_id, key, Durability.PERSISTENT)
        except Exception as exc:
            raise _chain_error(exc, "escrow read") from exc
        if entry is None:
            return None
        data = stellar_xdr.LedgerEntryData.from_xdr(entry.xdr)
        assert data.contract_data is not None
        return contract.decode_escrow(data.contract_data.val)

    async def get_config(self, source: str) -> OnchainConfig:
        account = await self._load_account(source)
        tx = (
            TransactionBuilder(account, self.passphrase, base_fee=BASE_FEE)
            .append_invoke_contract_function_op(self.contract_id, contract.Function.CONFIG.value, [])
            .set_timeout(60)
            .build()
        )
        try:
            simulated = await self._rpc.simulate_transaction(tx)
        except Exception as exc:
            raise _chain_error(exc, "config read") from exc
        if simulated.error or not simulated.results or not simulated.results[0].xdr:
            raise ChainRejected("Could not read the escrow contract configuration.")
        return contract.decode_config(stellar_xdr.SCVal.from_xdr(simulated.results[0].xdr))

    async def contract_exists(self, contract_id: str) -> bool:
        key = stellar_xdr.LedgerKey(
            stellar_xdr.LedgerEntryType.CONTRACT_DATA,
            contract_data=stellar_xdr.LedgerKeyContractData(
                contract=Address(contract_id).to_xdr_sc_address(),
                key=stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_LEDGER_KEY_CONTRACT_INSTANCE),
                durability=stellar_xdr.ContractDataDurability.PERSISTENT,
            ),
        )
        try:
            response = await self._rpc.get_ledger_entries([key])
        except Exception as exc:
            raise _chain_error(exc, "contract lookup") from exc
        return bool(response.entries)

    async def latest_ledger(self) -> int:
        try:
            return (await self._rpc.get_latest_ledger()).sequence
        except Exception as exc:
            raise _chain_error(exc, "ledger read") from exc

    async def health(self) -> Health:
        try:
            response = await self._rpc.get_health()
        except Exception as exc:
            return Health(healthy=False, latest_ledger=None, oldest_ledger=None, error=type(exc).__name__)
        return Health(
            healthy=response.status == "healthy",
            latest_ledger=response.latest_ledger,
            oldest_ledger=response.oldest_ledger,
        )


def _ledgers(valid_until: int) -> int:
    """Auth-entry expiry in ledgers: cover the tx validity window with margin (~5 s/ledger)."""
    remaining = max(0, valid_until - int(datetime.now(UTC).timestamp()))
    return remaining // 5 + 20


def _is_address_entry(entry: stellar_xdr.SorobanAuthorizationEntry, address: str) -> bool:
    credentials = entry.credentials
    if credentials.type != stellar_xdr.SorobanCredentialsType.SOROBAN_CREDENTIALS_ADDRESS:
        return False
    assert credentials.address is not None
    return (
        StrKey.encode_ed25519_public_key(
            credentials.address.address.account_id.account_id.ed25519.uint256  # type: ignore[union-attr]
        )
        == address
    )


__all__ = [
    "AccountInfo",
    "ChainGateway",
    "EventsPage",
    "Health",
    "PreparedTx",
    "RawEvent",
    "RpcGateway",
    "SendResult",
    "TxStatus",
]
