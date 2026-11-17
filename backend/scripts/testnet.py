"""Stellar TESTNET tooling: deploy the escrow contract and run the on-chain smoke test.

    uv run python -m scripts.testnet deploy     # keys (Friendbot), test asset + SAC, wasm, contracts
    uv run python -m scripts.testnet smoke      # every contract path through app.modules.stellar
    uv run python -m scripts.testnet env        # print .env lines for the USDC deployment

Everything here is testnet-only. Generated throwaway keys and the deployment record live in
``var/testnet/deployment.json`` (gitignored, never committed). Mainnet is refused.

Deployments (all from the same contract source):
* ``usdc``   — production wasm, Circle testnet USDC, 72 h review window (frontend demos).
* ``test``   — production wasm, a UniFix-issued test asset (automated E2E; mintable).
* ``short``  — the ``short-windows`` build (bounds in minutes), test asset; timeout paths only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import time
import urllib.request
from pathlib import Path
from typing import Any

from stellar_sdk import Asset, Keypair, Network, Server, SorobanServer, TransactionBuilder, scval
from stellar_sdk import xdr as stellar_xdr

from app.modules.stellar import contract
from app.modules.stellar.contract import Function
from app.modules.stellar.gateway import RpcGateway

RPC_URL = "https://soroban-testnet.stellar.org"
HORIZON_URL = "https://horizon-testnet.stellar.org"
FRIENDBOT = "https://friendbot.stellar.org"
PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE
EXPLORER = "https://stellar.expert/explorer/testnet"
USDC = Asset("USDC", "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5")
BACKEND = Path(__file__).resolve().parents[1]
STATE = BACKEND / "var" / "testnet" / "deployment.json"
WASM = BACKEND / "contracts" / "target" / "wasm32v1-none" / "release" / "unifix_escrow.wasm"
WASM_DIR = BACKEND / "var" / "testnet"
REVIEW_WINDOW = 72 * 3600
SHORT_REVIEW_WINDOW = 120  # the short-windows build allows 60 s .. 14 min
MINUTE = 60


def _friendbot(address: str) -> None:
    url = f"{FRIENDBOT}?addr={address}"
    request = urllib.request.Request(url, headers={"User-Agent": "unifix-testnet-tool"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310  (fixed https URL)
        response.read()


def _submit(server: SorobanServer, tx: Any, *signers: Keypair) -> stellar_xdr.SCVal | None:
    """Prepare (simulate + assemble), sign, send, and wait for success. Returns the return value."""
    prepared = server.prepare_transaction(tx)
    for signer in signers:
        prepared.sign(signer)
    sent = server.send_transaction(prepared)
    if sent.status.value != "PENDING":
        raise RuntimeError(f"send failed: {sent.status} {sent.error_result_xdr}")
    result = server.poll_transaction(sent.hash, max_attempts=60, sleep_strategy=lambda _: 2)
    if result.status.value != "SUCCESS":
        raise RuntimeError(f"transaction {sent.hash} {result.status}")
    assert result.result_meta_xdr is not None
    meta = stellar_xdr.TransactionMeta.from_xdr(result.result_meta_xdr)
    soroban = (meta.v4 or meta.v3).soroban_meta  # type: ignore[union-attr]
    return soroban.return_value if soroban else None


def _classic(horizon: Server, source: Keypair, build: Any, *signers: Keypair) -> str:
    account = horizon.load_account(source.public_key)
    tx = build(TransactionBuilder(account, PASSPHRASE, base_fee=1000)).set_timeout(120).build()
    for signer in signers or (source,):
        tx.sign(signer)
    return str(horizon.submit_transaction(tx)["hash"])


def _deploy_contract(
    server: SorobanServer,
    deployer: Keypair,
    wasm: bytes,
    admin: str,
    arbiter: str,
    operator: str,
    token: str,
    review_window: int,
) -> str:
    account = server.load_account(deployer.public_key)
    upload = (
        TransactionBuilder(account, PASSPHRASE, 100_000).append_upload_contract_wasm_op(wasm).set_timeout(300)
    )
    _submit(server, upload.build(), deployer)
    account = server.load_account(deployer.public_key)
    create = (
        TransactionBuilder(account, PASSPHRASE, 100_000)
        .append_create_contract_op(
            wasm_id=hashlib.sha256(wasm).digest(),
            address=deployer.public_key,
            salt=secrets.token_bytes(32),
            constructor_args=[
                scval.to_address(admin),
                scval.to_address(arbiter),
                scval.to_address(operator),
                scval.to_address(token),
                scval.to_uint64(review_window),
            ],
        )
        .set_timeout(300)
    )
    value = _submit(server, create.build(), deployer)
    assert value is not None
    return str(scval.from_address(value).address)


def deploy() -> None:
    if STATE.exists():
        raise SystemExit(f"{STATE} exists; delete it to redeploy (testnet resets also require this).")
    wasm, short_wasm = (
        (WASM_DIR / "unifix_escrow.wasm").read_bytes(),
        (WASM_DIR / "unifix_escrow_short_windows.wasm").read_bytes(),
    )
    keys = {
        name: Keypair.random()
        for name in ("admin", "arbiter", "operator", "issuer", "customer", "professional")
    }
    for name, keypair in keys.items():
        print(f"friendbot → {name} {keypair.public_key}")
        _friendbot(keypair.public_key)
    server, horizon = SorobanServer(RPC_URL), Server(HORIZON_URL)
    test_asset = Asset("UFXT", keys["issuer"].public_key)

    # The test asset: trustlines, balances, and its Stellar Asset Contract.
    for party in ("customer", "professional"):
        _classic(horizon, keys[party], lambda b: b.append_change_trust_op(test_asset))
    _classic(
        horizon,
        keys["issuer"],
        lambda b: b.append_payment_op(keys["customer"].public_key, test_asset, "100000"),
    )
    account = server.load_account(keys["issuer"].public_key)
    sac_tx = (
        TransactionBuilder(account, PASSPHRASE, 100_000)
        .append_create_stellar_asset_contract_from_asset_op(test_asset)
        .set_timeout(300)
        .build()
    )
    _submit(server, sac_tx, keys["issuer"])
    test_sac = test_asset.contract_id(PASSPHRASE)

    roles = (keys["admin"].public_key, keys["arbiter"].public_key, keys["operator"].public_key)
    deployments = {
        "usdc": _deploy_contract(
            server, keys["admin"], wasm, *roles, USDC.contract_id(PASSPHRASE), REVIEW_WINDOW
        ),
        "test": _deploy_contract(server, keys["admin"], wasm, *roles, test_sac, REVIEW_WINDOW),
        "short": _deploy_contract(server, keys["admin"], short_wasm, *roles, test_sac, SHORT_REVIEW_WINDOW),
    }
    record = {
        "network": "TESTNET",
        "deployed_at": int(time.time()),
        "wasm_hash": hashlib.sha256(wasm).hexdigest(),
        "short_windows_wasm_hash": hashlib.sha256(short_wasm).hexdigest(),
        "contracts": deployments,
        "usdc": {"code": USDC.code, "issuer": USDC.issuer, "sac": USDC.contract_id(PASSPHRASE)},
        "test_asset": {"code": test_asset.code, "issuer": test_asset.issuer, "sac": test_sac},
        "review_windows": {"usdc": REVIEW_WINDOW, "test": REVIEW_WINDOW, "short": SHORT_REVIEW_WINDOW},
        "keys": {name: {"public": k.public_key, "secret": k.secret} for name, k in keys.items()},
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(record, indent=2))
    os.chmod(STATE, 0o600)
    for name, contract_id in deployments.items():
        print(f"{name:5} {contract_id}  {EXPLORER}/contract/{contract_id}")
    print(f"wasm sha256 {record['wasm_hash']} (short-windows {record['short_windows_wasm_hash']})")


# ---------------------------------------------------------------- smoke


class Smoke:
    def __init__(self, record: dict[str, Any], deployment: str) -> None:
        self.record = record
        self.keys = {name: Keypair.from_secret(v["secret"]) for name, v in record["keys"].items()}
        self.gateway = RpcGateway(
            rpc_url=RPC_URL,
            horizon_url=HORIZON_URL,
            passphrase=PASSPHRASE,
            contract_id=record["contracts"][deployment],
            timeout=30,
        )
        self.log: list[dict[str, Any]] = []

    async def call(
        self, label: str, signer: str, function: Function, args: list[Any], *, operator: bool = False
    ) -> str:
        keypair = self.keys[signer]
        prepared = await self.gateway.prepare_call(
            source=keypair.public_key,
            function=function,
            args=args,
            valid_until=int(time.time()) + 300,
            operator=self.keys["operator"] if operator else None,
        )
        prepared.envelope.sign(keypair)
        sent = await self.gateway.send(prepared.envelope)
        assert sent.status == "PENDING", sent
        for _ in range(60):
            status = await self.gateway.get_transaction(prepared.tx_hash)
            if status.status != "NOT_FOUND":
                break
            await asyncio.sleep(2)
        assert status.status == "SUCCESS", (label, status)
        self.log.append(
            {
                "step": label,
                "tx": prepared.tx_hash,
                "ledger": status.ledger,
                "url": f"{EXPLORER}/tx/{prepared.tx_hash}",
            }
        )
        print(f"  {label:38} {EXPLORER}/tx/{prepared.tx_hash}")
        return prepared.tx_hash

    async def expect_failure(
        self, label: str, signer: str, function: Function, args: list[Any], error: str
    ) -> None:
        try:
            await self.gateway.prepare_call(
                source=self.keys[signer].public_key,
                function=function,
                args=args,
                valid_until=int(time.time()) + 300,
            )
        except Exception as exc:  # the simulation must refuse it with the contract error
            if not getattr(exc, "code", "").endswith(error):
                raise AssertionError(f"{label}: expected {error}, got {exc!r}") from exc
            self.log.append({"step": label, "refused": getattr(exc, "code", str(exc))})
            print(f"  {label:38} refused on-chain: {exc.code}")  # type: ignore[attr-defined]
            return
        raise AssertionError(f"{label}: expected {error}")

    async def fund(self, refund_after: int, amount: int = 10_000_000) -> bytes:
        escrow_id = secrets.token_bytes(32)
        customer, professional = self.keys["customer"].public_key, self.keys["professional"].public_key
        args = contract.fund_args(
            escrow_id, customer, professional, amount, secrets.token_bytes(32), refund_after
        )
        await self.call("fund", "customer", Function.FUND, args, operator=True)
        return escrow_id

    async def status(self, escrow_id: bytes) -> contract.OnchainEscrow:
        escrow = await self.gateway.get_escrow(escrow_id)
        assert escrow is not None
        return escrow


async def smoke() -> None:
    record = json.loads(STATE.read_text())
    day = 86_400
    runs: dict[str, Any] = {}

    s = Smoke(record, "test")
    now = int(time.time())
    print("fund → submit_completion → release")
    e = await s.fund(now + 3 * day)
    await s.call(
        "submit_completion",
        "professional",
        Function.SUBMIT_COMPLETION,
        contract.submit_completion_args(e, secrets.token_bytes(32)),
    )
    await s.call("release", "customer", Function.RELEASE, contract.escrow_only_args(e))
    assert (await s.status(e)).status is contract.OnchainStatus.RELEASED
    await s.expect_failure(
        "release again (InvalidState)",
        "customer",
        Function.RELEASE,
        contract.escrow_only_args(e),
        "INVALID_STATE",
    )

    print("fund → refund")
    e = await s.fund(now + 3 * day)
    await s.call("refund", "professional", Function.REFUND, contract.escrow_only_args(e))
    assert (await s.status(e)).status is contract.OnchainStatus.REFUNDED

    print("fund → dispute → resolve (split)")
    e = await s.fund(now + 3 * day)
    await s.expect_failure(
        "resolve undisputed (InvalidState)",
        "arbiter",
        Function.RESOLVE,
        contract.resolve_args(e, 1),
        "INVALID_STATE",
    )
    await s.call(
        "open_dispute (customer)",
        "customer",
        Function.OPEN_DISPUTE,
        contract.open_dispute_args(e, s.keys["customer"].public_key),
    )
    await s.expect_failure(
        "finalize_expired on dispute",
        "operator",
        Function.FINALIZE_EXPIRED,
        contract.escrow_only_args(e),
        "INVALID_STATE",
    )
    await s.call(
        "resolve 30% to professional", "arbiter", Function.RESOLVE, contract.resolve_args(e, 3_000_000)
    )
    escrow = await s.status(e)
    assert (escrow.status, escrow.professional_payout, escrow.customer_refund) == (
        contract.OnchainStatus.RESOLVED,
        3_000_000,
        7_000_000,
    )

    print("fund → dispute → concede")
    e = await s.fund(now + 3 * day)
    await s.call(
        "open_dispute (professional)",
        "professional",
        Function.OPEN_DISPUTE,
        contract.open_dispute_args(e, s.keys["professional"].public_key),
    )
    await s.call("customer concedes (release)", "customer", Function.RELEASE, contract.escrow_only_args(e))
    assert (await s.status(e)).settled_by == "CUSTOMER"
    runs["test"] = s.log
    await s.gateway.close()

    print("short windows: fund → finalize_expired after refund_after; completion → auto-release")
    s = Smoke(record, "short")
    now = int(time.time())
    refund = await s.fund(now + 2 * MINUTE)
    release = await s.fund(now + 10 * MINUTE)
    await s.call(
        "submit_completion",
        "professional",
        Function.SUBMIT_COMPLETION,
        contract.submit_completion_args(release, secrets.token_bytes(32)),
    )
    await s.expect_failure(
        "finalize before deadline (NotExpired)",
        "operator",
        Function.FINALIZE_EXPIRED,
        contract.escrow_only_args(refund),
        "NOT_EXPIRED",
    )
    deadline = max((await s.status(refund)).refund_after, (await s.status(release)).review_deadline or 0)
    wait = max(0, deadline - int(time.time())) + 15
    print(f"  waiting {wait}s for the deadlines to mature on the ledger clock…")
    await asyncio.sleep(wait)
    await s.call(
        "finalize_expired → timeout refund",
        "operator",
        Function.FINALIZE_EXPIRED,
        contract.escrow_only_args(refund),
    )
    await s.call(
        "finalize_expired → auto-release",
        "operator",
        Function.FINALIZE_EXPIRED,
        contract.escrow_only_args(release),
    )
    assert ((await s.status(refund)).status, (await s.status(release)).status) == (
        contract.OnchainStatus.REFUNDED,
        contract.OnchainStatus.RELEASED,
    )
    assert (await s.status(refund)).settled_by == "TIMEOUT"

    # Events from the RPC event scan decode to our event names.
    page = await s.gateway.get_events(start_ledger=s.log[0]["ledger"], cursor=None, limit=50)
    names = [d.name for d in (contract.decode_event(e.topics, e.value) for e in page.events) if d]
    assert {"funded", "completion_submitted", "expired"} <= set(names), names
    runs["short"] = s.log
    await s.gateway.close()

    out = STATE.parent / f"smoke-{int(time.time())}.json"
    out.write_text(json.dumps(runs, indent=2))
    print(f"smoke passed; record written to {out}")


def env() -> None:
    record = json.loads(STATE.read_text())
    print(f"ESCROW_CONTRACT_ID={record['contracts']['usdc']}")
    print(f"STELLAR_OPERATOR_ADDRESS={record['keys']['operator']['public']}")
    print("# STELLAR_OPERATOR_SECRET: copy from var/testnet/deployment.json (never commit it)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["deploy", "smoke", "env"])
    command = parser.parse_args().command
    if command == "deploy":
        deploy()
    elif command == "smoke":
        asyncio.run(smoke())
    else:
        env()


if __name__ == "__main__":
    main()
