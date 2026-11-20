# UniFix

UniFix is a service marketplace for university campuses. Customers post jobs or message verified
professionals, accept a quotation, and pay into a Soroban escrow contract on Stellar. Funds are released
to the professional when the customer confirms the work, refunded when the job does not go ahead, or
split by an arbiter when there is a dispute. Reviews can only be left by customers who paid for a booking.

The repository has two apps:

| Folder | What it is |
|---|---|
| [`backend/`](backend/) | FastAPI + PostgreSQL 16 API, background reconciler and keeper, Soroban escrow contract (Rust) |
| [`frontend/`](frontend/) | Next.js 16 web app (App Router, TypeScript, Tailwind CSS v4, TanStack Query, Freighter wallet) |

> Everything runs on **Stellar testnet**. Mainnet and real money are out of scope.

## Contents

- [How a job works](#how-a-job-works)
- [Stellar testnet deployment (contract IDs)](#stellar-testnet-deployment-contract-ids)
- [Escrow contract](#escrow-contract)
- [Quick start](#quick-start)
- [Backend](#backend)
- [Frontend](#frontend)
- [API overview](#api-overview)
- [Testing](#testing)
- [Deployment](#deployment)
- [Security](#security)
- [Documentation index](#documentation-index)
- [Project status](#project-status)

## How a job works

1. A customer signs up with a university email and verifies it.
2. A professional signs up, builds a profile and portfolio, and submits verification documents. An admin
   approves or rejects them.
3. The customer posts a service request or opens a conversation with a professional.
4. The professional sends a quotation (price, scope, timeline). The customer accepts it, which creates a
   booking and freezes the agreed terms.
5. The customer links a Stellar wallet (Freighter, SEP-53 signed challenge) and funds the escrow. The
   backend operator co-signs `fund` so that the on-chain escrow is bound to the accepted agreement.
6. The professional starts the job, then submits completion evidence (photos, checklist, notes). The
   evidence hash is recorded on-chain with `submit_completion`.
7. The customer confirms and releases payment. If the customer does nothing, the keeper auto-releases
   after the review window.
8. Either side can open a dispute. An admin locks it, both sides add evidence, and the arbiter resolves
   it on-chain: full release, full refund, or a split. Either party can also concede.
9. The customer leaves a verified review. The professional's rating updates, and the professional can
   respond.
10. Admins see the whole transaction: users, bookings, escrows, chain transactions, reports, audit logs
    and operational status.

In-app notifications are created for every step above. Chat is real-time over WebSockets.

## Stellar testnet deployment (contract IDs)

Current deployment: **2026-11-19**, network `TESTNET`, made with `uv run python -m scripts.testnet deploy`.
Contract IDs and public addresses are public identifiers. The secret keys for this deployment are throwaway
keys kept in the gitignored `backend/var/testnet/deployment.json`. Never commit that file.

### Escrow contracts

| Deployment | Contract ID | Token | Review window | Used for |
|---|---|---|---|---|
| `usdc` | [`CDSJEO4U4MQRXY7KZDFV5HOBSIPIPIYGEOV7N7S5IMWFZ6BRQ7DMIH3I`](https://stellar.expert/explorer/testnet/contract/CDSJEO4U4MQRXY7KZDFV5HOBSIPIPIYGEOV7N7S5IMWFZ6BRQ7DMIH3I) | Circle testnet USDC | 259200 s (3 days) | The API and frontend demos (`ESCROW_CONTRACT_ID`) |
| `test` | [`CAZBLH7JPO3ZRQKLZOVQ5FD3LLCEJ6D5ZF7JB5Y7ZRMEEK7US5RWEB4A`](https://stellar.expert/explorer/testnet/contract/CAZBLH7JPO3ZRQKLZOVQ5FD3LLCEJ6D5ZF7JB5Y7ZRMEEK7US5RWEB4A) | UniFix test asset `UFXT` (mintable) | 259200 s (3 days) | Automated end-to-end tests |
| `short` | [`CBQFW6CMYERMHHH4SH6FC43Q37X6QMZW64OWQWDGENB44GBEJQBIWKF5`](https://stellar.expert/explorer/testnet/contract/CBQFW6CMYERMHHH4SH6FC43Q37X6QMZW64OWQWDGENB44GBEJQBIWKF5) | `UFXT` | 120 s | Test-only `short-windows` build (deadlines in minutes) for timeout and auto-release paths |

### Wasm builds

| Build | SHA-256 |
|---|---|
| Production | `39d31914a132fc9dd5ec0b5683c6261c461a37441a088bff326b3363cbeaca5a` |
| `short-windows` (test only) | `61e7e537e5b0ddbad3a1da757e724744a79088b58759ad5f5bbeff0485d963fc` |

soroban-sdk 29, target `wasm32v1-none`, built with Stellar CLI 30.0.1.

### Tokens

| Asset | Issuer | Stellar Asset Contract |
|---|---|---|
| `USDC` (Circle testnet) | `GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` | `CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA` |
| `UFXT` (UniFix test asset) | `GDWZ46OBWEXNGDD5ZVNITBY3NFZVCNFYFETBKJD4CRCWR5A3BBRGJJPY` | `CAWHEKXDL7A2WRLTZGPD2B7XT3BCDN7GRSPE3YIKL2HRH2XIM2DQ3HRF` |

### Contract roles (public addresses)

| Role | Address | Can do |
|---|---|---|
| Admin | `GD26KTMHFLOOPD6C2XFP5Y72PJJBW5BX7FNSUIX765AXUHW6IFSJ3XL2` | `set_admin`, `set_arbiter`, `set_operator` |
| Arbiter | `GBHQ5PL22NHB7YZD3TX2S2ARHWM7ED4WKIY7X57JDJYI4VMOST4MHF4Q` | `resolve` disputed escrows |
| Operator | `GBC7EX7YX5LHV76K5JTSLLREEK6BVVYEYBIGVZZ2WQEQI2HOT62I5SF4` | Co-signs `fund` only (`STELLAR_OPERATOR_ADDRESS`) |

These are throwaway testnet keys. Before any real value, the admin and arbiter must be human-held
multisig accounts (see [Security](#security)).

### Network endpoints

| Service | URL |
|---|---|
| Soroban RPC | `https://soroban-testnet.stellar.org` |
| Horizon | `https://horizon-testnet.stellar.org` |
| Explorer | `https://stellar.expert/explorer/testnet` |

### Verified on testnet

Transactions from the end-to-end run of 2026-11-19, driven through the HTTP API:

| Path | Steps |
|---|---|
| Happy path | [fund](https://stellar.expert/explorer/testnet/tx/d337a133114fbb5a1bb4d801ca0328c3bc0b9f4570a7d1cb266184ab149ddcba) · [submit_completion](https://stellar.expert/explorer/testnet/tx/25ce52a06ffdc2ae7c7b0765cd129ad9d380efea7d631ed951649372e095d0fb) · [release](https://stellar.expert/explorer/testnet/tx/36f34b5ee1ba014566d8ed7da6cc706e011c0e290fce4e5418f6d5ae649443f2) |
| Full PRD journey | [fund](https://stellar.expert/explorer/testnet/tx/78de75737b87007c8f81e91764c563302fe335a782541cd027f0bfa9d8cf4489) · [submit_completion](https://stellar.expert/explorer/testnet/tx/67ab1ba61c5b3e67edcc3951302e68e9c02c995d7ddee4e47a836eee9653d6e6) · [release](https://stellar.expert/explorer/testnet/tx/85c38e3be1aaa0997bb52dac43d46473ba57cb17e16ed3e532d8cfb103176e6b) |
| Refund | [fund](https://stellar.expert/explorer/testnet/tx/2802743ae73b811a39aee1be188ab7fe8607d85707206c35c811338b587a6136) · [refund](https://stellar.expert/explorer/testnet/tx/6ab2edbd0cbc3177de400a2a053ece475f322f6d4c2870888537aa7e2eb485c9) |
| Keeper auto-release | [fund](https://stellar.expert/explorer/testnet/tx/30f82ed4030dc04f67d4bcb9111af557095c97cb1469a628ffd2a938a949c6ab) · [submit_completion](https://stellar.expert/explorer/testnet/tx/1f7a509b555a79666c14a3da8b5b7ed2a8d0d4c376a4a3e24ca17bd48f98a1ac) · [finalize_expired](https://stellar.expert/explorer/testnet/tx/42868e6f8e2a9c77f6ebe0870b4846a38a13d594f31b540c39ee44bf7518eee4) |
| Arbiter: release | [fund](https://stellar.expert/explorer/testnet/tx/e2b49c9676ceccb0fa21dffdecae489ec34547e9eedec8b6d9729b2d6d373436) · [open_dispute](https://stellar.expert/explorer/testnet/tx/1ebcb474d1ee75f57b42634df07218bd1489bfe0b78a88cad4fce061ee7c4f37) · [resolve](https://stellar.expert/explorer/testnet/tx/944bee121e06d62221abc93ccdb417f0a23d6c06d0f58e6f8d1ce44c5a041378) |
| Arbiter: refund | [fund](https://stellar.expert/explorer/testnet/tx/12472f8c6ea342ea3bd4975a6cddacc0dcaa7b5fa8077b48eaf07920e03f0b40) · [open_dispute](https://stellar.expert/explorer/testnet/tx/b72599682467f4855909a52c4faf5a59889a8a71d979e5acb65ec8f46c7e0de2) · [resolve](https://stellar.expert/explorer/testnet/tx/eb8edd9f52207991a16d72481439e4386ee83d3e81382a0393cde7e3a3399ae3) |
| Customer concedes | [fund](https://stellar.expert/explorer/testnet/tx/e1881110030636460174582f5a68bcd3ccde53cf1751f31f1eb0034e07a5d6de) · [open_dispute](https://stellar.expert/explorer/testnet/tx/4e0a71d57af152d95f309973587c758723ff459a1f242f3eb9d136d97b4911b6) · [release](https://stellar.expert/explorer/testnet/tx/3e56d4d8dee9b4812ccdf5e75ad66d3de6a4208dd9dfb5f8ac2f623efad349d9) |
| Professional concedes | [fund](https://stellar.expert/explorer/testnet/tx/82d7d2678125a2831de7764e510eef6d14fb73da1ab98f2c1f12b5e6e83ad649) · [open_dispute](https://stellar.expert/explorer/testnet/tx/cd48748d7adf1108d2cb1064b227e806e440a94e0980cd651007af3cd24ef361) · [refund](https://stellar.expert/explorer/testnet/tx/5612a8a0a17f032280ae6615ed64ab2d5711b534af8c80d6f793abb9e98225c6) |

The same run confirmed that the contract refuses `finalize_expired` on a disputed escrow, a customer
refunding themselves, and a professional releasing to themselves. Run the suite again to produce a fresh
report (see [Testing](#testing)).

## Escrow contract

Source: [`backend/contracts/escrow`](backend/contracts/escrow) (Rust, soroban-sdk 29). Full design:
[`backend/docs/STELLAR_ESCROW_DESIGN.md`](backend/docs/STELLAR_ESCROW_DESIGN.md).

| Function | Caller | Effect |
|---|---|---|
| `__constructor` | Deployer | Sets admin, arbiter, operator, token and review window |
| `fund` | Customer, co-signed by operator | Locks tokens in escrow. The operator signature attests that the terms come from an accepted agreement |
| `submit_completion` | Professional | Records the completion evidence hash and starts the review window |
| `release` | Customer only | Pays the professional. During a dispute this is the customer's concession |
| `refund` | Professional only | Returns funds to the customer. During a dispute this is the professional's concession |
| `extend` | Customer | Moves the refund deadline later |
| `open_dispute` | Customer or professional | Freezes the escrow for the arbiter |
| `resolve` | Arbiter | Settles a disputed escrow: any amount to the professional, the rest to the customer |
| `finalize_expired` | Anyone (the backend keeper) | Auto-release after the review window, or timeout refund after `refund_after` |
| `get_escrow`, `config` | Anyone | Read state |
| `set_admin`, `set_arbiter`, `set_operator` | Admin | Rotate roles |

Escrow states: `Funded`, `CompletionSubmitted` and `Disputed` are open; `Released`, `Refunded` and
`Resolved` are terminal and cannot change. `fund` creates a `Funded` escrow, `submit_completion` moves it
to `CompletionSubmitted`, and `open_dispute` moves either open state to `Disputed`. When the arbiter
resolves a dispute, a full payout ends as `Released`, zero ends as `Refunded`, and a split ends as
`Resolved`. The contract is immutable: a policy change needs a new deployment, and existing escrows stay
on the old one.

Build and test:

```bash
cd backend/contracts
cargo test                                        # unit tests and randomised invariant tests
stellar contract build                            # production wasm
stellar contract build --features short-windows   # test-only build (deadlines in minutes)
```

Requires the `wasm32v1-none` Rust target (pinned in `rust-toolchain.toml`) and the Stellar CLI.

## Quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/) 0.13+, PostgreSQL 16 (or Docker), Node.js 20+,
and the [Freighter](https://www.freighter.app/) browser extension set to testnet for wallet steps.

```bash
# 1. Backend
cd backend
uv sync
cp .env.example .env            # set DATABASE_URL, TEST_DATABASE_URL, JWT_SECRET
docker compose up -d db         # or use a local PostgreSQL 16
export $(grep ^DATABASE_URL .env)
uv run alembic upgrade head
uv run python -m app.cli create-admin --email ops@unifix.local --name "UniFix Ops"
uv run uvicorn --factory app.main:app_factory --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev
```

- Frontend: http://localhost:3000
- API docs (Swagger UI): http://localhost:8000/api/v1/docs

Without `NEXT_PUBLIC_API_URL` the frontend runs in **demo mode**: an in-browser backend stores data in
`localStorage` and every chain transaction is simulated and labelled as such.

To enable real escrow payments, set these in `backend/.env`:

```bash
ESCROW_CONTRACT_ID=CDSJEO4U4MQRXY7KZDFV5HOBSIPIPIYGEOV7N7S5IMWFZ6BRQ7DMIH3I
ESCROW_TOKEN_CODE=USDC
ESCROW_TOKEN_ISSUER=GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5
ESCROW_TOKEN_CONTRACT_ID=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
ESCROW_REVIEW_WINDOW_SECONDS=259200
ESCROW_ID_SECRET=<32+ random bytes; never change once escrows exist>
STELLAR_OPERATOR_ADDRESS=GBC7EX7YX5LHV76K5JTSLLREEK6BVVYEYBIGVZZ2WQEQI2HOT62I5SF4
STELLAR_OPERATOR_SECRET=<operator secret from var/testnet/deployment.json>
```

At startup the API checks that the token contract matches `Asset(code, issuer)` and that the contract's
operator and review window match this configuration. It refuses to start if they do not.

## Backend

FastAPI app in [`backend/app`](backend/app), organised by module:

| Module | Responsibility |
|---|---|
| `users` | Registration, login, sessions, email verification, password reset |
| `professionals` | Profiles, portfolio, verification documents, discovery and search |
| `requests` | Service requests and the professional feed |
| `chat` | Conversations, messages, attachments, read receipts, reports, WebSocket hub, call sessions |
| `quotes` | Quotations: send, revise, withdraw, accept, reject |
| `bookings` | Bookings, frozen agreements, start, completion evidence, cancellation requests |
| `payments` | Wallet linking (SEP-53), escrow funding, release, refund, receipts, reconciler, keeper |
| `disputes` | Disputes, evidence, admin lock, arbiter resolution, concessions |
| `reviews` | Verified reviews, responses, reports, moderation, rating aggregates |
| `notifications` | In-app notifications, written in the same transaction as the event |
| `admin` | Users, bookings, escrows, chain transactions, reports queue, audit logs, ops status |
| `audit` | Append-only audit log of security and money events |

Key design points:

- **Auth:** short-lived JWT access token held in page memory, plus a rotating refresh token in an
  `HttpOnly`, `Secure`, `SameSite=Strict` cookie. Cookie routes check CSRF origin. WebSockets use
  one-time tickets and an `Origin` check.
- **Payments are exactly-once:** a reconciler reads chain events by cursor and applies each
  `(tx_hash, event_index)` once. A PostgreSQL advisory lock elects one leader across processes. The
  keeper calls `finalize_expired` for escrows past their deadline.
- **Layering** is enforced by `import-linter`: routers do not touch repositories, and `core` does not
  import modules.
- **Database:** PostgreSQL 16 only, Alembic migrations (`backend/migrations`), never SQLite.
- **Storage:** local disk in development, S3-compatible bucket in production, signed URLs only.

See [`backend/README.md`](backend/README.md) for the full setup, configuration table and Docker usage.

## Frontend

Next.js 16 app in [`frontend/`](frontend/).

| Route | Purpose |
|---|---|
| `/` | Landing page |
| `/sign-in`, `/sign-up` | Sign-in, customer and professional onboarding |
| `/home` | Dashboard: what needs attention, money in escrow, recent messages |
| `/discover` | Search and filter professionals |
| `/pros/[id]` | Professional profile, verification, ratings and reviews |
| `/messages`, `/messages/[id]` | Real-time chat, quotations, call UI, reporting |
| `/bookings`, `/bookings/[id]` | Bookings: funding, completion, approval, dispute, receipt, review |
| `/wallet` | Linked Stellar wallets and payment history |
| `/profile` | Account and professional profile settings |
| `/admin` | Verification queue, disputes, reports, users |
| `/terms`, `/privacy` | Legal pages |

Environment variables:

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | API base, e.g. `http://localhost:8000/api/v1`. Unset means demo mode |
| `NEXT_PUBLIC_HORIZON_URL` | Horizon endpoint, default `https://horizon-testnet.stellar.org` |

```bash
npm run dev     # development server on :3000
npm run build   # production build
npm run lint    # ESLint
```

## API overview

Base path `/api/v1`. The full contract is in
[`backend/docs/API_CONTRACT.md`](backend/docs/API_CONTRACT.md) and the generated schema is
[`backend/openapi.json`](backend/openapi.json).

| Area | Endpoints |
|---|---|
| Health | `GET /health`, `GET /ready` |
| Auth | `/auth/register`, `/login`, `/refresh`, `/logout`, `/logout-all`, `/me`, `/sessions`, `/change-password`, `/verify-email/*`, `/password-reset/*` |
| Reference data | `GET /campuses`, `GET /categories` |
| Professionals | `/professionals`, `/professionals/me`, portfolio, verifications, reviews |
| Service requests | `/service-requests`, `/feed`, `/mine`, `/{id}/respond`, `/{id}/cancel` |
| Chat | `/conversations`, messages, read, report; `POST /ws/tickets`; `WS /ws/conversations/{id}`; `/calls/sessions` |
| Quotes | `POST /quotes`, `/quotes/{id}/accept`, `/reject`, `/withdraw` |
| Bookings | `/bookings`, agreement, start, completion, cancel, cancellation requests, receipts, reviews, `POST /bookings/{id}/escrow` |
| Escrow | `/escrows/{id}`, `/funding`, `/release`, `/refund`, `/extend`, `/disputes` |
| Wallets | `/wallets`, `/wallets/challenge` |
| Disputes | `/disputes/{id}`, `/evidence`, `/lock`, `/resolve` |
| Reviews | `/reviews/{id}/response`, `/reviews/{id}/report` |
| Notifications | `GET /notifications`, `POST /notifications/read`, `GET /notifications/unread-count` |
| Uploads and files | `POST /uploads`, `GET /files/{id}` |
| Admin | `/admin/users`, `/bookings`, `/escrows`, `/chain-transactions`, `/service-requests`, `/disputes`, `/verifications`, `/reports`, `/reviews/{id}/moderate`, `/campuses`, `/categories`, `/audit-logs`, `/ops/status` |

## Testing

Backend quality gates (the same ones CI runs):

```bash
cd backend
uv run ruff check app tests scripts migrations
uv run ruff format --check app tests scripts migrations
uv run mypy
uv run lint-imports
uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head && uv run alembic check
uv run python -m scripts.export_openapi --check
uv run pytest -q          # real PostgreSQL via TEST_DATABASE_URL
```

- The test suite migrates and truncates the database named in `TEST_DATABASE_URL`. It refuses to run
  unless the database name contains `test`.
- Integration tests cover every module, an authorization matrix over every route and actor type, CSRF
  and CORS, notifications for every event, the admin console, and hardening (headers, body limits,
  production config validation, log redaction, upload fuzz cases).

Real testnet end-to-end suite (spends only testnet tokens):

```bash
uv run python -m scripts.testnet deploy     # once per testnet reset; writes var/testnet/deployment.json
uv run python -m scripts.testnet smoke      # every contract path, prints tx hashes
uv run python -m scripts.e2e_testnet        # full journey through the HTTP API
```

`scripts.e2e_testnet` writes `backend/var/testnet/E2E_REPORT.md` with a stellar.expert link for every
transaction.

CI (`.github/workflows/`): `backend` runs the gates above on PostgreSQL 16 and builds the contract;
`security` runs `pip-audit`, `cargo audit` and gitleaks.

## Deployment

See [`backend/docs/DEPLOYMENT.md`](backend/docs/DEPLOYMENT.md). In short:

- One API container (`backend/Dockerfile`, non-root, health check on `/health`), managed PostgreSQL 16,
  an S3-compatible private bucket, any SMTP provider, and the Next.js frontend.
- Frontend and API must be **same-site** for the refresh cookie, e.g. `app.<domain>` and `api.<domain>`.
  `*.vercel.app` and other public-suffix domains do not work without a rewrite.
- Migrations run as a release step (`alembic upgrade head`), never on API boot.
- With `ENV=production` the API refuses insecure configuration: non-`Secure` cookies, wildcard or
  non-https CORS origins, an empty origin list, the example JWT secret, or the console email backend.
- After a testnet reset, follow the redeploy runbook in DEPLOYMENT §7 and update the contract IDs in
  this README and in `backend/.env.example`.

## Security

The security review is in [`backend/docs/SECURITY_REVIEW.md`](backend/docs/SECURITY_REVIEW.md): risk
re-check, OWASP API Security Top 10, and open findings. The main open items before any real value:

- The arbiter is a single key. It must become a 2-of-3 multisig.
- There is no long-stop settlement for disputed funds if the arbiter never acts.
- Rate limits are enforced in the app and database only. Production needs edge limiting (proxy or WAF).
- The frontend needs a strict Content-Security-Policy.

Never commit `backend/.env` or `backend/var/`. Contract IDs and public addresses are safe to share;
secret keys (`S...`), `JWT_SECRET` and `ESCROW_ID_SECRET` are not.

## Documentation index

| Document | Contents |
|---|---|
| [`backend/README.md`](backend/README.md) | Backend setup, configuration, Docker |
| [`backend/docs/ARCHITECTURE.md`](backend/docs/ARCHITECTURE.md) | Modules, layering, auth, state machines, real-time, testing |
| [`backend/docs/API_CONTRACT.md`](backend/docs/API_CONTRACT.md) | REST and WebSocket contract |
| [`backend/docs/FRONTEND_INTEGRATION.md`](backend/docs/FRONTEND_INTEGRATION.md) | Connecting the frontend to the API |
| [`backend/docs/DATABASE_DESIGN.md`](backend/docs/DATABASE_DESIGN.md) | Tables, constraints, indexes, migration policy |
| [`backend/docs/STELLAR_ESCROW_DESIGN.md`](backend/docs/STELLAR_ESCROW_DESIGN.md) | Escrow contract, trust model, payment flows |
| [`backend/docs/DEVELOPMENT_PLAN.md`](backend/docs/DEVELOPMENT_PLAN.md) | The eight issues, order, decisions, risks |
| [`backend/docs/DEPLOYMENT.md`](backend/docs/DEPLOYMENT.md) | Deploying from scratch, backups, testnet reset |
| [`backend/docs/SECURITY_REVIEW.md`](backend/docs/SECURITY_REVIEW.md) | Security gate and open findings |
| [`frontend/README.md`](frontend/README.md) | Frontend setup and demo walkthrough |

## Project status

| Issue | Scope | Status |
|---|---|---|
| 1 | Foundation and auth | Merged |
| 2 | Professional discovery | Merged |
| 3 | Requests, quotes and bookings | Merged |
| 4 | Real-time communication | Merged |
| 5 | Stellar escrow contract | Branch `feat/issue-5-stellar-escrow` |
| 6 | Payments and reconciliation | Branch `feat/issue-6-payments-reconciliation` |
| 7 | Disputes and reviews | Branch `feat/issue-7-disputes-reviews` |
| 8 | Notifications, admin, security hardening, end-to-end tests | Branch `feat/issue-8-admin-hardening` |
| — | Frontend rebrand and redesign | Merged (PR #16) |
