# UniFix Backend — Architecture

Status: **Planning baseline (2026-11-17). Nothing described here is implemented yet.**
Owner: Ladipo Samuel (backend). Consumer: Victor (frontend, `frontend/`).

Related documents:

- [API_CONTRACT.md](API_CONTRACT.md): the REST and WebSocket contract for the frontend
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md): entities, constraints and indexes
- [STELLAR_ESCROW_DESIGN.md](STELLAR_ESCROW_DESIGN.md): the Soroban contract, trust model and payment flows
- [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md): the eight issues, order, branches and decisions

---

## 1. Context and inputs

| Input | Location | How it is used |
|---|---|---|
| FixMe PRD (MVP 1.0, Sept 2026) | `~/Documents/fixme-v1/Fixme-v1/prd.md` (outside this repo) | Requirements background only. No FixMe code is reused. |
| Onboarding brief (Nov 2026) | Ladipo's onboarding prompt | The authoritative current scope: university-first, Stellar escrow, chat, disputes, reviews. |
| Victor's frontend | `frontend/` (Next.js 16) | Defines the API shapes the frontend already calls (`frontend/src/lib/api/live.ts`, `contract.ts`, `types.ts`). |

The frontend README says routes come from "PRD section 10". Section 10 of the FixMe PRD is "Repair Request Page", so the frontend was built against a different "Handi" PRD that is not in the workspace. Where the frontend and the brief disagree, this plan follows the brief and lists each change Victor needs in [API_CONTRACT.md §13](API_CONTRACT.md#13-changes-the-frontend-needs).

## 2. System overview

```
 Browser (Next.js, Freighter wallet)
   │  HTTPS REST /api/v1/*         WSS /api/v1/ws/*
   ▼
 ┌──────────────────────── UniFix API (FastAPI, one process) ────────────────────────┐
 │ routers → services → repositories → SQLAlchemy models                             │
 │ in-process WebSocket hub · in-process chain reconciler (advisory-locked)          │
 └───────┬──────────────────────────┬─────────────────────────────┬──────────────────┘
         ▼                          ▼                             ▼
   PostgreSQL 16              Object storage                Stellar testnet
   (all state)                (local disk in dev,           Soroban RPC + Horizon
                              S3-compatible in prod)        UniFix Escrow contract
```

- **Modular monolith.** One deployable, one database, clear module boundaries. No Redis, Celery, Kafka or Kubernetes. See §9 for when that would change.
- **The chain is the source of truth for money.** The database mirrors on-chain escrow state through a reconciler. No database write can move funds.
- **The backend never holds a key that can move customer funds.** It holds one *operator* key. That key can only co-sign the creation of an escrow, to attest that its terms match the accepted agreement. See [STELLAR_ESCROW_DESIGN.md §3](STELLAR_ESCROW_DESIGN.md#3-trust-model).

## 3. Technology choices

Versions were checked on PyPI and crates.io on 2026-11-17. They are pinned in `uv.lock` / `Cargo.lock` when Issue 1 (or 5) starts, re-checked then, and kept to supported stable releases.

| Concern | Choice | Version seen | Why |
|---|---|---|---|
| Runtime | Python 3.12 | 3.12.10 installed | Installed locally; supported by every dependency below |
| Packaging | uv + `pyproject.toml` + `uv.lock` | uv 0.13.7 | Fast, reproducible, already installed |
| Web | FastAPI + Uvicorn | 0.163.x / 0.54.x | Async REST + WebSockets + OpenAPI |
| Validation | Pydantic v2 + pydantic-settings | 2.14.x / 2.16.x | Explicit schemas, typed config |
| ORM | SQLAlchemy 2.x (async) | 2.1.x | Typed `Mapped[]` models, async sessions |
| Driver | psycopg 3 (async + sync) | 3.3.x | One driver for the app (async) and Alembic (sync); supports LISTEN/NOTIFY if needed later |
| Migrations | Alembic | 1.20.x | Standard for SQLAlchemy |
| DB | PostgreSQL 16 | 16.15 installed (Homebrew) | Same major version in dev, CI and prod |
| Passwords | argon2-cffi (Argon2id) | 25.1 | Current OWASP recommendation |
| Tokens | PyJWT (HS256 access tokens) | 2.15.x | Small, well-maintained |
| Stellar | stellar-sdk (Python) | 17.0.x | Soroban RPC client, XDR, auth-entry signing, SEP-53 message verification |
| Contracts | Rust + soroban-sdk | rustc 1.98 / soroban-sdk 29.0.x | Official Soroban SDK |
| Images | Pillow | — | Decode, verify and re-encode uploads, strip EXIF/GPS |
| Tests | pytest, pytest-asyncio, httpx | pytest 9.2 | Async API tests against real PostgreSQL |
| Lint/type | ruff, mypy | — | Enforced in CI |

**Missing locally:** Docker, the `stellar` CLI, and the Rust `wasm32v1-none` target. PostgreSQL is installed but not running. See [DEVELOPMENT_PLAN.md §6](DEVELOPMENT_PLAN.md#6-readiness).

## 4. Repository layout (monorepo)

The backend lives in `backend/` of `ladicodes/UniFix`. Nothing under `frontend/` is modified.

```
UniFix/
├── frontend/                      # Victor — not touched by backend work
├── .github/workflows/backend.yml  # CI, runs only on backend/** changes (Issue 1)
└── backend/
    ├── pyproject.toml  uv.lock  alembic.ini  .env.example
    ├── Dockerfile  docker-compose.yml  README.md
    ├── app/
    │   ├── main.py                 # create_app(): middleware, routers, lifespan
    │   ├── cli.py                  # create-admin, seed, reconcile --once, deploy helpers
    │   ├── core/                   # cross-cutting, no business rules
    │   │   ├── config.py           # Settings (pydantic-settings), single source of config
    │   │   ├── db.py               # engine, async session factory, Base, naming convention
    │   │   ├── security.py         # hashing, JWT encode/decode, token hashing
    │   │   ├── errors.py           # AppError hierarchy + exception handlers
    │   │   ├── schemas.py          # APIModel base (camelCase out, both cases in)
    │   │   ├── pagination.py       # limit/offset + cursor helpers, headers
    │   │   ├── money.py            # minor-unit helpers, currency enum
    │   │   ├── logging.py          # JSON logs, request IDs, redaction
    │   │   └── ratelimit.py        # DB-backed limiter for auth-sensitive routes
    │   ├── api/
    │   │   ├── deps.py             # get_session, current_user, require_role(...)
    │   │   └── v1.py               # mounts every module router under /api/v1
    │   └── modules/
    │       ├── audit/              # audit_logs (append-only) + record()       — Issue 1
    │       ├── auth/               # register/login/refresh/logout/reset         — Issue 1
    │       ├── users/              # profile, account status                     — Issue 1
    │       ├── campuses/                                                          — Issue 2
    │       ├── catalog/            # service categories                          — Issue 2
    │       ├── professionals/      # profiles, verification, portfolio, search   — Issue 2
    │       ├── uploads/            # files, storage backends, access policy      — Issue 2
    │       ├── chat/               # conversations, messages, WS hub, reports    — Issue 4
    │       ├── calls/              # call sessions + signaling relay             — Issue 4
    │       ├── requests/           # service requests                            — Issue 3
    │       ├── quotes/             # quotes, agreements                          — Issue 3
    │       ├── bookings/           # booking state machine, timeline, idempotency— Issue 3
    │       ├── wallets/            # challenge + SEP-53 verification             — Issue 5
    │       ├── stellar/            # RPC client, tx builder, XDR checks, contract bindings — Issue 5
    │       ├── payments/           # escrow orchestration, reconciler, ledger, receipts — Issue 6
    │       ├── completion/         # evidence + approval                         — Issue 6
    │       ├── disputes/                                                          — Issue 7
    │       ├── reviews/                                                           — Issue 7
    │       ├── notifications/                                                     — Issue 8
    │       └── admin/              # cross-cutting admin views, ops status       — Issue 8
    ├── migrations/versions/        # Alembic, one or more revisions per issue
    ├── contracts/                  # Cargo workspace — Issue 5
    │   └── escrow/ src/lib.rs, src/test.rs, Makefile
    ├── scripts/                    # testnet deploy, e2e driver
    ├── tests/
    │   ├── conftest.py             # PG test DB, migrations, client, factories
    │   ├── unit/  integration/  e2e/
    └── docs/                       # these documents
```

Each module has the same files, and only the ones it needs:

| File | Responsibility | May import |
|---|---|---|
| `models.py` | SQLAlchemy tables for this module | `core.db`; other modules' models only by string name in `relationship()` |
| `schemas.py` | Pydantic request/response models | `core.schemas` |
| `repository.py` | Query functions taking `AsyncSession`. No business rules, no commits | own models |
| `service.py` | Business rules, authorization checks, state transitions, transaction boundary | own repository, *other modules' services* |
| `router.py` | HTTP/WS wiring only: parse, call one service function, map to schema | own service, `api.deps` |
| `policies.py` (optional) | Pure functions such as `can_view_conversation(user, conv)` | nothing stateful |

**Import rules (checked in CI with `import-linter`):**

1. `core` imports no module.
2. Routers never import repositories or other modules.
3. Cross-module calls go service → service. Dependencies point one way: `auth/users ← campuses/catalog ← professionals ← chat ← quotes/bookings ← payments/completion ← disputes/reviews`. `audit`, `uploads` and `notifications` are leaf services that anything may call.
4. Cycles are a build failure.

## 5. Request lifecycle and transactions

1. Middleware assigns `X-Request-ID`, starts a timer, and binds the request ID to log context.
2. `get_session` yields one `AsyncSession` per request.
3. A service function is the **unit of work**: it opens `async with session.begin():`, performs its checks and writes, and commits once. Routers never commit.
4. Financial and state-changing operations lock the rows they read with `SELECT … FOR UPDATE` (booking, escrow, quote) before checking state. Optimistic `version` columns protect against stale admin edits.
5. Side effects that must not roll back (WebSocket broadcast, email) run **after** commit through a small per-request `after_commit` list. If the transaction fails, they do not fire.
6. `AppError` subclasses carry `status_code`, `code` and `detail`. One handler renders them into the error envelope. Unhandled exceptions return 500 with the request ID and are logged with a stack trace. They are never swallowed.

## 6. Authentication and authorization

**Accounts**

- Roles: `customer`, `professional`, `admin`. Admins cannot self-register. They are created with `uv run python -m app.cli create-admin`.
- Account status: `ACTIVE`, `SUSPENDED`, `DEACTIVATED`. Suspension revokes all sessions immediately.
- Email is the login identifier. It is case-insensitive (`citext`) and unique. A university email address is **not** required. Campus is a self-declared association (see Issue 2).
- Email verification and password reset use single-use, hashed, expiring tokens. Email is sent over SMTP (any provider). In `ENV=development` the sender writes the link to the console log, and that mode refuses to start when `ENV=production`.

**Tokens**

| Token | Format | Lifetime | Storage |
|---|---|---|---|
| Access | JWT HS256: `sub` (user id), `sid` (session id), `role`, `iat`, `exp`, `jti` | 15 min | Client memory/localStorage (current frontend) |
| Refresh | 256-bit random, opaque | 30 days, rotated on every use | Server stores only SHA-256 hash in `auth_sessions` |

- **Rotation with reuse detection.** Every refresh issues a new refresh token and marks the old one used. Presenting a used token revokes the entire session family. This is how a stolen token is detected.
- **Immediate revocation.** `current_user` loads the session row by `sid`, so logout, suspension and password change take effect at once. This costs one primary-key lookup per request, which is acceptable at MVP scale.
- **Passwords.** Argon2id with library defaults (tuned at implementation). Length 10–128. Rehash on login if the parameters change. Failed logins are counted per account and per IP in the database. Five failures cause a 15-minute lockout, and the message does not reveal whether the account exists.

**Authorization**

- `require_role(...)` handles coarse role checks in dependencies.
- **Ownership and participation checks live in services, not routers.** An example is "caller is this booking's customer". A missing resource and a resource the caller cannot see both return **404**, so IDs cannot be probed. Admin-only routes return 403 to non-admins.
- Issue 8 adds an **authorization matrix test**. It calls every route as anonymous, customer, other customer, professional, other professional and admin, and asserts the expected status for each.

## 7. API conventions (summary — full detail in API_CONTRACT.md)

- Base path `/api/v1`. The frontend sets `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`, so its existing relative paths keep working.
- JSON responses are **camelCase**. Request bodies accept camelCase **or** snake_case, because the current frontend sends both (`conversationId` and `professional_id`).
- Errors: `{"detail": "...", "code": "MACHINE_CODE", "requestId": "...", "errors": [...]}`. `detail` is always a string, which the frontend already reads.
- Lists return a JSON array, matching the current frontend. Pagination uses `limit`/`offset` (or `before` cursors for messages), and the totals come back in `X-Total-Count` and `X-Next-Offset` headers.
- Money in requests and responses is a decimal number in **major units** (naira). Storage is integer **minor units** (kobo). On-chain token amounts are also returned as an exact string, `amountUnits`.
- Every state-changing financial route honours `Idempotency-Key`.

## 8. Domain workflows

### 8.1 Request → quote → booking

There are two entry points, and both end in a conversation:

- **Direct:** customer opens a conversation with a professional, using `POST /conversations`.
- **Open request:** customer posts a service request to a campus and category feed. A professional responds, which opens or reuses a conversation linked to that request.

Quotes live inside a conversation and are versioned. A new quote supersedes the previous pending one. Accepting a quote is one transaction that:

1. locks the quote, plus the service request if there is one;
2. checks that the caller is the customer, the quote is `PENDING`, and no active booking exists for that conversation or request;
3. writes an immutable **agreement**: the canonical JSON of the terms and both parties, with SHA-256 → `agreementHash`;
4. creates the booking in `PENDING_PAYMENT`;
5. marks the other pending quotes on the request `REJECTED`;
6. writes timeline and audit entries, and posts a system message to the chat.

### 8.2 Booking state machine

```
                      ┌──────────── cancel (either party, no funds) ───────────┐
                      │                                                        ▼
 [quote accepted] → PENDING_PAYMENT ──fund confirmed on-chain──► FUNDED      CANCELLED
                                                                 │  │
                                     professional starts ◄───────┘  └─ professional refunds ─► REFUNDED
                                                │
                                           IN_PROGRESS ──professional submits evidence──► COMPLETION_SUBMITTED
                                                                                                │
                                                     customer approves + release confirmed ◄────┘
                                                                     ▼
                                                                COMPLETED  (terminal, review allowed)

 FUNDED | IN_PROGRESS | COMPLETION_SUBMITTED ──dispute lock confirmed on-chain──► DISPUTED
 DISPUTED ──arbiter resolution confirmed──► COMPLETED (100% to pro) | REFUNDED (100% to customer) | RESOLVED (split)
```

| From | To | Actor | Guard |
|---|---|---|---|
| — | `PENDING_PAYMENT` | customer | accepts a `PENDING` quote; no active booking on that conversation or request |
| `PENDING_PAYMENT` | `CANCELLED` | customer or professional | no escrow funding confirmed or pending |
| `PENDING_PAYMENT` | `FUNDED` | system (reconciler) | `funded` event confirmed **and** on-chain escrow matches the agreement |
| `FUNDED` | `IN_PROGRESS` | professional | — |
| `FUNDED`/`IN_PROGRESS` | `REFUNDED` | system | professional's refund tx confirmed |
| `IN_PROGRESS` | `COMPLETION_SUBMITTED` | professional | evidence has ≥1 photo or a note |
| `COMPLETION_SUBMITTED` | `COMPLETED` | system | customer's release tx confirmed |
| `FUNDED`/`IN_PROGRESS`/`COMPLETION_SUBMITTED` | `DISPUTED` | system | `disputed` event confirmed (the off-chain dispute record blocks release preparation immediately) |
| `DISPUTED` | `COMPLETED`/`REFUNDED`/`RESOLVED` | system | arbiter `resolved` event confirmed |

Rules:

- Every transition goes through **one function**, `bookings.service.transition(booking, to, actor, reason)`. That function checks the table above, writes `booking_events`, and writes an audit entry.
- The financial transitions are **only** made by the reconciler, from confirmed chain data. No API lets a user set them.
- FixMe's `TECHNICIAN_ACCEPTED` state is dropped. A professional accepts the job by issuing the quote.

### 8.3 Escrow state (mirrors the contract)

`CREATED` (off-chain, prepared) → `FUNDED` → `RELEASED` | `REFUNDED` | `DISPUTED` → `RELEASED` | `REFUNDED` | `RESOLVED`.

The reconciliation status is tracked separately: `AWAITING_SIGNATURE` → `PENDING_CONFIRMATION` → `CONFIRMED` | `FAILED`. Full design: [STELLAR_ESCROW_DESIGN.md](STELLAR_ESCROW_DESIGN.md).

## 9. Real-time (WebSockets)

- `WS /api/v1/ws/conversations/{id}?token=<access JWT>` is the route the frontend already uses. The server validates the token and conversation membership **before** `accept()`. It closes with `4401` for an invalid token and `4403`/`4404` for no access. It closes with `4401` again when the token expires, and the client reconnects with a fresh token.
- **Message writes go through REST** (`POST /conversations/{id}/messages`). The service persists the message, commits, and then publishes `message.created` to the hub. Over the socket, the client sends only ephemeral events: `typing`, `read`, `call.*` signaling and `ping`.
- **Hub:** an in-process `dict[conversation_id, set[WebSocket]]`, with bounded per-connection send queues so a slow client cannot block others. This supports **one API instance**, which is the MVP deployment. If we need more than one instance, the hub changes to fan out through PostgreSQL `LISTEN/NOTIFY`. That is a contained change inside `chat/hub.py`, with no new infrastructure.
- Access tokens in query strings can leak through logs. Uvicorn access logs are configured to redact query strings. A short-lived single-use `ws ticket` is offered as a decision in DEVELOPMENT_PLAN.
- Call signaling (`call.offer`, `call.answer`, `call.ice`, `call.end`) is relayed only to the other participant of an active call session. The backend does not handle media. STUN/TURN servers come from config, and **no TURN server is provided**, so calls may fail behind strict NATs.

## 10. Stellar integration (summary)

- `stellar/` wraps Soroban RPC (simulate, prepare, send, getTransaction, getEvents, getLatestLedger) and Horizon (account existence, trustlines). It also holds the network passphrase check, operator auth-entry signing, and the "signed envelope equals prepared envelope" check.
- `payments/` builds `fund`/`release`/`refund`/`open_dispute`/`resolve` transactions for the **user's wallet to sign**. It accepts the signed XDR, submits it, and runs the **reconciler**.
- **Reconciler:** an asyncio task started in the app lifespan. It runs only while holding a PostgreSQL advisory lock, so only one runs even with several workers. Every few seconds it polls `getTransaction` for submitted transactions, and every ~30 s it scans contract events from a stored ledger cursor. That catches transactions submitted outside our API. `app.cli reconcile --once` does the same job for cron or manual recovery.

## 11. Files and uploads

- `POST /uploads` (multipart) → `{id, url, contentType, size, …}`. Messages, portfolio items, evidence and verification records then reference file IDs. Base64 `dataUrl`s inside JSON are not accepted.
- Validation: size cap per purpose; detect the real type from file bytes; allow images (jpeg/png/webp) and PDFs (verification documents only). Pillow re-encodes images, which strips EXIF and GPS. This matters for student privacy.
- Visibility: `PUBLIC` (avatars, portfolio) or `PRIVATE` (chat attachments, evidence, verification documents). Private files are served by `GET /files/{id}`, which applies the access policy for each purpose. Verification documents are visible to the owner and admins only.
- Storage is behind one small interface with two implementations: local disk (dev and test) and S3-compatible (prod, e.g. Cloudflare R2 or AWS S3). The prod implementation is the only storage dependency added.

## 12. Observability and operations

- JSON logs with request ID, user ID and route. A redaction filter removes `Authorization` headers, `token`, `password`, `signed_xdr` and secrets.
- `GET /health` checks the process only. `GET /ready` checks the DB and that Soroban RPC is reachable.
- `GET /api/v1/admin/ops/status` (Issue 8) reports: pending-transaction count, age of the oldest pending transaction, reconciler cursor ledger versus the latest ledger, and the last reconciler error.
- An error-tracking provider such as Sentry is optional and needs approval. It is not wired by default.

## 13. Testing strategy

| Layer | What | Where it runs |
|---|---|---|
| Unit | Pure functions: state machine table, money math, agreement hashing, XDR checks, policy functions | Every CI run |
| Integration (PostgreSQL) | Every endpoint through `httpx.AsyncClient` against a real PG 16 database migrated by Alembic; each test isolated by a rolled-back outer transaction; factories for fixtures | Every CI run (PG service container) and locally (Homebrew PG) |
| Concurrency | Parallel `accept quote`, parallel `submit funding`, parallel reconciler passes using separate connections: exactly one winner | Every CI run |
| Migrations | `alembic upgrade head` → `downgrade base` → `upgrade head` on an empty database | Every CI run |
| Contract | Rust tests with `soroban-sdk` testutils and a real Stellar Asset Contract: every function, every auth failure, every invalid state transition, balance conservation | Every CI run (`cargo test`) |
| Stellar adapter | Recorded RPC responses for parsing and error paths (unit level only, never presented as integration) | Every CI run |
| Testnet E2E | A script drives the real API plus real testnet: generated throwaway keypairs funded by Friendbot, a test asset minted by a harness-controlled issuer, the full happy path, the refund path, the dispute release/refund/split paths | On demand / nightly. Marked `@pytest.mark.testnet`. Results reported with tx hashes |

SQLite is never used. A test only counts as passed if it was actually executed.

## 14. Deployment

- **Container:** a multi-stage `Dockerfile` (uv install, non-root user, `uvicorn app.main:app`). `docker-compose.yml` runs `db` (postgres:16) + `api` for local parity.
- **Startup:** `alembic upgrade head` runs as a release step, not on every boot. One instance (see §9).
- **Target:** any container platform with managed PostgreSQL, such as Render, Railway or Fly.io. The choice is pending your approval.
- **Secrets:** environment variables only (`JWT_SECRET`, `DATABASE_URL`, `STELLAR_OPERATOR_SECRET`, SMTP and S3 credentials). `.env.example` contains no real values. The operator secret is never logged, returned or stored in the database.
- **Testnet caveat:** SDF resets Stellar testnet periodically. Contract deployment is scripted (`scripts/deploy_testnet.py`), and the contract ID lives in config, so redeploying is a five-minute job. Escrow rows from before a reset are marked by network epoch.
