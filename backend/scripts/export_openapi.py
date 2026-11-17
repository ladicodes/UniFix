"""Write (or check) the committed OpenAPI document.

    uv run python -m scripts.export_openapi          # write backend/openapi.json
    uv run python -m scripts.export_openapi --check  # exit 1 if it is stale (CI)

Uses placeholder settings: generating the schema never connects to a database.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi import FastAPI

from app.core.config import Environment, Settings
from app.main import create_app

OUTPUT = Path(__file__).resolve().parent.parent / "openapi.json"


def render_openapi(app: FastAPI) -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def _placeholder_app() -> FastAPI:
    settings = Settings(
        _env_file=None,
        env=Environment.TEST,
        database_url="postgresql+psycopg://openapi:openapi@localhost:5432/openapi_unused",
        jwt_secret="openapi-generation-only-" + "x" * 32,
        cors_origins=["http://localhost:3000"],
    )
    return create_app(settings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if openapi.json is out of date")
    args = parser.parse_args()
    rendered = render_openapi(_placeholder_app())
    if args.check:
        if not OUTPUT.exists() or json.loads(OUTPUT.read_text()) != json.loads(rendered):
            print("openapi.json is stale; run: uv run python -m scripts.export_openapi", file=sys.stderr)
            return 1
        print("openapi.json is up to date")
        return 0
    OUTPUT.write_text(rendered)
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
