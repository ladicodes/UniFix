"""Migrations match the models, and the committed OpenAPI document matches the code."""

from __future__ import annotations

import json
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.core.db import Base
from app.main import create_app
from scripts.export_openapi import render_openapi
from tests.conftest import make_settings

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi.json"


def test_migrations_produce_exactly_the_model_schema(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert diff == []


def test_committed_openapi_matches_generated(migrated_database: str) -> None:
    generated = render_openapi(create_app(make_settings(migrated_database)))
    assert OPENAPI_PATH.exists(), "Run: uv run python -m scripts.export_openapi"
    assert json.loads(OPENAPI_PATH.read_text()) == json.loads(generated), (
        "openapi.json is stale. Run: uv run python -m scripts.export_openapi"
    )


def test_every_route_declares_response_model_and_error_responses(migrated_database: str) -> None:
    """Checked on the generated OpenAPI document: FastAPI mounts included routers lazily, so
    ``app.routes`` alone does not list them."""
    schema = create_app(make_settings(migrated_database)).openapi()
    operations = [
        (path, method, operation)
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if path.startswith("/api/v1/")
    ]
    assert len(operations) >= 10  # guard against silently checking nothing
    for path, method, operation in operations:
        label = f"{method.upper()} {path}"
        assert operation.get("summary"), f"{label} has no summary"
        codes = set(operation["responses"])
        errors = {code for code in codes if code.startswith(("4", "5"))}
        assert errors, f"{label} documents no error responses"
        success = sorted(code for code in codes if code.startswith("2"))
        assert success, f"{label} documents no success response"
        if path.startswith("/api/v1/files/"):
            continue  # binary download
        if success[0] not in {"202", "204"}:
            content = operation["responses"][success[0]].get("content", {})
            assert content.get("application/json", {}).get("schema"), f"{label} has no response schema"
