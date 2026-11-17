"""Shared fixtures.

Integration tests run against a real PostgreSQL database (``TEST_DATABASE_URL``), migrated
with Alembic at the start of the session. Tests exercise real commits; every table is
truncated after each test so tests stay independent.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.clock import FrozenClock
from app.core.config import Environment, Settings
from app.core.container import Services, build_services
from app.main import create_app
from app.seed import seed
from tests.support import ALLOWED_ORIGIN, API_BASE_URL, RecordingEmailSender

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        env_file = BACKEND_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("TEST_DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
    if not url:
        pytest.exit("TEST_DATABASE_URL is not set (see backend/.env.example)", returncode=2)
    if "test" not in url.rsplit("/", 1)[-1]:
        pytest.exit("Refusing to run: TEST_DATABASE_URL database name must contain 'test'", returncode=2)
    return url


def _alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    return _test_database_url()


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    """Upgrade → downgrade → upgrade, proving the migration chain round-trips, then hand over."""
    config = _alembic_config(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return database_url


@pytest.fixture(scope="session")
def table_names(migrated_database: str) -> list[str]:
    engine = create_engine(migrated_database)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        names = sorted(row[0] for row in rows)
    engine.dispose()
    return names


def make_settings(database_url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "env": Environment.TEST,
        "database_url": database_url,
        "database_pool_size": 5,
        "jwt_secret": "test-secret-" + "x" * 40,
        "cors_origins": [ALLOWED_ORIGIN],
        "cookie_secure": True,
        "log_json": False,
        "log_level": "WARNING",
        # Fast, still-real Argon2id parameters for tests only (production enforces the minimums).
        "password_hash_time_cost": 1,
        "password_hash_memory_kib": 1024,
        "password_hash_parallelism": 1,
        "auth_ip_rate_limit_per_minute": 10_000,
        "email_action_rate_limit_per_hour": 10_000,
        "frontend_base_url": ALLOWED_ORIGIN,
        "local_storage_dir": str(BACKEND_DIR / "var" / "test-uploads"),
        "upload_rate_limit_per_hour": 10_000,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.fixture
def settings(migrated_database: str) -> Settings:
    return make_settings(migrated_database)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def email_outbox() -> RecordingEmailSender:
    return RecordingEmailSender()


@pytest.fixture
async def services(
    settings: Settings, clock: FrozenClock, email_outbox: RecordingEmailSender, table_names: list[str]
) -> AsyncIterator[Services]:
    built = build_services(settings, clock=clock)
    built.email = email_outbox  # test double: records instead of sending
    yield built
    async with built.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
    await built.engine.dispose()


@pytest.fixture
async def seeded(services: Services) -> Services:
    """Reference categories and campuses (app.seed), as a deployment would have."""
    async with services.session_factory() as session:
        await seed(session)
    return services


@pytest.fixture
async def client(services: Services) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(services.settings, services=services)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=API_BASE_URL) as http:
        yield http


@pytest.fixture
async def live_server(services: Services) -> AsyncIterator[str]:
    """A real uvicorn server (same event loop) for WebSocket tests. Yields its base URL."""
    import asyncio

    import uvicorn

    app = create_app(services.settings, services=services)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="off", ws="websockets-sansio"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110  (uvicorn exposes no 'started' event)
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    await task


@pytest.fixture
def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"
