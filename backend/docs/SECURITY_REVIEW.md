# UniFix backend: security review (Issue 8 gate)

Date: 2026-11-19 · Scope: `backend/` (FastAPI API, PostgreSQL schema, Soroban escrow contract, Stellar
adapter, CI) at the head of `feat/issue-8-admin-hardening` · Network: Stellar **testnet** only.

This review re-checks every risk in DEVELOPMENT_PLAN §8 and the OWASP API Security Top 10 (2023).
Each item names the control and the test or documented check that proves it. Findings that are not
fixed are listed in §4 with severity. **There are no open critical or high findings for the testnet
MVP.** Two items become high before any real-value (mainnet) use; §4 marks them.

## 1. How it was checked

| Check | Where | Result (2026-11-19) |
|---|---|---|
| Authorization matrix: every route in the live OpenAPI schema × anonymous / customer / professional / admin | `tests/integration/test_authorization_matrix.py` | Pass. Anonymous reaches only the 14 listed public routes; every admin route returns `403 ROLE_FORBIDDEN` to non-admins and passes the role check for admins; no route returns 5xx for any role with unknown ids |
| IDOR on bookings, chats, files, disputes, notifications | Per-module integration tests (404 on not-visible) and `test_notifications.py::test_list_read_and_unread_count_are_owner_only` | Pass |
| CSRF and Origin checks on cookie routes; WS ticket and Origin checks | `test_csrf_cors_cookies.py`, `test_realtime.py`, matrix (`CSRF_REJECTED` for anonymous cookie routes) | Pass |
| Production configuration validation | `tests/unit/test_config.py` (one case per insecure setting) | Pass |
| Log redaction (bearer tokens, cookies, tickets, passwords, signed XDR, Stellar secret seeds, `*secret*` JSON keys) | `tests/unit/test_logging_and_email.py` | Pass |
| Upload fuzz cases (spoofed types, polyglots, oversize, decompression bomb, EXIF stripping) | `test_verification_and_uploads.py` | Pass |
| Request size limits (declared and chunked bodies), security headers, HSTS and docs in production | `tests/integration/test_hardening.py` | Pass |
| Rate limits, including the per-user write backstop | `test_auth.py`, `test_chat.py`, `test_requests.py`, `test_wallets.py`, `test_hardening.py` | Pass |
| Money safety: DB tampering cannot release funds; terms binding; exactly-once reconciler; concurrency | `test_payments.py`, `test_disputes_reviews.py` | Pass |
| Contract rules (every auth failure and invalid transition, invariants under random sequences) | `cargo test` in `backend/contracts` (29 tests) | Pass |
| Real testnet: PRD journey with negative paths, refund, keeper timeout, three arbiter outcomes, both concessions, on-chain refusals | `tests/testnet/*`, `scripts/e2e_testnet.py` | Pass (tx hashes in the Issue 8 PR) |
| Python dependency audit | `pip-audit` (CI job `security/python-audit`) | 0 known vulnerabilities after upgrading Pillow 12.3.0 → 13.0.0 (CVE batch incl. GHSA-78g4-xqwv-q3g8) and dnspython 2.9.1 → 2.9.2 (CVE-2026-128089) |
| Rust dependency audit | `cargo audit` (CI job `security/cargo-audit`) | Runs in CI. Not run on the review machine (tool install not permitted there) |
| Secret scanning | gitleaks over the full git history (CI job `security/secrets`, `.gitleaks.toml`) | Manual scan of history for Stellar seeds, AWS keys, private keys and tokens: only the published SEP-53 test vector in unit tests. Throwaway testnet keys live in `var/testnet/` (gitignored, never committed) |

## 2. DEVELOPMENT_PLAN §8 risks, re-verified

| Risk | Control | Evidence |
|---|---|---|
| Backend compromise used to steal escrowed funds | The backend holds no fund-moving key. The contract pays only the stored customer or professional; the operator key only co-signs `fund` and pays fees | Contract tests; `STELLAR_ESCROW_DESIGN` §3 |
| DB tampering marks a booking paid or released | Financial transitions only from the reconciler after RPC confirmation plus a `get_escrow` cross-check | `test_database_tampering_cannot_release_funds` |
| User signs a different transaction than prepared | Signed-envelope hash must equal the prepared hash; network passphrase checked | `test_tampered_or_foreign_signatures_are_rejected` |
| Duplicate funding / double processing | Unique escrow per booking, on-chain `AlreadyExists`, unique tx hash, row locks, idempotency keys | `test_parallel_funding_submissions_produce_one_effect`; testnet journey (duplicate funding refused) |
| Arbiter key compromise | Arbiter can act only on `Disputed` escrows; human-held Freighter wallet; the admin's wallet must equal the on-chain arbiter | `test_resolution_requires_the_arbiter_wallet_and_a_locked_dispute`; testnet "resolve undisputed" refusal. See F1 |
| IDOR | Service-level participation checks; 404 when not visible; authorization matrix | §1 |
| Refresh token theft via XSS | HttpOnly, `Secure`, `SameSite=Strict`, path-scoped cookie; rotation with reuse detection; 15-minute in-memory access token | `test_sessions.py`, `test_csrf_cors_cookies.py`. See F4 |
| CSRF on cookie routes | Origin allowlist + `X-CSRF-Protection` header + `SameSite=Strict` | `test_cookie_routes_reject_csrf` |
| Cross-site WebSocket hijacking | Single-use 30 s tickets, WS `Origin` check, periodic session re-validation | `test_realtime.py` |
| Terms altered after acceptance | No edit endpoint; DB triggers and `CHECK`s on agreement and escrow-terms hashes; on-chain `terms_hash` cross-check; admin alert on mismatch | `test_terms_tampered_on_chain_is_flagged_not_funded`; `test_notification_for_event[escrow failed verification]` |
| Duplicate reconciliation across instances | Unique event key, row locks, cursor in the same transaction | `test_same_event_from_both_sources_and_concurrent_reconcilers_apply_once`, `test_crash_between_apply_steps_recovers` |
| Fiat/token unit confusion | Separate columns and types; one conversion function | `test_fx_conversion_boundary_vectors` |
| Upload abuse | Byte-level type detection, per-purpose caps, an outer body limit, image re-encode, private storage | Upload tests; `test_uploads_get_a_larger_outer_limit` |
| Location privacy | Approximate coordinates; address revealed only after funding | `test_discovery.py`, `test_fund_complete_release_end_to_end` |
| Token leakage via URLs or logs | Query strings never logged; redaction filter (now also Stellar seeds) | Redaction tests |
| Brute force on login or wallet challenge | DB-backed limits and lockout; per-user write backstop | Auth and wallet tests |
| Funds locked by an unresponsive party | Deadlines on every undisputed state; permissionless `finalize_expired`; keeper; 24 h deadline warnings | Keeper tests (fake chain and testnet); `test_notification_for_event[refund deadline approaching]` |
| Disputed funds stuck if the arbiter is unavailable | Escalation ladder with SLA reminders and admin notifications; admin can rotate the arbiter | `test_disputed_escrows_never_time_out_and_escalate`; SLA reminder tests. See F2 |
| Asset issuer freeze (USDC) | Documented trust assumption | `STELLAR_ESCROW_DESIGN` §3. See F5 |
| Testnet reset | Scripted redeploy, network epoch | `docs/DEPLOYMENT.md` §7 |
| Freighter SEP-53 mismatch | Verified against a real Freighter fixture | `tests/unit/test_stellar.py` |

## 3. OWASP API Security Top 10 (2023)

| # | Category | Status | Controls and evidence |
|---|---|---|---|
| API1 | Broken Object Level Authorization | Mitigated | Every read and write loads the object through a participation check and answers 404 when it is not visible. Notifications filter on `user_id` in SQL, including `POST /notifications/read` (foreign ids are ignored). Matrix + per-module tests |
| API2 | Broken Authentication | Mitigated | Argon2id; lockout and per-IP limits; short JWTs with session-family revocation; refresh rotation with reuse detection; suspension revokes all sessions; WS tickets single-use |
| API3 | Broken Object Property Level Authorization | Mitigated | Request models reject unknown fields (`extra="forbid"`), so mass assignment fails with 422. Response models are explicit; admin models carry no password hash, token hash, secret, `escrow_key` or XDR (`test_admin_console.py::_assert_no_sensitive_fields`) |
| API4 | Unrestricted Resource Consumption | Mitigated | 1 MiB body limit (11 MiB on `/uploads`, then per-purpose caps), counted for chunked bodies too; pagination max 100; per-user write backstop (120/min) plus route limits; decompression-bomb guard; WS frame limits. See F3 |
| API5 | Broken Function Level Authorization | Mitigated | `AdminDep` on every `/admin` route; role checks in services (e.g. only professionals quote); matrix proves it for every admin-tagged route |
| API6 | Unrestricted Access to Sensitive Business Flows | Mitigated | Money flows need a wallet signature by the right party and are verified on-chain; one active booking per conversation; one review per booking within 30 days; one open dispute per booking; one report per reporter and target |
| API7 | Server-Side Request Forgery | Not applicable / mitigated | The API makes outbound calls only to configured Stellar RPC/Horizon, SMTP and S3 endpoints. No user-supplied URL is fetched |
| API8 | Security Misconfiguration | Mitigated | Production refuses insecure settings (§DEPLOYMENT 3); HSTS, CSP, `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`; no `server` header; CORS allowlist without wildcards; docs hidden in production; non-root, read-only-capable image |
| API9 | Improper Inventory Management | Mitigated | One versioned prefix (`/api/v1`); CI fails if `openapi.json` is stale; the matrix test enumerates the live schema, so a new route without a policy fails CI |
| API10 | Unsafe Consumption of APIs | Mitigated | Stellar responses are parsed defensively; RPC errors map to 503 with no state change; on-chain state is cross-checked against stored terms before any transition; Horizon/RPC data never reaches SQL or HTML unescaped |

## 4. Open findings (not fixed in this issue)

| ID | Severity (testnet MVP) | Finding | Plan |
|---|---|---|---|
| F1 | Medium (High before real value) | The arbiter is a single human-held key (D11). Its loss blocks disputed escrows; its theft lets an attacker settle disputed escrows (only those) arbitrarily | Accepted for testnet. 2-of-3 multisig arbiter before any real-value deployment (STELLAR_ESCROW_DESIGN §4.5) |
| F2 | Medium (High before real value) | No long-stop settlement for disputed funds (policy P1 pending, D16a rejected). If no arbiter acts, disputed funds stay locked; escalations and admin notifications are the only mitigation | Awaiting P1 approval. A fallback can only apply to escrows funded on a later contract deployment (the contract is immutable) |
| F3 | Low | Rate limits are enforced in PostgreSQL per user and per IP; there is no edge (CDN/WAF) limiting, so a large distributed flood still reaches the app and the database | Put the API behind the platform's proxy/WAF with connection and request-rate limits (DEPLOYMENT §1) |
| F4 | Medium (frontend) | An XSS in the frontend could act as the user while the page is open (the access token is in page memory). The refresh cookie itself is not readable by scripts | Frontend follow-up: a strict Content-Security-Policy on the Next.js app and no `dangerouslySetInnerHTML` on user content |
| F5 | Low | Circle USDC is `AUTH_REVOCABLE`; the issuer can freeze escrowed balances | Inherent to regulated stablecoins; documented trust assumption |
| F6 | Low | `cargo audit` and gitleaks have not been run on the review machine; they run only in CI | Confirm both CI jobs are green on the Issue 8 PR |
| F7 | Informational | Production domains (D4a) are not agreed, so the same-site cookie topology has not been verified on real domains | DEPLOYMENT §2 verification step on first deploy |

## 5. Changes made by this review

- Request body size limit middleware (declared and streamed bodies) with a larger bound for uploads.
- `Content-Security-Policy` (API responses), `Permissions-Policy`, HSTS in production, no `server` header.
- Swagger UI / OpenAPI hidden in production unless `EXPOSE_API_DOCS=true`.
- Production validator: example values in `ESCROW_ID_SECRET`, `SMTP_PASSWORD`, `S3_SECRET_ACCESS_KEY`;
  `FRONTEND_BASE_URL` must be https and in the CSRF origin list; `LOG_LEVEL=DEBUG` refused.
- Log redaction of Stellar secret seeds and any `*secret*` JSON key.
- Per-user write rate limit backstop on every authenticated POST/PATCH/PUT/DELETE.
- Dependency upgrades: Pillow 13.0.0, dnspython 2.9.2 (uv `exclude-newer` moved to 2026-11-05, still two weeks).
- CI: `pip-audit`, `cargo audit`, gitleaks (full history), weekly schedule.
- Docker image defaults to `ENV=production` and documents read-only root filesystem use.
- Admin alert notification when an on-chain escrow fails terms verification.
