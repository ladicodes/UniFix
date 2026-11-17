"""Migrations match the models, and the committed OpenAPI document matches the code."""

from __future__ import annotations

import json
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.routing import APIRoute
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
    application = create_app(make_settings(migrated_database))
    for route in application.routes:
        if not isinstance(route, APIRoute):
            continue
        no_body = route.status_code in {202, 204}
        assert no_body or route.response_model is not None, f"{route.path} has no response model"
        if route.path.startswith("/api/v1"):
            documented_errors = {int(code) for code in route.responses if str(code).startswith(("4", "5"))}
            assert documented_errors, f"{route.path} documents no error responses"
            assert route.summary, f"{route.path} has no summary"
