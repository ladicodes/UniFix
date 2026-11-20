"""Real Stellar TESTNET fixtures. Opt in with ``UNIFIX_TESTNET=1 uv run pytest -m testnet``.

Uses the deployments recorded by ``scripts/testnet.py deploy`` (var/testnet/deployment.json, never
committed) and the real RPC/Horizon. The database is the local PostgreSQL test database.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from stellar_sdk import Keypair

from app.core.container import Services, build_services
from app.main import create_app
from app.modules.payments.reconciler import Reconciler
from app.modules.stellar.context import StellarContext, build_stellar, startup_check
from app.seed import seed
from tests.conftest import make_settings
from tests.support import API_BASE_URL, RecordingEmailSender

RECORD = Path(__file__).resolve().parents[2] / "var" / "testnet" / "deployment.json"


@pytest.fixture(scope="session")
def deployment() -> dict[str, Any]:
    if os.environ.get("UNIFIX_TESTNET") != "1" or not RECORD.exists():
        pytest.skip("set UNIFIX_TESTNET=1 and run scripts/testnet.py deploy first")
    return dict(json.loads(RECORD.read_text()))


class Testnet:
    __test__ = False  # a helper, not a test class

    def __init__(
        self,
        services: Services,
        stellar: StellarContext,
        client: httpx.AsyncClient,
        outbox: RecordingEmailSender,
        record: dict[str, Any],
    ) -> None:
        self.services, self.stellar, self.client, self.outbox = services, stellar, client, outbox
        self.reconciler = Reconciler(services, stellar)
        self.keys = {name: Keypair.from_secret(v["secret"]) for name, v in record["keys"].items()}
        self.log: list[dict[str, Any]] = []

    async def until(self, check: Callable[[], Awaitable[bool]], what: str, timeout: float = 120) -> None:
        """Run the reconciler until ``check`` holds (real ledgers close every ~5 s)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await self.reconciler.tick()
            if await check():
                return
            await asyncio.sleep(3)
        raise AssertionError(f"timed out waiting for {what}")


async def _testnet(
    deployment: dict[str, Any], table_names: list[str], migrated_database: str, which: str, **overrides: Any
) -> AsyncIterator[Testnet]:
    asset = deployment["test_asset"]
    settings = make_settings(
        migrated_database,
        escrow_contract_id=deployment["contracts"][which],
        escrow_token_code=asset["code"],
        escrow_token_issuer=asset["issuer"],
        escrow_token_contract_id=asset["sac"],
        escrow_review_window_seconds=deployment["review_windows"][which],
        escrow_deadline_unit_seconds=60 if which == "short" else 86_400,
        stellar_operator_secret=deployment["keys"]["operator"]["secret"],
        stellar_operator_address=deployment["keys"]["operator"]["public"],
        stellar_check_on_startup=True,
        **overrides,
    )
    services = build_services(settings)  # real clock: the ledger clock is real time
    outbox = RecordingEmailSender()
    services.email = outbox
    stellar = build_stellar(settings)
    await startup_check(stellar)
    assert stellar.gateway is not None
    latest = await stellar.gateway.latest_ledger()
    services.settings = settings.model_copy(update={"reconciler_start_ledger": latest - 2})
    async with services.session_factory() as session:
        await seed(session)
    app = create_app(services.settings, services=services, stellar=stellar)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=API_BASE_URL, timeout=60
    ) as http:
        yield Testnet(services, stellar, http, outbox, deployment)
    await stellar.gateway.close()
    async with services.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
    await services.engine.dispose()


@pytest.fixture
async def testnet(
    deployment: dict[str, Any], table_names: list[str], migrated_database: str
) -> AsyncIterator[Testnet]:
    async for value in _testnet(deployment, table_names, migrated_database, "test"):
        yield value


@pytest.fixture
async def testnet_short(
    deployment: dict[str, Any], table_names: list[str], migrated_database: str
) -> AsyncIterator[Testnet]:
    async for value in _testnet(deployment, table_names, migrated_database, "short", keeper_delay_seconds=0):
        yield value
