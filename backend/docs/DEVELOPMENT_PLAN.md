# UniFix Backend — Development Plan

Status: **Planning baseline, revision 2 (2026-11-17). Architecture and issue breakdown approved for continued planning. No issue has started; Issue #1 awaits explicit approval.**

## Revision log

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-11-17 | Initial architecture, contract, DB design, escrow design, eight issues |
| 2 | 2026-11-17 | Per review: (1) HttpOnly refresh cookie with CSRF/CORS design; (2) single-use WebSocket tickets; (3) snake_case API, frontend changes documented, no dual-case support; (4) deadline-based cancellation, refund, dispute and arbitration policy so no permanent locks, with on-chain completion and concessions; (5) separate fiat/token integer units and a verified testnet USDC configuration; (6) quote immutability triggers and an RFC 8785 agreement → escrow-terms → on-chain hash chain; (7) exactly-once reconciler across restarts and instances; (8) frontend change list F1–F25 with file:line references |

## 1. The eight issues

| # | Title | Batch | Branch | Deliverable |
|---|---|---|---|---|
| 1 | Project Foundation, Authentication and User Management | 1 | `feat/issue-1-foundation-auth` | Working authenticated API |
| 2 | Professional Profiles, Campus Services and Discovery | 1 | `feat/issue-2-professional-discovery` | Searchable professional marketplace |
| 3 | Service Requests, Quotations and Booking Management | 1 | `feat/issue-3-requests-quotes-bookings` | Complete request-to-booking workflow |
| 4 | Real-Time Chat, Attachments and Call Signaling | 1 | `feat/issue-4-realtime-communication` | Working real-time customer–professional communication |
| 5 | Stellar Wallets and Soroban Escrow Contracts | 2 | `feat/issue-5-stellar-escrow` | Secure testnet escrow contracts |
| 6 | Payment Integration, Job Completion and Blockchain Reconciliation | 2 | `feat/issue-6-payment-completion` | End-to-end protected-payment workflow |
| 7 | Disputes, Refunds and Verified Reviews | 2 | `feat/issue-7-disputes-reviews` | Safe dispute handling, verified reputation |
| 8 | Notifications, Administration, Security Hardening and End-to-End Testing | 2 | `feat/issue-8-admin-hardening` | Deployable, verified backend |

GitHub issue URLs are recorded in §7 once the issues are created.

## 2. Ownership rules (no duplicated responsibility)

Three cross-cutting concerns are placed so later issues can depend on them:

| Concern | Built in | Used by | Why there |
|---|---|---|---|
| `audit_logs` table + `audit.record()` | **Issue 1** | all | Financial and admin actions in Issues 3–7 must be audited as they are written, not retrofitted |
| `files` + `POST /uploads` + storage backends | **Issue 2** | 3, 4, 6, 7 | Portfolio is the first consumer; Issue 4 adds the access policies for chat attachments |
| `idempotency_keys` + `Idempotency-Key` dependency | **Issue 3** | 3, 6, 7 | Quote acceptance is the first operation where a retry could cause a duplicate |
| Notifications (table, service, endpoints, triggers) | **Issue 8** | — | Kept in Issue 8 per the brief. Issue 8 adds `notify()` calls at the event points already built in Issues 3–7 |

**Admin rule:** each domain issue owns the admin actions inside its own workflow:

- Issue 1: suspend or reactivate a user.
- Issue 2: approve or reject a verification; manage categories and campuses.
- Issue 7: dispute queue and resolution; review moderation.

Issue 8 owns the cross-cutting admin views (users, bookings, escrows, requests, reports, audit log, ops status).

**Boundary notes against the brief:**

- *Professional verification controls* (brief §K) are in Issue 2, because a verified badge is unreachable in Batch 1 without them.
- *Booking-linked conversations* (brief §D) are completed in Issue 3, because bookings do not exist until then. Issue 4 provides the conversation; Issue 3 links bookings to it and posts booking/quote system messages.
- *Refunds* are split. The professional-initiated (non-dispute) full refund is in Issue 6, because it is the same prepare → sign → reconcile path as release. Dispute refunds and splits stay in Issue 7.

## 3. Dependencies and implementation order

```
Issue 1 ──► Issue 2 ──► Issue 4 ──► Issue 3 ──► Issue 6 ──► Issue 7 ──► Issue 8
   │                                    ▲
   └──────────────► Issue 5 ────────────┘ (5 needs only 1; 6 needs 3 + 5)
```

| Issue | Hard dependencies | Why |
|---|---|---|
| 1 | — | |
| 2 | 1 | users, roles, audit |
| 4 | 1, 2 | conversations reference professional profiles; attachments use uploads |
| 3 | 1, 2, 4 | quotes live inside conversations and post quote messages; bookings link to conversations |
| 5 | 1 | wallets belong to users; the contract is self-contained Rust |
| 6 | 3, 5 | escrow per booking; wallets + contract |
| 7 | 6 | disputes lock escrows; reviews need settled bookings |
| 8 | 1–7 | notifications at every event; admin views over everything; full E2E |

**Recommended order: 1 → 2 → 4 → 3 (Batch 1), then 5 → 6 → 7 → 8 (Batch 2).** Building Issue 4 before Issue 3 removes an inverted dependency: frontend quotes are created inside a conversation (`QuoteInput.conversationId`). Issue numbers stay as the brief defines them. Only the build order changes (decision D1).

Issue 5's contract work depends only on Issue 1. It can start while Batch 1 is in review, if you want to overlap.

## 4. Branch and PR strategy

- Every branch starts from `main`, or from the previous unmerged issue branch (stacked) when its dependency has not merged yet.
- **Preferred:** each issue PR is merged before the next issue starts. No stacking, simplest review.
- **If stacking is needed:** open the PR with the previous issue's branch as its base, so the diff shows only this issue. After the parent merges, merge `main` into the child branch (**no rebase, no force-push**) and retarget the PR to `main`. Merge stacked PRs with *merge commits*, not squash, so child branches stay compatible.
- I never open or merge PRs, deploy, or push without your authorization. After an authorized push I give you the compare URL (`https://github.com/ladicodes/UniFix/compare/main...<branch>?expand=1`) plus a prepared PR title and description, with the real test output.
- Commits: Conventional Commits scoped to `backend` (e.g. `feat(backend): …`). Nothing under `frontend/` is touched. CI lives in `.github/workflows/backend.yml` with `paths: ["backend/**", ".github/workflows/backend.yml"]`.

**Definition of done, for every issue:**

1. Every acceptance criterion in the issue is met.
2. `ruff`, `mypy`, the import-linter check and `pytest` (against PostgreSQL 16) pass locally **and** in CI. `cargo test` passes too, from Issue 5.
3. `alembic upgrade head` / `downgrade` round-trip passes.
4. API_CONTRACT.md is updated for every endpoint added or changed, and the OpenAPI output matches it.
5. No TODOs or placeholder endpoints. Anything deferred is listed in the PR as **not done**.
6. A security self-review against the issue's security section is recorded in the PR.

## 5. Decisions requiring approval

Each decision has a recommendation. If you approve as-is, I proceed with the recommendation.

Settled in the revision-2 review (no longer open):

| ID | Decision | Outcome |
|---|---|---|
| D2 | JSON casing | **snake_case** for all fields and query params; enum values `UPPER_SNAKE_CASE`; no dual-case support; frontend changes F19–F20 |
| D4 | Refresh-token transport | **HttpOnly `SameSite=Strict` cookie**, path-scoped to `/api/v1/auth`; access token in memory; CSRF = Origin allowlist + `X-CSRF-Protection` header + SameSite |
| D9 | WebSocket auth | **Single-use 30-second tickets** from `POST /ws/tickets`; no tokens in WS URLs |

Open (each has a recommendation; approving the plan as-is accepts it):

| ID | Decision | Recommendation | Needed by |
|---|---|---|---|
| D1 | Build order | 1 → 2 → 4 → 3 → 5 → 6 → 7 → 8 | Batch 1 |
| D3 | List response shape | bare arrays + `X-Total-Count`/`X-Next-Offset` headers rather than `{items,total}` envelopes. Since F19 already changes every type, switching to envelopes now costs little; your call | Issue 1 |
| D4a | Production domain topology | `app.<domain>` + `api.<domain>` (same-site), or a Next.js rewrite proxy. Required for the cookie. Victor's hosting must fit this | Issue 1 (documented), Issue 8 (deployed) |
| D4b | Enum value casing | `UPPER_SNAKE_CASE` for all enum values (F20). Alternative: keep the frontend's lowercase values | Issue 1 |
| D5 | Email delivery | generic SMTP sender; you choose the provider (e.g. Resend, Brevo, Postmark SMTP). Dev logs links to console. Without a provider, verification and reset work in dev only | Issue 1 |
| D6 | Email verification gate | registration works unverified; **funding and quoting require a verified email** | Issue 1 / 3 |
| D7 | Phone verification | no SMS provider in MVP; `PHONE` verification is reviewed manually by an admin | Issue 2 |
| D8 | Prod object storage | S3-compatible (Cloudflare R2 recommended for cost); local disk in dev and test | Issue 2 (interface) / Issue 8 (prod) |
| D10 | Review eligibility | `COMPLETED` and `RESOLVED` (dispute split) bookings; not `REFUNDED`/`CANCELLED`; 30-day window | Issue 7 |
| D11 | Arbiter custody | human-held Freighter wallet (multisig before mainnet); the backend holds **no** key that can move funds | Issue 5 |
| D12 | Operator co-signature on `fund` | yes: blocks mislabelled or squatted escrows; the operator key cannot move funds | Issue 5 |
| D13 | Escrow asset | Circle testnet USDC (`GBBD47IF…LFLA5`, SAC `CBIELTK6…DAMA`, verified 2026-11-17) for demos; a UniFix-issued test asset for automated E2E. Note: the issuer has `AUTH_REVOCABLE` set | Issue 5 |
| D14 | FX rate | fixed configured USDC/NGN rate on testnet, locked per escrow, `source = CONFIGURED_TESTNET`; the rate value itself is yours to set | Issue 6 |
| D15 | Platform fee | none in MVP | Issue 5 |
| D16a | Dispute-timeout fallback | **refund to customer** if the arbiter has not resolved within `arbitration_window`. Alternative: 50/50 split | Issue 5 |
| D16b | Keeper auto-finalization | the backend keeper triggers all matured timeouts (auto-release after review, refund after `refund_after`, dispute fallback) 15 min after maturity, with 24 h warnings | Issue 6 |
| D16c | Default windows | `SERVICE_GRACE` 3 days after the agreed completion date; review window 72 h; arbitration window 30 days | Issue 5 |
| D17 | Settlement during a dispute | **concessions only**: the customer may release to the professional, the professional may refund the customer; only the arbiter can split. *Changed from rev 1 ("not allowed"), to reduce dependence on the arbiter* | Issue 5 |
| D21 | Professional cancellation after funding | allowed via a full refund; counted in a cancellation metric shown to admins (not public in MVP) | Issue 6 |
| D18 | Deployment target | Render, Railway or Fly.io + managed PostgreSQL 16; single API instance | Issue 8 |
| D19 | Error tracking | none by default; optional Sentry | Issue 8 |
| D20 | CI location | `.github/workflows/backend.yml` at repo root (the only file outside `backend/`) | Issue 1 |

## 6. Readiness

| Item | Status | Action |
|---|---|---|
| Repo `ladicodes/UniFix` | ✅ Exists, authenticated as `ladicodes` (scopes `repo`, `workflow`) | — |
| Python 3.12 + uv | ✅ 3.12.10, uv 0.13.7 | — |
| PostgreSQL 16 | ⚠️ Installed (16.15) but **not running** | `brew services start postgresql@16` at Issue 1 start (I will ask first) |
| Docker | ❌ Not installed | Dockerfile and compose are written in Issue 1 but **cannot be verified locally**. They are verified by a CI build job, or after you install Docker/OrbStack |
| Rust | ✅ rustc 1.98.1 | — |
| `wasm32v1-none` target | ❌ Missing | `rustup target add wasm32v1-none` (Issue 5) |
| Stellar CLI | ❌ Missing | `brew install stellar-cli` (Issue 5) |
| Testnet access | ✅ Soroban RPC and Horizon reachable (2026-11-17); Friendbot not yet exercised | Friendbot checked at Issue 5 start |
| Handi PRD (the "section 10" API spec the frontend references) | ❌ Not in the workspace | Optional. The plan uses the frontend's actual code as the contract |
| Testnet asset | ✅ Circle USDC verified on live testnet; RPC healthy (retention 120,960 ledgers ≈ 7 days) | Re-verified by the startup check (Issue 5) |

**Batch 1 (Issues 1–4) is ready to start** once Issue #1 is approved. The open decisions D1, D3, D4a, D4b and D5–D7 proceed on their recommendations unless you say otherwise. PostgreSQL will be started at the beginning of Issue 1. No existing database is reset or deleted.

## 7. GitHub issues

| # | URL |
|---|---|
| 1 | https://github.com/ladicodes/UniFix/issues/1 |
| 2 | https://github.com/ladicodes/UniFix/issues/2 |
| 3 | https://github.com/ladicodes/UniFix/issues/3 |
| 4 | https://github.com/ladicodes/UniFix/issues/4 |
| 5 | https://github.com/ladicodes/UniFix/issues/5 |
| 6 | https://github.com/ladicodes/UniFix/issues/6 |
| 7 | https://github.com/ladicodes/UniFix/issues/7 |
| 8 | https://github.com/ladicodes/UniFix/issues/8 |

## 8. Top security risks

| Risk | Mitigation (where) |
|---|---|
| Backend compromise used to steal escrowed funds | Backend holds no fund-moving key; contract enforces parties (Issue 5) |
| DB tampering marks a booking paid or released | Financial transitions only come from the reconciler, after RPC confirmation plus a `get_escrow` cross-check (Issue 6) |
| User signs a transaction other than the one prepared | Signed-envelope hash must equal the prepared hash (Issue 6) |
| Duplicate funding or double processing | Unique escrow per booking, on-chain `AlreadyExists`, unique tx hash, row locks, idempotency keys (Issues 3, 5, 6) |
| Arbiter key compromise | Can only touch disputed escrows; human-held; multisig before mainnet (Issue 5) |
| IDOR on bookings, chats, files | Service-level participation checks; 404 on not-visible; authorization matrix test (Issues 1–8) |
| Refresh token theft via XSS | HttpOnly cookie (not readable by JS), path-scoped, rotation with reuse detection; access token in memory only, 15 min (Issue 1) |
| CSRF against cookie routes | Origin allowlist + `X-CSRF-Protection` header (forces preflight) + `SameSite=Strict` (Issue 1) |
| Cross-site WebSocket hijacking / token leakage | Single-use 30 s tickets + WS `Origin` check + periodic session re-validation (Issue 4) |
| Quote or terms altered after acceptance | No edit endpoint; DB triggers; agreement and escrow-terms hashes with DB `CHECK`s; on-chain `terms_hash` cross-checked by the reconciler (Issues 3, 6) |
| Duplicate reconciliation across instances or restarts | Unique event key, row locks, cursor in the same transaction, idempotent apply; advisory-lock leader for efficiency only (Issue 6) |
| Fiat and token unit confusion | Separate columns and types, explicit asset identity, one conversion function, boundary tests (Issue 6) |
| Upload abuse (malware, EXIF location leaks, oversized files) | Type detection from bytes, size caps, image re-encode, private-by-default storage (Issue 2) |
| Location privacy for students | Approximate coordinates only; address revealed after funding (Issues 2, 3) |
| WS token leakage via URLs | Query-string log redaction; short-lived tokens (Issue 4) |
| Brute force on login or wallet challenge | DB-backed rate limits and lockout (Issues 1, 5) |
| Funds locked by an unresponsive party or arbiter | On-chain deadlines for every non-terminal state; permissionless `finalize_expired`; keeper (Issues 5, 6); D16a–c |
| Asset issuer freeze (USDC `AUTH_REVOCABLE`) | Inherent to regulated stablecoins; documented trust assumption (STELLAR_ESCROW_DESIGN §3) |
| Testnet reset wipes contract state | Scripted redeploy; network epoch on escrow rows (Issue 5) |
| Freighter SEP-53 encoding mismatch | Verify against a real Freighter fixture before closing Issue 5 |
