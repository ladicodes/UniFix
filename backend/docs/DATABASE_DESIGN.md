# UniFix — Database Design

Status: **Planning baseline (2026-11-17). Not implemented.** PostgreSQL 16, SQLAlchemy 2.x, Alembic.

## 1. Conventions

- Primary keys are `uuid` (generated in Python, `uuid4`). They are exposed to clients as strings.
- Timestamps are `timestamptz`, stored in UTC. Mutable tables have `created_at` and `updated_at`.
- Money is `bigint` **minor units** (kobo/pesewas) with a `currency` column (`NGN`, `GHS`). On-chain token amounts are `numeric(39,0)` base units, which fits `i128`.
- Enums are PostgreSQL `text` columns with `CHECK` constraints, generated from Python `StrEnum`s. Adding a value is then a single migration with no type rewrite.
- Every foreign key has an explicit `ON DELETE` rule. The default is `RESTRICT`. Users are never hard-deleted (deactivated instead), so financial history stays intact.
- The constraint naming convention is set on `MetaData` (`pk_`, `fk_`, `uq_`, `ix_`, `ck_`), so Alembic autogenerate produces stable names.
- Free-text search uses a generated `tsvector` column with a GIN index. No extension is needed beyond `citext` (and `pg_trgm` if fuzzy name search proves necessary).
- Tables marked **append-only** have a trigger that raises on `UPDATE`/`DELETE`.

Column lists below are the planned shape. Final names are fixed in each issue's migration.

## 2. Entity map

```
users ─┬─ auth_sessions
       ├─ user_tokens (email verify / password reset)
       ├─ professional_profiles ─┬─ professional_categories ── service_categories (self-ref parent)
       │                         ├─ professional_campuses ──── campuses
       │                         ├─ professional_verifications ── files
       │                         └─ portfolio_items ── files
       ├─ wallets ── wallet_challenges
       └─ notifications
campuses ── users.campus_id

service_requests ─┬─ service_request_media ── files
                  └─ conversations ─┬─ conversation_members
                                    ├─ messages ── files
                                    ├─ call_sessions
                                    └─ quotes ── agreements ── bookings ─┬─ booking_events
                                                                         ├─ escrows ─┬─ chain_transactions
                                                                         │           └─ ledger_entries
                                                                         ├─ completion_submissions ── completion_files ── files
                                                                         ├─ disputes ── dispute_evidence ── files
                                                                         ├─ reviews ── (reports)
                                                                         └─ receipts
reports (target_type: MESSAGE | CONVERSATION | USER | REVIEW)
audit_logs (append-only)   idempotency_keys   chain_sync_state   rate_limit_events
```

## 3. Tables by issue

### Issue 1 — Foundation and auth

**users**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| email | citext NOT NULL | `UNIQUE` |
| email_verified_at | timestamptz NULL | |
| password_hash | text NOT NULL | Argon2id |
| full_name | text NOT NULL | 2–120 chars |
| phone | text NULL | E.164; `UNIQUE` where not null |
| role | text NOT NULL | `customer` \| `professional` \| `admin` |
| status | text NOT NULL | `ACTIVE` \| `SUSPENDED` \| `DEACTIVATED`, default `ACTIVE` |
| city | text NULL | |
| country | text NOT NULL | `NG` \| `GH` |
| campus_id | uuid NULL | FK campuses — **column added in Issue 2** |
| avatar_file_id | uuid NULL | FK files — **added in Issue 2** |
| failed_login_count | int NOT NULL default 0 | |
| locked_until | timestamptz NULL | |
| last_login_at | timestamptz NULL | |

Indexes: `(role, status)`.

**auth_sessions**: one row per refresh token in a rotation chain.
`id, user_id FK CASCADE, family_id uuid, refresh_token_hash char(64) UNIQUE, parent_id FK self NULL, created_at, expires_at, used_at NULL, revoked_at NULL, revoked_reason text NULL, user_agent text, ip inet`.
Indexes: `(user_id) WHERE revoked_at IS NULL`, `(family_id)`.
The access JWT `sid` refers to the **family**. Revoking a family sets `revoked_at` on all its rows.

**user_tokens**
`id, user_id FK CASCADE, purpose (VERIFY_EMAIL|RESET_PASSWORD), token_hash char(64) UNIQUE, expires_at, used_at NULL, created_at`.

**audit_logs** (append-only)
`id, occurred_at, actor_type (USER|ADMIN|SYSTEM|CHAIN), actor_user_id NULL FK SET NULL, action text, entity_type text, entity_id uuid NULL, request_id text NULL, ip inet NULL, data jsonb NOT NULL default '{}'`.
Indexes: `(entity_type, entity_id, occurred_at)`, `(actor_user_id, occurred_at)`, `(action, occurred_at)`.
`data` never contains secrets, tokens or full XDR.

**rate_limit_events**
`id, bucket text, key text, at timestamptz`. Index `(bucket, key, at)`. Rows older than the largest window are pruned.

### Issue 2 — Campuses, categories, professionals, uploads

**campuses**
`id, slug UNIQUE, name, short_name, city, state, country, latitude numeric(9,6), longitude numeric(9,6), is_active bool`.

**service_categories**
`id, slug UNIQUE, name, parent_id FK self NULL, description, is_active, sort_order`.
The seed list is university-first: phone-repair, laptop-repair, electronics-repair, electrician, plumber, ac-technician, laundry, cleaner, tailor, carpenter, painter, generator, plus the frontend's existing slugs.

**files**

| Column | Notes |
|---|---|
| id, owner_user_id FK RESTRICT | |
| purpose | `AVATAR`, `PORTFOLIO`, `VERIFICATION_DOCUMENT`, `REQUEST_MEDIA`, `MESSAGE_ATTACHMENT`, `COMPLETION_EVIDENCE`, `DISPUTE_EVIDENCE` |
| visibility | `PUBLIC` \| `PRIVATE` (derived from purpose, stored for queries) |
| storage_key | `UNIQUE` |
| content_type, size_bytes, sha256 char(64), original_name, width, height | |
| created_at, deleted_at NULL | |

Index: `(owner_user_id, purpose)`.

**professional_profiles**

| Column | Notes |
|---|---|
| id, user_id FK CASCADE `UNIQUE` | |
| primary_category_id FK | |
| headline, bio, city, area, country | |
| latitude, longitude NULL | Approximate (rounded to ~1 km); never exact |
| years_experience smallint `CHECK 0–60` | |
| availability | `now` \| `today` \| `this-week` \| `unavailable` |
| starting_price_minor bigint `CHECK >= 0`, currency | |
| skills text[], languages text[], coverage text[] | |
| is_listed bool | Hidden from discovery when false or when the user is not `ACTIVE` |
| verification_status | `NOT_SUBMITTED` \| `PENDING` \| `VERIFIED` \| `REJECTED` (overall, derived) |
| rating_avg numeric(3,2), rating_count int, rating_quality … rating_value numeric(3,2) | Maintained by Issue 7 |
| completed_jobs int | Maintained by Issue 6 |
| response_minutes int NULL | Median first response, maintained by Issue 4 |
| search_vector tsvector GENERATED | From headline, bio, skills, area |

Indexes: GIN `search_vector`; `(primary_category_id, is_listed)`; `(rating_avg DESC)`; `(completed_jobs DESC)`.

**professional_categories** `(professional_id, category_id)` PK.
**professional_campuses** `(professional_id, campus_id)` PK.

**professional_verifications**
`id, professional_id FK CASCADE, type (IDENTITY|TRADE|PHONE), status (PENDING|VERIFIED|REJECTED), file_ids uuid[], note, submitted_at, reviewed_by FK users NULL, reviewed_at, rejection_reason`.
`UNIQUE (professional_id, type)`. History lives in audit_logs.

**portfolio_items**
`id, professional_id FK CASCADE, title, caption, category_id FK NULL, image_file_id FK files, sort_order, created_at`. At most 30 per professional (service rule).

### Issue 4 — Conversations and messaging

**conversations**
`id, customer_id FK, professional_id FK (professional_profiles), service_request_id FK NULL (added in Issue 3), last_message_at, last_message_preview, created_at`.
Constraints:

- `UNIQUE (customer_id, professional_id) WHERE service_request_id IS NULL`: one direct thread per pair.
- `UNIQUE (service_request_id, professional_id) WHERE service_request_id IS NOT NULL`.
- `CHECK` that the customer user is not the professional's user (enforced in the service).

**conversation_members**
`(conversation_id, user_id)` PK, `role (customer|professional)`, `last_read_message_id NULL`, `last_read_at NULL`, `muted bool`.
Used for access control, unread counts and read receipts.

**messages**
`id, conversation_id FK CASCADE, sender_id FK NULL (NULL = system), kind (text|image|quote|system), body text (≤ 4000), quote_id FK NULL (added in Issue 3), attachment_file_id FK NULL, client_message_id uuid NULL, created_at`.
`UNIQUE (sender_id, client_message_id)` dedupes client retries. Index `(conversation_id, created_at DESC, id DESC)`.

**call_sessions**
`id, conversation_id FK, initiator_id FK, status (RINGING|ACTIVE|ENDED|MISSED|DECLINED), created_at, answered_at, ended_at, end_reason`.
`UNIQUE (conversation_id) WHERE status IN ('RINGING','ACTIVE')`.

**reports**
`id, reporter_id FK, target_type (MESSAGE|CONVERSATION|USER|REVIEW), target_id uuid, reason, details, status (OPEN|DISMISSED|ACTIONED), resolved_by NULL, resolved_at, created_at`.
`UNIQUE (reporter_id, target_type, target_id)`. Reused by Issue 7 for reviews.

### Issue 3 — Requests, quotes, agreements, bookings

**service_requests**
`id, customer_id FK, category_id FK, campus_id FK NULL, title, description, item, location_text, latitude NULL, longitude NULL (private), preferred_start, preferred_end, status (OPEN|BOOKED|CANCELLED|EXPIRED), expires_at, created_at, updated_at`.
Index `(status, category_id, campus_id, created_at DESC)`.

**service_request_media** `(request_id, file_id)` PK, `sort_order`.

**quotes**

| Column | Notes |
|---|---|
| id, conversation_id FK, service_request_id FK NULL, professional_id FK, customer_id FK | |
| version int | `UNIQUE (conversation_id, version)` |
| status | `PENDING` \| `ACCEPTED` \| `REJECTED` \| `SUPERSEDED` \| `WITHDRAWN` |
| title, description | |
| labour_minor, materials_minor, total_minor bigint | `CHECK total = labour + materials`, `CHECK labour >= 0 AND materials >= 0 AND total > 0` |
| currency, completion_date date, payment_terms, service_method (`customer_to_pro`\|`pro_to_customer`\|`either`\|`remote`), milestones jsonb | |
| valid_until, created_at, responded_at | |

Constraint: `UNIQUE (conversation_id) WHERE status = 'PENDING'`, so a conversation has at most one live quote.

**agreements** (append-only)
`id, quote_id FK UNIQUE, customer_id, professional_id, terms jsonb (canonical, sorted keys), terms_hash char(64) UNIQUE, total_minor, currency, accepted_by FK, accepted_at`.

**bookings**

| Column | Notes |
|---|---|
| id, agreement_id FK UNIQUE, quote_id FK UNIQUE, conversation_id FK, service_request_id FK NULL, customer_id FK, professional_id FK | |
| title, service_address | `service_address` is revealed to the professional only from `FUNDED` onwards |
| amount_minor, currency | Copied from the agreement; `CHECK amount_minor > 0` |
| status | `PENDING_PAYMENT`, `FUNDED`, `IN_PROGRESS`, `COMPLETION_SUBMITTED`, `COMPLETED`, `DISPUTED`, `CANCELLED`, `REFUNDED`, `RESOLVED` |
| version int | Optimistic lock |
| funded_at, started_at, completion_submitted_at, completed_at, cancelled_at, cancelled_by, cancellation_reason | |
| created_at, updated_at | |

Constraints and indexes:

- `UNIQUE (conversation_id) WHERE status IN ('PENDING_PAYMENT','FUNDED','IN_PROGRESS','COMPLETION_SUBMITTED','DISPUTED')`: no duplicate active booking.
- `UNIQUE (service_request_id) WHERE service_request_id IS NOT NULL AND status <> 'CANCELLED'`.
- Indexes `(customer_id, status)`, `(professional_id, status)`.

**booking_events** (append-only): the timeline.
`id, booking_id FK CASCADE, from_status NULL, to_status NULL, label, actor_type (customer|professional|system|chain|admin), actor_user_id NULL, data jsonb, created_at`. Index `(booking_id, created_at)`.

**idempotency_keys**
`id, user_id FK, key text, method, path, request_hash char(64), status (IN_PROGRESS|COMPLETED), response_status int, response_body jsonb, created_at, expires_at`.
`UNIQUE (user_id, key)`.
Behaviour:

- Same key with the same request: replay the stored response.
- Same key with a different request: `409 IDEMPOTENCY_KEY_REUSED`.
- Same key while still in progress: `409 IDEMPOTENCY_IN_PROGRESS`.

### Issue 5 — Wallets

**wallets**
`id, user_id FK, network (testnet), address char(56), verified_at, is_primary bool, created_at, revoked_at NULL`.
Constraints: `UNIQUE (network, address) WHERE revoked_at IS NULL`; `UNIQUE (user_id, network) WHERE is_primary AND revoked_at IS NULL`.

**wallet_challenges**
`id, user_id FK, address, nonce char(32) UNIQUE, message text, expires_at, used_at NULL, created_at`.

### Issue 6 — Escrow, chain transactions, ledger, completion, receipts

**escrows**

| Column | Notes |
|---|---|
| id, booking_id FK `UNIQUE` | |
| network, network_epoch | Epoch handles testnet resets |
| contract_id, escrow_key bytea(32) `UNIQUE` | |
| token_contract_id, asset_code, asset_issuer | |
| amount_units numeric(39,0) `CHECK > 0` | |
| local_amount_minor, local_currency, fx_rate numeric(20,8), fx_rate_source, fx_locked_at | |
| customer_wallet, professional_wallet, agreement_hash char(64) | |
| state | `CREATED`, `FUNDED`, `DISPUTED`, `RELEASED`, `REFUNDED`, `RESOLVED` |
| reconciliation | `AWAITING_SIGNATURE`, `PENDING_CONFIRMATION`, `CONFIRMED`, `FAILED` |
| verification_error text NULL, professional_payout_units, customer_refund_units | |
| last_synced_ledger, last_synced_at, version, created_at, updated_at | |

**chain_transactions**

| Column | Notes |
|---|---|
| id, escrow_id FK, kind | `FUND`, `RELEASE`, `REFUND`, `DISPUTE`, `RESOLVE` |
| tx_hash char(64) `UNIQUE` | |
| source_account, unsigned_envelope_xdr text, valid_until | Unsigned envelope is kept for verification only |
| status | `PREPARED`, `SUBMITTED`, `PENDING`, `CONFIRMED`, `FAILED`, `EXPIRED` |
| ledger, ledger_closed_at, fee_charged, result_code, error | |
| requested_by FK users, attempts, last_checked_at, created_at, confirmed_at | |

Index `(status, last_checked_at)` for the reconciler. `UNIQUE (escrow_id, kind) WHERE status IN ('SUBMITTED','PENDING','CONFIRMED')`.

**ledger_entries** (append-only): written only from confirmed chain data.
`id, booking_id, escrow_id, chain_transaction_id NULL, type (CUSTOMER_FUNDING|PROFESSIONAL_PAYOUT|CUSTOMER_REFUND), amount_units, asset_code, from_address, to_address, tx_hash, ledger, created_at`.
`UNIQUE (tx_hash, type)`.

**chain_sync_state**
`contract_id PK, last_ledger, last_cursor text, updated_at`: the event-scan cursor.

**completion_submissions**
`id, booking_id FK, submitted_by, notes, checklist jsonb, evidence_hash char(64), status (SUBMITTED|APPROVED|DISPUTED), submitted_at, decided_at`.
`UNIQUE (booking_id) WHERE status = 'SUBMITTED'`.
**completion_files** `(submission_id, file_id)` PK.

**receipts**
`id, booking_id FK, escrow_id FK, kind (FUNDING|RELEASE|REFUND|RESOLUTION), number text UNIQUE (UFX-YYYY-NNNNNN), payload jsonb, payload_hash char(64), issued_at`.
`UNIQUE (escrow_id, kind)`.

### Issue 7 — Disputes and reviews

**disputes**
`id, booking_id FK, escrow_id FK, opened_by FK, reason (INCOMPLETE|DAMAGED|NO_SHOW|PRICE_CHANGED|QUALITY|OTHER), details, status (OPEN|UNDER_REVIEW|AWAITING_SETTLEMENT|RESOLVED|CLOSED), outcome NULL (RELEASE|REFUND|SPLIT), split_bps_to_professional int NULL CHECK 0–10000, resolution_note, resolved_by NULL, resolved_at, created_at, updated_at`.
`UNIQUE (booking_id) WHERE status NOT IN ('RESOLVED','CLOSED')`.

**dispute_evidence**
`id, dispute_id FK, submitted_by FK, note, file_id FK NULL, created_at`.

**reviews**
`id, booking_id FK UNIQUE, customer_id, professional_id, overall numeric(2,1), quality, punctuality, communication, professionalism, value smallint CHECK 1–5, comment ≤ 2000, status (PUBLISHED|HIDDEN|REMOVED), response_body NULL, response_at NULL, moderated_by NULL, moderation_reason NULL, created_at, updated_at`.
Index `(professional_id, status, created_at DESC)`.
Aggregates on `professional_profiles` are recomputed in the same transaction whenever a review is created, hidden or restored.

### Issue 8 — Notifications

**notifications**
`id, user_id FK CASCADE, type text, title, body, href, data jsonb, read_at NULL, created_at`.
Index `(user_id, created_at DESC)` and partial `(user_id) WHERE read_at IS NULL`.

## 4. Migration policy

- One Alembic revision chain. Each issue adds its own revisions and never edits an earlier issue's revisions after merge.
- Every revision must pass `upgrade` → `downgrade` → `upgrade` in CI.
- Seed data (categories, campuses) lives in an idempotent `app.cli seed` command, not in migrations. Lookup values that code depends on are the exception.
- Append-only triggers and partial unique indexes are written by hand in the migrations. Autogenerate does not produce them.
