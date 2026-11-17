# UniFix Backend — Architecture

Status: **Planning baseline, revision 2 (2026-11-17). Nothing described here is implemented yet.**

Revision 2:

- HttpOnly refresh cookies with CSRF defences (§6).
- snake_case API (§7).
- Single-use WebSocket tickets (§9).
- On-chain completion and deadline-based escrow policy (§8).
- Integer fiat and token units (§7).
- Exactly-once reconciler across restarts and instances (§10).
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
- **The backend never holds a key that can choose where customer funds go.** It holds one *operator* key, which can do two things:
  - co-sign the creation of an escrow, to attest that its terms match the accepted agreement;
  - pay the fee for triggering a deadline that has already passed, where the contract fixes the outcome.

  See [STELLAR_ESCROW_DESIGN.md §3](STELLAR_ESCROW_DESIGN.md#3-trust-model).

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
| Canonical JSON | `rfc8785` (RFC 8785 JCS); maintenance re-checked at Issue 3 | — | Deterministic agreement and escrow-terms hashing. Fallback is a restricted canonicaliser (ints, strings, arrays, objects only) proven equal on the RFC test vectors |
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
    │   │   ├── schemas.py          # APIModel base (snake_case, extra="forbid")
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

| Token | Format | Lifetime | Client storage | Server storage |
|---|---|---|---|---|
| Access | JWT HS256: `sub`, `sid` (session family), `role`, `iat`, `exp`, `jti` | 15 min | **JS memory only**, sent as `Authorization: Bearer` | — (stateless, but `sid` is checked per request) |
| Refresh | 256-bit random, opaque | 14 days idle / 30 days absolute; rotated on every use | **HttpOnly cookie** `__Secure-unifix_rt`, `Secure`, `SameSite=Strict`, `Path=/api/v1/auth`, host-only | SHA-256 hash in `auth_sessions` |

- **Browser sessions use the HttpOnly cookie for refresh only.** The cookie is never readable by JavaScript and is only sent to `/api/v1/auth/*`. The refresh token never appears in a response body. On app load, the frontend calls `/auth/refresh` to obtain an in-memory access token.
- **CSRF defences** apply only to routes that read or set the cookie (`/auth/login`, `/auth/register`, `/auth/refresh`, `/auth/logout`). Every other route requires the `Authorization` header, which browsers never attach on their own. The defences:
  1. `Origin` is required and must be in the allowlist.
  2. The custom header `X-CSRF-Protection: 1` is required. It forces a CORS preflight, which only allowlisted origins pass.
  3. The cookie is `SameSite=Strict`.
- **CORS:** an explicit origin list and `allow_credentials=true`. A wildcard origin is a startup error. `X-CSRF-Protection` is in the allowed headers.
- **Deployment constraint:** the frontend and API must be same-site (`app.<domain>` + `api.<domain>`, or a Next.js rewrite proxy). `*.vercel.app` previews are cross-site.
- **Rotation with reuse detection.** Every refresh issues a new cookie and marks the old token used. Presenting a used token revokes the entire session family. This is how a stolen token is detected.
- **Multi-tab race grace:** a token rotated less than 30 s ago, whose successor is unused, returns `409 REFRESH_RACE` and is not treated as reuse. The client retries with the cookie jar's newer cookie, and refreshes are serialised across tabs with the Web Locks API.
- Full frontend flow: API_CONTRACT §4.
- **Immediate revocation.** `current_user` loads the session row by `sid`, so logout, suspension and password change take effect at once. This costs one primary-key lookup per request, which is acceptable at MVP scale.
- **Passwords.** Argon2id with library defaults (tuned at implementation). Length 10–128. Rehash on login if the parameters change. Failed logins are counted per account and per IP in the database. Five failures cause a 15-minute lockout, and the message does not reveal whether the account exists.

**Authorization**

- `require_role(...)` handles coarse role checks in dependencies.
- **Ownership and participation checks live in services, not routers.** An example is "caller is this booking's customer". A missing resource and a resource the caller cannot see both return **404**, so IDs cannot be probed. Admin-only routes return 403 to non-admins.
- Issue 8 adds an **authorization matrix test**. It calls every route as anonymous, customer, other customer, professional, other professional and admin, and asserts the expected status for each.

## 7. API conventions (summary — full detail in API_CONTRACT.md)

- Base path `/api/v1`. The frontend sets `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`, so its existing relative paths keep working.
- **snake_case for every field and query parameter.** Pydantic field names are the wire names: no alias generators, and `extra="forbid"`, so a misspelled or camelCase field returns 422 instead of being silently dropped. Enum values are `UPPER_SNAKE_CASE`. The frontend's required changes are in API_CONTRACT §13.
- Errors: `{"detail": "...", "code": "MACHINE_CODE", "request_id": "...", "errors": [...]}`. `detail` is always a string.
- Lists return a JSON array. Pagination uses `limit`/`offset` (or `before` cursors for messages), with `X-Total-Count` and `X-Next-Offset` headers.
- **Money is never a float.**
  - Fiat: integer minor units plus an ISO 4217 code (`total_minor`, `currency`).
  - Token: an integer base-unit string plus an explicit asset object (`asset_amount`, `asset {code, issuer, sac_contract_id, decimals}`).
  - FX rates: decimal strings.
  - Conversion happens in exactly one place, `payments.fx`, using integer math and rounding up (STELLAR_ESCROW_DESIGN §8).
- Every state-changing financial route honours `Idempotency-Key`.

## 8. Domain workflows

### 8.1 Request → quote → booking

There are two entry points, and both end in a conversation:

- **Direct:** customer opens a conversation with a professional, using `POST /conversations`.
- **Open request:** customer posts a service request to a campus and category feed. A professional responds, which opens or reuses a conversation linked to that request.

Quotes live inside a conversation and are versioned. A new quote supersedes the previous pending one. **Quotes are never edited.** No endpoint edits a quote, and a DB trigger blocks changes to term columns and all deletes. Accepting a quote is one transaction that:

1. locks the quote, plus the service request if there is one;
2. checks that the caller is the customer, the quote is `PENDING` and unexpired, and no active booking exists for that conversation or request;
3. generates the booking ID and writes the immutable **agreement**: the RFC 8785 canonical JSON of every term, both parties and the booking ID, with SHA-256 → `agreement_hash`;
4. creates the booking in `PENDING_PAYMENT`, with its amount copied from the agreement;
5. marks the other pending quotes on the request `REJECTED`;
6. writes timeline and audit entries, and posts a system message to the chat.

The escrow is later bound to this agreement through the escrow-terms hash stored on-chain. That binding is specified in STELLAR_ESCROW_DESIGN §6.

### 8.2 Booking state machine

```
 [quote accepted] → PENDING_PAYMENT ──cancel (either party) / 7-day expiry──► CANCELLED
                          │
                          └─ fund confirmed on-chain ─► FUNDED ──professional starts──► IN_PROGRESS
                                                         │                                  │
                                                         │   professional's submit_completion confirmed
                                                         │                                  ▼
                                                         │                       COMPLETION_SUBMITTED
                                                         │                                  │
                                                         │      customer release confirmed, or review_deadline
                                                         │      passed and finalize_expired confirmed
                                                         │                                  ▼
                                                         │                              COMPLETED
   FUNDED | IN_PROGRESS: professional refund, or refund_after passed + finalize_expired ─► REFUNDED
   COMPLETION_SUBMITTED: professional refund ─► REFUNDED
   FUNDED | IN_PROGRESS | COMPLETION_SUBMITTED ── dispute lock confirmed ─► DISPUTED
   DISPUTED ─► COMPLETED (arbiter 100% to pro, or customer concedes)
             | REFUNDED  (arbiter 0%, professional concedes, or dispute_deadline fallback)
             | RESOLVED  (arbiter split)
```

| From | To | Actor | Guard |
|---|---|---|---|
| — | `PENDING_PAYMENT` | customer | accepts a `PENDING` quote; no active booking on that conversation or request |
| `PENDING_PAYMENT` | `CANCELLED` | customer, professional or system (7-day expiry) | no funding transaction pending or confirmed |
| `PENDING_PAYMENT` | `FUNDED` | reconciler | `funded` event confirmed **and** on-chain escrow matches the escrow terms (STELLAR_ESCROW_DESIGN §6) |
| `FUNDED` | `IN_PROGRESS` | professional | — (off-chain only) |
| `FUNDED`/`IN_PROGRESS` | `COMPLETION_SUBMITTED` | reconciler | `completion_submitted` event confirmed; evidence recorded off-chain first, with `evidence_hash` on-chain |
| `COMPLETION_SUBMITTED` | `COMPLETED` | reconciler | `released` event (customer, or `Timeout` auto-release) |
| `FUNDED`/`IN_PROGRESS`/`COMPLETION_SUBMITTED` | `REFUNDED` | reconciler | `refunded` event (professional refund, or `Timeout` after `refund_after` in Funded) |
| `FUNDED`/`IN_PROGRESS`/`COMPLETION_SUBMITTED` | `DISPUTED` | reconciler | `disputed` event. The off-chain dispute record blocks release and refund **preparation** at once (concessions excepted) |
| `DISPUTED` | `COMPLETED`/`REFUNDED`/`RESOLVED` | reconciler | `released` / `refunded` / `resolved` event: arbiter, concession, or timeout fallback |

Rules:

- Every transition goes through **one function**, `bookings.service.transition(booking, to, actor, reason)`. It checks the table above and writes `booking_events` plus an audit entry.
- Every financial transition is made **only** by the reconciler, from confirmed and verified chain data. No route can set one.
- Cancellation, refund, dispute and arbitration policies, with their deadlines, are specified in STELLAR_ESCROW_DESIGN §4. Every non-terminal state has a deadline-based exit, so funds are never permanently locked.
- FixMe's `TECHNICIAN_ACCEPTED` state is dropped. A professional accepts the job by issuing the quote.

### 8.3 Escrow state (mirrors the contract)

`CREATED` (off-chain, prepared) → `FUNDED` → `COMPLETION_SUBMITTED` → `RELEASED` | `REFUNDED` | `DISPUTED` → `RELEASED` | `REFUNDED` | `RESOLVED`.

The reconciliation status is tracked separately: `AWAITING_SIGNATURE` → `PENDING_CONFIRMATION` → `CONFIRMED` | `FAILED`. Full design: [STELLAR_ESCROW_DESIGN.md](STELLAR_ESCROW_DESIGN.md).

## 9. Real-time (WebSockets)

- **Authentication by single-use ticket. No auth token ever appears in a WebSocket URL.**
  1. The client calls `POST /api/v1/ws/tickets {scope, conversation_id}` with its Bearer token.
  2. The server checks membership and creates a ticket:
     - 256-bit random, stored as SHA-256 in `ws_tickets`;
     - **30-second** TTL and **single use**;
     - bound to the user, the session family, the scope and the conversation.
  3. The client connects to `WS /api/v1/ws/conversations/{id}?ticket=…`.
  4. **Before `accept()`**, the server:
     - checks `Origin` against the allowlist (blocks cross-site WebSocket hijacking);
     - consumes the ticket with one atomic `UPDATE … SET used_at = now() WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now() RETURNING …`;
     - checks the scope matches the path;
     - checks the session is not revoked and the user is `ACTIVE`;
     - re-checks membership.
  5. While connected, the server re-validates the session every 60 s and closes the connection when it is revoked. Connections are capped at 1 h (close `4000`), so the client reconnects with a new ticket.
  6. A ticket left in a log is worthless once used or after 30 s, and query strings are redacted from access logs anyway.
  7. Tickets live in PostgreSQL, so they work across instances.
- Rejected alternatives:
  - an access JWT in the query string (replayable for 15 min);
  - a bearer token in `Sec-WebSocket-Protocol` (misuses the header, and it still gets logged by proxies);
  - cookie auth on the socket (the refresh cookie is path-restricted to `/auth`, and a cookie-authenticated socket needs the same Origin defences anyway).
- **Message writes go through REST** (`POST /conversations/{id}/messages`). The service persists the message, commits, and then publishes `message.created` to the hub. Over the socket, the client sends only ephemeral events: `typing`, `read`, `call.*` signaling and `ping`.
- **Hub:** an in-process `dict[conversation_id, set[WebSocket]]`, with bounded per-connection send queues so a slow client cannot block others. This supports **one API instance**, which is the MVP deployment. If we need more than one instance, the hub changes to fan out through PostgreSQL `LISTEN/NOTIFY`. That is a contained change inside `chat/hub.py`, with no new infrastructure.
- Call signaling (`call.offer`, `call.answer`, `call.ice`, `call.end`) is relayed only to the other participant of an active call session. The backend does not handle media. STUN/TURN servers come from config, and **no TURN server is provided**, so calls may fail behind strict NATs.

## 10. Stellar integration (summary)

- `stellar/` wraps Soroban RPC (simulate, prepare, send, getTransaction, getEvents, getLatestLedger) and Horizon (account existence, trustlines). It also holds the network passphrase check, operator auth-entry signing, and the "signed envelope equals prepared envelope" check.
- `payments/` builds the contract-call transactions for the **user's wallet to sign**: `fund`, `submit_completion`, `release`, `refund`, `extend`, `open_dispute`, `resolve`. It accepts the signed XDR, submits it, and runs the **reconciler** and **keeper**.
- **Reconciler (exactly once):**
  - Every chain effect, whether from our own transactions or the contract event scan, is ingested into `chain_events` under `UNIQUE (tx_hash, event_index)`.
  - Each event is applied in one DB transaction that locks the event, escrow and booking rows, re-reads `get_escrow` from the chain, and writes every derived row behind its own unique key. The event cursor advances in the same transaction.
  - A PostgreSQL session advisory lock, held on a dedicated non-pooled connection, picks one leader among all processes and instances. Correctness does **not** depend on the lock: overlapping leaders still apply each event once.
  - After a restart, everything resumes from the DB.
  - If the RPC's ~7-day event retention has been exceeded, a full `get_escrow` sweep runs (`app.cli reconcile --full`).
  - Full specification: STELLAR_ESCROW_DESIGN §10.
- **Keeper:** the leader submits the permissionless `finalize_expired` for escrows whose deadline has passed, using the operator account as fee payer. The contract fixes the outcome, so the keeper cannot choose a recipient or an amount.

## 11. Files and uploads

- `POST /uploads` (multipart) → `{id, url, contentType, size, …}`. Messages, portfolio items, evidence and verification records then reference file IDs. Base64 `dataUrl`s inside JSON are not accepted.
- Validation: size cap per purpose; detect the real type from file bytes; allow images (jpeg/png/webp) and PDFs (verification documents only). Pillow re-encodes images, which strips EXIF and GPS. This matters for student privacy.
- Visibility: `PUBLIC` (avatars, portfolio) or `PRIVATE` (chat attachments, evidence, verification documents). Private files are served by `GET /files/{id}`, which applies the access policy for each purpose. Verification documents are visible to the owner and admins only.
- Storage is behind one small interface with two implementations: local disk (dev and test) and S3-compatible (prod, e.g. Cloudflare R2 or AWS S3). The prod implementation is the only storage dependency added.

## 12. Observability and operations

- JSON logs with request ID, user ID and route. A redaction filter removes `Authorization` and `Cookie`/`Set-Cookie` headers, `ticket` and `token` query parameters, `password`, `signed_xdr` and secrets.
- `GET /health` checks the process only. `GET /ready` checks the DB and that Soroban RPC is reachable.
- `GET /api/v1/admin/ops/status` (Issue 8) reports: pending-transaction count, age of the oldest pending transaction, reconciler cursor ledger versus the latest ledger, and the last reconciler error.
- An error-tracking provider such as Sentry is optional and needs approval. It is not wired by default.

## 13. Testing strategy

| Layer | What | Where it runs |
|---|---|---|
| Unit | Pure functions: state machine table, money math, agreement hashing, XDR checks, policy functions | Every CI run |
| Integration (PostgreSQL) | Every endpoint through `httpx.AsyncClient` against a real PG 16 database migrated by Alembic; each test isolated by a rolled-back outer transaction; factories for fixtures | Every CI run (PG service container) and locally (Homebrew PG) |
| Concurrency | Parallel `accept quote`, parallel `submit funding`, two reconciler leaders forced to overlap, the same event ingested twice, a crash injected between apply steps: exactly one effect | Every CI run |
| Auth transport | Cookie attributes per environment, CSRF rejection (missing or foreign `Origin`, missing `X-CSRF-Protection`), refresh rotation, reuse revocation, race grace, WS ticket single use, expiry and scope mismatch, WS `Origin` rejection | Every CI run |
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
