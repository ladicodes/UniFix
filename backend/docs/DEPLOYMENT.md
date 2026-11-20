# UniFix backend: deployment guide

Audience: whoever deploys the API from scratch. You should not need to read the code.
Status: written for Issue 8 (2026-11-19). The hosting platform (decision D18) and the production
domains (D4a, to be agreed between Ladipo and Victor) are still open, so this guide is
platform-neutral. Every step works on any container platform with managed PostgreSQL 16 (Render,
Railway, Fly.io, a VM with Docker). **Deploying needs explicit approval first.**

## 1. What you deploy

| Component | Notes |
|---|---|
| API container | `backend/Dockerfile`. Non-root, `ENV=production` by default, health check on `/health`. **One instance** (the WebSocket hub and the reconciler leader are in-process; multi-instance scaling is out of scope). |
| PostgreSQL 16 | Managed. Daily backups with point-in-time recovery if the provider offers it (§6). |
| S3-compatible bucket | Private bucket for uploads (AWS S3, Cloudflare R2, Backblaze B2, MinIO). Signed URLs only; no public ACLs. |
| SMTP | Any provider (verification and password-reset emails). |
| Stellar | Soroban RPC + Horizon endpoints and the deployed escrow contract (testnet for now; mainnet is excluded). |
| Frontend | Next.js app, deployed separately on the same registrable domain (§2). |

## 2. Domain topology (same-site requirement, D4a)

The refresh cookie is `__Secure-unifix_rt`, `HttpOnly`, `Secure`, `SameSite=Strict`, path
`/api/v1/auth`. Browsers only send it when the frontend and API are **same-site**:

- Recommended: `app.<domain>` (frontend) + `api.<domain>` (API), e.g. `app.unifix.ng` + `api.unifix.ng`.
- Alternative: serve the API under the frontend origin through a Next.js rewrite (`/api/v1/*` → API).
- `*.vercel.app` (or any other Public Suffix List domain) is cross-site to everything else. Previews must
  use the rewrite or a custom preview domain.

Set `CORS_ORIGINS=https://app.<domain>` and `FRONTEND_BASE_URL=https://app.<domain>`. The same list is
the CSRF origin allowlist for cookie routes and the WebSocket `Origin` allowlist.

**Verify after deploying:** sign in on the frontend, reload the page (the access token is in memory,
so a reload exercises `/auth/refresh` with the cookie), and confirm that you stay signed in.

## 3. Configuration

All configuration is environment variables (see `backend/.env.example`). With `ENV=production` the
API **refuses to start** if any of these is insecure:

| Check | Requirement |
|---|---|
| `JWT_SECRET` | ≥ 32 bytes, not the example value |
| `COOKIE_SECURE` | `true` |
| `CORS_ORIGINS` | non-empty, all `https://`, no `*` |
| `FRONTEND_BASE_URL` | `https://` and listed in `CORS_ORIGINS` |
| `EMAIL_BACKEND` | `smtp` (with `SMTP_HOST`) |
| `STORAGE_BACKEND` | `s3` (with `S3_BUCKET`) |
| Password hashing | `PASSWORD_HASH_MEMORY_KIB` ≥ 65536, `PASSWORD_HASH_TIME_COST` ≥ 3 |
| Secrets | `ESCROW_ID_SECRET`, `SMTP_PASSWORD`, `S3_SECRET_ACCESS_KEY` not the example value |
| `LOG_LEVEL` | not `DEBUG` |
| Escrow | `ESCROW_TOKEN_CONTRACT_ID` matches `Asset(code, issuer)`; the operator secret matches `STELLAR_OPERATOR_ADDRESS`; the short-windows test build is refused; a demo FX rate is refused off testnet |

Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Keep them in the
platform's secret store only. `STELLAR_OPERATOR_SECRET` is the fee-payer/co-signer key: it can never
move escrowed funds (the contract pays only the stored parties), but it pays fees, so fund it modestly.
Arbiter and admin keys are **never** configured on the server (D11).

Other production settings:

| Variable | Value |
|---|---|
| `ENV` | `production` (the image default) |
| `DATABASE_URL` | `postgresql+psycopg://…` with `sslmode=require` if the provider supports it |
| `FORWARDED_ALLOW_IPS` | the platform proxy's address range, so client IPs (rate limits, audit) are real |
| `EXPOSE_API_DOCS` | unset (Swagger UI and `openapi.json` are hidden in production); `true` to publish them |
| `MAX_REQUEST_BODY_BYTES` / `MAX_UPLOAD_BODY_BYTES` | defaults 1 MiB / 11 MiB |
| `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | from the bucket provider |
| `STELLAR_*`, `ESCROW_*`, `FX_DEMO_RATE_*` | from `uv run python -m scripts.testnet env` (testnet) |

## 4. First deployment

1. **Build** the image from `backend/`: `docker build -t unifix-backend backend` (CI builds it on every push).
2. **Database:** create the database and a role that owns it.
3. **Release step (migrations)**, before the new version receives traffic:
   `docker run --rm --env-file prod.env unifix-backend alembic upgrade head`.
   Configure it as the platform's release/pre-deploy command, not as part of the container start.
4. **Seed** lookup data once: `docker run --rm --env-file prod.env unifix-backend python -m app.cli seed`.
5. **Create the first admin:**
   `docker run --rm -it --env-file prod.env unifix-backend python -m app.cli create-admin --email ops@<domain> --name "UniFix Ops"`.
   Admins cannot self-register. The admin who arbitrates disputes links the arbiter's Freighter wallet
   in the app (the wallet must equal the on-chain arbiter).
6. **Run** one instance. Recommended container flags: `--read-only --tmpfs /tmp`. Health check:
   `GET /health` (process) and `GET /ready` (database). RPC health is in `/admin/ops/status`.
7. **Verify:**
   - `curl -sI https://api.<domain>/health` shows `strict-transport-security`, `content-security-policy`,
     `x-content-type-options` and no `server` header.
   - Sign in as the admin and open `GET /api/v1/admin/ops/status`: `rpc.healthy: true`,
     `pending_tx_count: 0`, `failed_verification_count: 0`, small `reconciler.cursor_lag_ledgers`.
   - Run the same-site check in §2.

## 5. Updating

1. CI must be green (lint, types, import contracts, migration round trip, OpenAPI, tests, contract
   tests, dependency audits, secret scan, Docker build).
2. Deploy the new image with the release step (`alembic upgrade head`). Migrations are additive
   within an issue; never edit a merged revision.
3. Rollback: redeploy the previous image. Run `alembic downgrade <revision>` only if the newer
   revision's downgrade is known to be safe for the data written since; otherwise restore (§6).

The reconciler resumes from the database after any restart (cursor and events are persisted), so a
restart mid-confirmation is safe.

## 6. PostgreSQL backup and restore

- Enable the provider's automated daily backups and point-in-time recovery (7 days minimum).
- Before each release with a migration, take a manual snapshot, or:
  `pg_dump --format=custom --no-owner "$DATABASE_URL_PLAIN" > unifix-$(date +%F).dump`
  (`DATABASE_URL_PLAIN` is the same URL with `postgresql://` instead of `postgresql+psycopg://`).
- Restore into an **empty** database:
  `pg_restore --no-owner --dbname "$TARGET_URL" unifix-YYYY-MM-DD.dump`, then point `DATABASE_URL` at it
  and run `alembic current` to confirm the revision.
- Test a restore at least once before launch.
- The chain is the source of truth for money: after a restore, the reconciler re-ingests contract
  events since its cursor, and `python -m app.cli reconcile --full` compares every open escrow with the
  contract to catch any gap. The `audit_logs` table is
  append-only (UPDATE and DELETE are blocked by a trigger) and is restored with the rest.

## 7. Testnet reset runbook

SDF resets Stellar testnet periodically; every contract and account disappears.

1. Check: `GET /admin/ops/status` shows RPC errors or `cursor_lag_ledgers` jumps; stellar.expert shows
   the contract as missing.
2. Redeploy from `backend/`: `uv run python -m scripts.testnet deploy` (new keys via Friendbot, test asset,
   wasm, the three contract deployments; written to `var/testnet/deployment.json`, which is gitignored).
3. Smoke test: `uv run python -m scripts.testnet smoke`.
4. Print the new configuration: `uv run python -m scripts.testnet env`. Update the platform's
   `ESCROW_CONTRACT_ID`, `STELLAR_OPERATOR_SECRET`, `STELLAR_OPERATOR_ADDRESS`, `ESCROW_ID_SECRET`, and
   bump `STELLAR_NETWORK_EPOCH` so old escrow rows are clearly from the previous network.
5. Redeploy the API; confirm `/ready` and `/admin/ops/status` (`rpc.healthy: true`).
6. Optional: run the full journey, `uv run python -m scripts.e2e_testnet`, and keep `var/testnet/E2E_REPORT.md`.
7. Users must re-link wallets (new network accounts) and fund new escrows. Escrows from the old epoch
   cannot settle; tell affected users.

## 8. Operations

- Logs are JSON on stdout with request IDs; tokens, cookies, passwords, signed XDR and Stellar secret
  seeds are redacted.
- Watch `GET /admin/ops/status` (admin only): pending transactions and their oldest age, transactions
  awaiting a signature, escrows that failed verification, conflicting or unapplied chain events,
  reconciler leader, cursor lag and last error, RPC health, open disputes and reports.
- Admins get in-app notifications for `CHAIN_VERIFICATION_FAILED`, dispute locks, SLA reminders and
  escalations.
