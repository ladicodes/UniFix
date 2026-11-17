# UniFix Backend

FastAPI + PostgreSQL backend for UniFix, the university service marketplace. The Soroban escrow on Stellar testnet arrives in Batch 2.

| Document | Purpose |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Modules, layering, auth, state machines, real-time, testing, deployment |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | REST and WebSocket contract for the frontend |
| [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md) | Tables, constraints, indexes, migration policy |
| [docs/STELLAR_ESCROW_DESIGN.md](docs/STELLAR_ESCROW_DESIGN.md) | Escrow contract, trust model, payment flows |
| [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md) | The eight issues, order, branches, decisions, risks |
| [openapi.json](openapi.json) | Generated OpenAPI schema (CI fails if it is stale) |

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13+
- PostgreSQL 16 (local install or `docker compose up db`)

## Local setup

```bash
cd backend
uv sync                                   # installs runtime + dev dependencies from uv.lock
cp .env.example .env                      # then set DATABASE_URL, TEST_DATABASE_URL, JWT_SECRET

# One-time database setup (local PostgreSQL; adjust names/passwords):
psql -d postgres -c "CREATE ROLE unifix LOGIN PASSWORD 'choose-a-password'"
psql -d postgres -c "CREATE DATABASE unifix_dev OWNER unifix"
psql -d postgres -c "CREATE DATABASE unifix_test OWNER unifix"

uv run alembic upgrade head               # uses DATABASE_URL from the environment
uv run python -m app.cli create-admin --email ops@unifix.local --name "UniFix Ops"
uv run uvicorn --factory app.main:app_factory --reload --port 8000
```

- Swagger UI: http://localhost:8000/api/v1/docs
- The frontend uses `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`. `localhost:3000` and `localhost:8000` are same-site, so the refresh cookie works locally with `COOKIE_SECURE=false`.
- Alembic reads `DATABASE_URL` from the process environment, so export it first, e.g. `export $(grep ^DATABASE_URL .env)`.
- With `EMAIL_BACKEND=console`, verification and reset links are printed to the server log (development/test only).

## Quality gates (the same ones CI runs)

```bash
uv run ruff check app tests scripts migrations
uv run ruff format --check app tests scripts migrations
uv run mypy                                # strict
uv run lint-imports                        # module-boundary contracts
uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head && uv run alembic check
uv run python -m scripts.export_openapi --check
uv run pytest -q                           # real PostgreSQL via TEST_DATABASE_URL; never SQLite
```

- The test suite **migrates and truncates** the database named in `TEST_DATABASE_URL`. It refuses to run unless the database name contains `test`.
- After changing routes or schemas, regenerate the schema with `uv run python -m scripts.export_openapi` and commit `openapi.json`.

## Docker

```bash
docker build -t unifix-backend backend
cd backend && docker compose up --build   # db + one-shot migrate + api on :8000
```

Migrations run as a separate release step (the `migrate` service). They never run on every API boot.

## Configuration

Every option is read and validated in `app/core/config.py`. Production (`ENV=production`) refuses to start with:

- `COOKIE_SECURE=false`;
- an empty CORS allowlist, or any non-https origin;
- a wildcard origin (refused in every environment);
- the example JWT secret;
- the console email backend;
- weak password-hashing parameters.

| Variable | Notes |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…` |
| `JWT_SECRET` | ≥ 32 bytes, random |
| `CORS_ORIGINS` | Comma-separated explicit origins |
| `COOKIE_SECURE` | `true` except plain-http local development |
| `EMAIL_BACKEND` | `console` (dev/test) or `smtp` with `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_TLS_MODE`, `EMAIL_FROM`. Works with any SMTP provider |
| `FRONTEND_BASE_URL` | Base for links in emails |
| `FORWARDED_ALLOW_IPS` | (Docker) proxy addresses trusted for `X-Forwarded-For` |
