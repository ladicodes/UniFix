# UniFix API Contract (for the frontend)

Audience: Victor (frontend). You should not need to read backend code to integrate.
Status: **Planned contract, 2026-11-17. No endpoint below exists yet.** Each section names the issue that delivers it. Once an issue merges, the live OpenAPI schema at `/api/v1/openapi.json` (Swagger UI at `/api/v1/docs`) is authoritative for that issue's endpoints. This document is updated in the same PR.

Section 13 lists every change from what `frontend/src/lib/api/live.ts` does today.

---

## 1. Base URL, versioning, CORS

| | Local | Production |
|---|---|---|
| REST base | `http://localhost:8000/api/v1` | TBD |
| WebSocket base | `ws://localhost:8000/api/v1` | `wss://…/api/v1` |

Set `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`. Every path below is relative to that base, so the existing `live.ts` paths (`/auth/login`, …) work unchanged.

CORS allows the origins listed in `CORS_ORIGINS` (default `http://localhost:3000`), with methods `GET, POST, PATCH, PUT, DELETE`. Allowed headers: `Authorization, Content-Type, Idempotency-Key, X-Request-ID`. Exposed headers: `X-Total-Count, X-Next-Offset, X-Request-ID, Retry-After`. Credentials are not used, because tokens go in the `Authorization` header.

## 2. Conventions

- **Casing.** Response JSON is camelCase. Request JSON may be camelCase *or* snake_case; both are accepted for every field.
- **IDs** are UUID strings. **Timestamps** are ISO-8601 UTC (`2026-11-17T10:30:00Z`). **Dates** are `YYYY-MM-DD`.
- **Money:**
  - `labour`, `materials`, `total` and `startingPrice` are numbers in **major units** of `currency` (e.g. `35000` = ₦35,000), with at most 2 decimals.
  - Escrow `amount` is the token amount as a number. `amountUnits` is the exact integer string in base units (7 decimals). Use `amountUnits` for anything exact.
- **Pagination.** List endpoints return a **JSON array**. Query params: `limit` (default 20, max 100) and `offset`. Response headers: `X-Total-Count` and `X-Next-Offset` (absent on the last page). Message history uses `before=<messageId>` instead of `offset`.
- **Idempotency.** Send `Idempotency-Key: <uuid>` on POSTs, as `live.ts` already does. On **financial** endpoints (marked 💰) the server stores the result. Retrying the same request with the same key returns the stored response, and reusing a key with a different body returns `409 IDEMPOTENCY_KEY_REUSED`. To get the benefit, generate the key **once per user action** and reuse it for retries. Today `live.ts` makes a new key per call.
- **Request ID.** Every response has `X-Request-ID`. Quote it in bug reports.

## 3. Errors

```json
{
  "detail": "This quote has already been accepted.",
  "code": "QUOTE_NOT_PENDING",
  "requestId": "01J…",
  "errors": [{ "field": "labour", "message": "Must be ≥ 0" }]
}
```

`detail` is always a human-readable string, which `live.ts` already reads. `errors` is present only on 422.

| Status | Meaning |
|---|---|
| 400 | Malformed request (bad XDR, wrong network) |
| 401 | Missing, invalid or expired access token → refresh, then retry once |
| 403 | Authenticated but not allowed (role), or account suspended |
| 404 | Not found **or not visible to you** (deliberately indistinguishable) |
| 409 | Conflict with current state (e.g. `BOOKING_INVALID_TRANSITION`, `ACTIVE_BOOKING_EXISTS`) |
| 413 | Upload too large |
| 415 | Unsupported file type |
| 422 | Validation failed (`errors[]`) |
| 429 | Rate limited, see `Retry-After` |
| 502 / 503 | Stellar RPC/Horizon unavailable. Safe to retry; the state was not changed |

## 4. Authentication — Issue 1

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/register` | `{name, email, password, role: "customer"\|"professional", city, country: "NG"\|"GH", campusId?, professional?}` | `201 AuthResponse` |
| POST | `/auth/login` | `{email, password}` | `200 AuthResponse` |
| POST | `/auth/refresh` | `{refreshToken}` | `200 AuthResponse` (new refresh token; the old one is now invalid) |
| POST | `/auth/logout` | `{refreshToken}` | `204` (revokes this session) |
| POST | `/auth/logout-all` | — | `204` (revokes every session) |
| GET | `/auth/me` | — | `User` |
| PATCH | `/auth/me` | `{name?, city?, campusId?, phone?}` | `User` |
| POST | `/auth/change-password` | `{currentPassword, newPassword}` | `204` (revokes other sessions) |
| POST | `/auth/verify-email/request` | — | `202` |
| POST | `/auth/verify-email/confirm` | `{token}` | `200 User` |
| POST | `/auth/password-reset/request` | `{email}` | `202` (always, whether or not the account exists) |
| POST | `/auth/password-reset/confirm` | `{token, newPassword}` | `204` (revokes all sessions) |

```ts
AuthResponse = { accessToken: string; access_token: string; refreshToken: string;
                 tokenType: "bearer"; expiresIn: number; user: User }
// access_token is a temporary alias so the current live.ts keeps working. It will be removed after you migrate.

User = { id; name; email; role: "customer"|"professional"|"admin"; status: "ACTIVE"|"SUSPENDED"|"DEACTIVATED";
         emailVerified: boolean; city; country; campus?: Campus; phone?;
         professionalId?;            // Issue 2
         walletAddress?; walletVerified?: boolean }  // Issue 5
```

- Password: 10–128 characters. Registration and login are rate limited. A locked account returns `429` with a generic message.
- The `professional` object in `register` (category, headline, bio, area, coverage, yearsExperience, startingPrice, availability, skills) is processed **from Issue 2**. In Issue 1 it is accepted but ignored, and the profile is created through `POST /professionals/me` instead.
- Access tokens last 15 minutes. On `401`, call `/auth/refresh` once, then retry the request. Today `live.ts` keeps only `access_token`, so users will be signed out every 15 minutes until refresh is added.

## 5. Campuses, categories, professionals, uploads — Issue 2

| Method | Path | Notes |
|---|---|---|
| GET | `/campuses?country&q` | `Campus[]` = `{id, slug, name, shortName, city, state, country}` |
| GET | `/categories` | `Category[]` = `{id, slug, name, parentId?, description}` (active only) |
| GET | `/professionals` | Query: `q, category (slug), campus (slug), city, availability (now\|today), minRating, verifiedOnly, sort (best\|nearest\|most-jobs\|experience), limit, offset` → `Professional[]` |
| GET | `/professionals/{id}` | `Professional` (public) |
| POST | `/professionals/me` | Create own profile (professional role, once) |
| GET | `/professionals/me` | Own profile, including private verification details |
| PATCH | `/professionals/{id}` | Owner only: `{headline, bio, availability, startingPrice, skills, coverage, area, categories?, campusIds?, languages?, yearsExperience?}` |
| POST | `/professionals/me/portfolio` | `{title, caption, categoryId?, imageFileId}` |
| PATCH / DELETE | `/professionals/me/portfolio/{itemId}` | |
| POST | `/professionals/me/verifications` | `{type: "IDENTITY"\|"TRADE"\|"PHONE", fileIds[], note?}` → status `PENDING` |
| GET | `/admin/verifications?status=PENDING` | Admin |
| POST | `/admin/verifications/{id}/decision` | Admin: `{decision: "VERIFIED"\|"REJECTED", reason?}` |
| POST | `/uploads` | `multipart/form-data`: `file`, `purpose` → `FileRef` |
| GET | `/files/{id}` | Streams the file if you may see it. Public files are also served from `url` |

```ts
Professional = {
  id; userId; name; avatarUrl?; category: string /* primary slug */; categories: string[];
  headline; bio; city; area; country; campuses: {id; name; shortName}[];
  distanceKm: number | null;            // null when your campus/location is unknown
  coverage: string[]; skills: string[]; languages: string[];
  rating: number; reviewCount: number; completedJobs: number; yearsExperience: number;
  verification: { identity: boolean; trade: boolean; phone: boolean };
  verificationStatus: "NOT_SUBMITTED"|"PENDING"|"VERIFIED"|"REJECTED";
  availability: "now"|"today"|"this-week"|"unavailable";
  responseMinutes: number | null;
  startingPrice: number; currency: "NGN"|"GHS";
  portfolio: { id; title; caption; imageUrl; categoryId? }[];
  ratingBreakdown: { quality; punctuality; communication; professionalism; value };
  joinedAt;
}

FileRef = { id; url; name; contentType; size; width?; height?; purpose }
```

**Uploads.** Purposes and limits:

| Purpose | Types | Max size | Visibility |
|---|---|---|---|
| `AVATAR` | jpeg/png/webp | 5 MB | public |
| `PORTFOLIO` | jpeg/png/webp | 5 MB | public |
| `REQUEST_MEDIA` | jpeg/png/webp | 10 MB | private |
| `MESSAGE_ATTACHMENT` | jpeg/png/webp | 10 MB | private |
| `COMPLETION_EVIDENCE` | jpeg/png/webp | 10 MB | private |
| `DISPUTE_EVIDENCE` | jpeg/png/webp | 10 MB | private |
| `VERIFICATION_DOCUMENT` | jpeg/png/webp/pdf | 10 MB | owner + admins only |

The server re-encodes images, which strips EXIF and GPS data. A private `url` points at `/files/{id}` and needs the `Authorization` header, so in an `<img>` you either fetch it as a blob or use the `signedUrl` (5-minute expiry) that the server returns on private `FileRef`s.

## 6. Conversations, messages, real-time, calls — Issue 4

| Method | Path | Body / Query | Response |
|---|---|---|---|
| GET | `/conversations` | `limit, offset` | `ConversationSummary[]` (most recent first) |
| POST | `/conversations` | `{professionalId}` | `201 Conversation` or `200` with the existing direct thread |
| GET | `/conversations/{id}` | `messagesLimit` (default 50) | `ConversationDetail` (`messages` oldest→newest, `quotes` from Issue 3) |
| GET | `/conversations/{id}/messages` | `before, limit` | `Message[]` (older history) |
| POST | `/conversations/{id}/messages` | `{body, attachmentFileId?, clientMessageId?}` | `201 Message` |
| POST | `/conversations/{id}/read` | `{lastReadMessageId}` | `204` |
| POST | `/conversations/{id}/report` | `{reason, details?, messageId?}` | `201` |
| POST | `/calls/sessions` | `{conversationId}` | `201 {sessionId, status: "RINGING", iceServers}` |
| POST | `/calls/sessions/{id}/end` | `{reason?}` | `200 CallSession` |

```ts
Conversation = { id; customerId; professionalId; bookingId?; serviceRequestId?;
                 lastMessageAt; lastMessagePreview; unreadFor: string[] }
ConversationSummary = { conversation; professional: Professional; customer: PublicUser; unread: boolean }
ConversationDetail  = ConversationSummary & { messages: Message[]; quotes: Quote[] }
Message = { id; conversationId; senderId: string | null /* null = system */;
            kind: "text"|"image"|"quote"|"system"; body; quoteId?;
            attachment?: FileRef; createdAt; readAt? }
PublicUser = { id; name; avatarUrl?; city; campus? }   // no email or phone
```

`clientMessageId` (a uuid the client generates) makes message sends safe to retry: the same id returns the same message.

**WebSocket:** `GET /ws/conversations/{id}?token=<accessToken>`

- Close codes: `4401` invalid or expired token (refresh, then reconnect), `4403`/`4404` no access, `4429` too many messages, `1011` server error.
- Server → client frames (JSON):

```json
{ "type": "message.created", "conversationId": "…", "data": { /* Message */ } }
{ "type": "message.read",    "data": { "userId": "…", "lastReadMessageId": "…", "at": "…" } }
{ "type": "typing",          "data": { "userId": "…" } }
{ "type": "quote.created" | "quote.updated", "data": { /* Quote */ } }          // Issue 3
{ "type": "booking.updated", "data": { "bookingId": "…", "status": "…" } }     // Issue 3+
{ "type": "call.offer" | "call.answer" | "call.ice" | "call.end", "data": { "sessionId": "…", "from": "…", "payload": {} } }
{ "type": "pong" }
```

- Client → server frames: `{"type":"typing"}`, `{"type":"read","lastReadMessageId":"…"}`, `{"type":"ping"}`, and `{"type":"call.offer"|"call.answer"|"call.ice"|"call.end","sessionId":"…","payload":{…}}`. The server relays call frames only to the other participant of that session.
- Send messages over **REST**, not the socket. Refetching on any frame (what `live.ts` does today) still works. Applying `message.created` directly saves a round trip.
- Calls: the backend handles session state and relays signaling. WebRTC media is browser-to-browser. `iceServers` comes from config (public STUN). No TURN server is provided, so calls can fail on restrictive networks.

## 7. Service requests, quotes, bookings — Issue 3

| Method | Path | Who | Body → Response |
|---|---|---|---|
| POST | `/service-requests` | customer | `{categoryId, title, description, item?, campusId?, locationText?, preferredStart?, preferredEnd?, mediaFileIds?, targetProfessionalId?}` → `201 ServiceRequest` |
| GET | `/service-requests/mine` | customer | `ServiceRequest[]` |
| GET | `/service-requests/feed` | professional | Open requests in your categories and campuses → `ServiceRequest[]` (approximate location only) |
| GET | `/service-requests/{id}` | owner / eligible professional | `ServiceRequest` |
| POST | `/service-requests/{id}/respond` | professional | `{message}` → `201 Conversation` (linked to the request) |
| POST | `/service-requests/{id}/cancel` | owner | → `ServiceRequest` |
| POST | `/quotes` | professional | `QuoteInput` → `201 Quote` (supersedes your previous pending quote in that conversation) |
| POST | `/quotes/{id}/withdraw` | professional | → `Quote` |
| POST | `/quotes/{id}/accept` 💰 | customer | → `201 Booking` |
| POST | `/quotes/{id}/reject` | customer | `{reason?}` → `Quote` |
| GET | `/bookings` | participant | `status?, role?, limit, offset` → `BookingBundle[]` |
| GET | `/bookings/{id}` | participant / admin | `BookingBundle` |
| POST | `/bookings/{id}/start` | professional | → `Booking` (requires `FUNDED`) |
| POST | `/bookings/{id}/cancel` | participant | `{reason}` → `Booking` (only `PENDING_PAYMENT`) |

```ts
QuoteInput = { conversationId; title; description; labour; materials; currency;
               completionDate /* YYYY-MM-DD */; paymentTerms; serviceMethod?;
               milestones?: {title; percent}[] /* descriptive only — single payment */; validUntil? }
Quote = { id; conversationId; serviceRequestId?; professionalId; customerId; version;
          status: "PENDING"|"ACCEPTED"|"REJECTED"|"SUPERSEDED"|"WITHDRAWN";
          title; description; labour; materials; total; currency; completionDate;
          paymentTerms; serviceMethod; milestones; createdAt; acceptedAt?; agreementHash? }
Booking = { id; quoteId; agreementId; agreementHash; conversationId; customerId; professionalId;
            title; address: string | null /* visible to the professional from FUNDED */;
            status: BookingStatus; amount; currency; createdAt;
            escrowId?; completion?; disputeId?; reviewId?; timeline: TimelineEvent[] }
BookingStatus = "PENDING_PAYMENT"|"FUNDED"|"IN_PROGRESS"|"COMPLETION_SUBMITTED"|"COMPLETED"
              | "DISPUTED"|"CANCELLED"|"REFUNDED"|"RESOLVED"
TimelineEvent = { at; label; actor: "customer"|"professional"|"system"|"chain"|"admin" }
BookingBundle = { booking; quote; escrow?; professional; customer: PublicUser; dispute?; review?;
                  allowedActions: string[] }   // e.g. ["fund","cancel"]: render buttons from this
```

`allowedActions` is computed by the server for the calling user. Use it instead of re-implementing the state machine in `booking.ts`.

## 8. Wallets — Issue 5

| Method | Path | Body → Response |
|---|---|---|
| POST | `/wallets/challenge` | `{address}` → `{message, nonce, expiresAt}` |
| POST | `/wallets` | `{address, message, signature}` → `User` (wallet verified) |
| GET | `/wallets` | → `Wallet[]` = `{id, address, network, verifiedAt, isPrimary, accountExists, hasEscrowTrustline}` |
| DELETE | `/wallets/{id}` | → `204` (blocked while that wallet is a party to an active escrow) |

Flow:

1. Freighter `requestAccess()` gives the address. Check the network passphrase is testnet.
2. `POST /wallets/challenge`.
3. Freighter `signMessage(message)`. Send the signature exactly as `signOwnershipMessage` returns it (base64).
4. `POST /wallets`.

The challenge is single-use and expires after 5 minutes. **Both** the customer and the professional need a verified wallet before an escrow can be prepared.

## 9. Escrow and payments — Issues 6 and 7

Every money movement is **two calls**: *prepare* (returns `unsignedXdr`), sign in Freighter, *submit* (send `signedXdr` to the same route). The backend never treats your signature as settlement. Keep polling `GET /bookings/{id}` while `escrow.reconciliation === "PENDING_CONFIRMATION"`.

| Action | Who | Prepare | Submit | Booking result on confirmation |
|---|---|---|---|---|
| Fund 💰 | customer | `POST /bookings/{id}/escrow {customerWallet}` → `{escrow, unsignedXdr}` | `POST /escrows/{id}/funding {signedXdr}` → `Escrow` | `FUNDED` |
| Release 💰 | customer | `POST /escrows/{id}/release {}` → `{escrow, unsignedXdr}` | `POST /escrows/{id}/release {signedXdr}` → `{escrow}` | `COMPLETED` |
| Refund 💰 | professional | `POST /escrows/{id}/refund {}` | `POST /escrows/{id}/refund {signedXdr}` | `REFUNDED` |
| Dispute 💰 | either party | `POST /escrows/{id}/disputes {reason, details}` → `{dispute, escrow, unsignedXdr}` | `POST /disputes/{id}/lock {signedXdr}` → `{dispute, escrow}` | `DISPUTED` |
| Resolve 💰 | admin (arbiter wallet) | `POST /disputes/{id}/resolve {outcome, splitPercentToProfessional?, note}` → `{dispute, escrow, unsignedXdr}` | `POST /disputes/{id}/resolve {signedXdr}` | `COMPLETED` / `REFUNDED` / `RESOLVED` |
| Read | participant | `GET /escrows/{id}` → `Escrow` | | |
| Receipts | participant | `GET /bookings/{id}/receipts` → `Receipt[]` | | |

Sign with `signTransaction(unsignedXdr, { networkPassphrase: "Test SDF Network ; September 2015", address })`. Do not modify the transaction: the backend rejects any signed envelope whose hash differs from the one it prepared (`400 TX_MISMATCH`). If preparation is older than ~5 minutes, or the account's sequence number changed, submission fails with `409 TX_EXPIRED`. Prepare again.

```ts
Escrow = { id; bookingId; contractId; state: "CREATED"|"FUNDED"|"DISPUTED"|"RELEASED"|"REFUNDED"|"RESOLVED";
           asset; assetIssuer?; amount; amountUnits: string; localAmount; currency; rate; rateSource;
           networkFee; customerWallet?; professionalWallet?;
           reconciliation: "AWAITING_SIGNATURE"|"PENDING_CONFIRMATION"|"CONFIRMED"|"FAILED";
           failureReason?; transactions: EscrowTransaction[]; createdAt }
EscrowTransaction = { kind: "FUND"|"RELEASE"|"REFUND"|"DISPUTE"|"RESOLVE"; hash; ledger?; at;
                      status: "PENDING"|"CONFIRMED"|"FAILED"; explorerUrl }
Receipt = { id; number; kind: "FUNDING"|"RELEASE"|"REFUND"|"RESOLUTION"; bookingId; amount; asset;
            localAmount; currency; txHash; ledger; issuedAt; payloadHash }
```

Prerequisites the UI should check, which the API also enforces:

- Customer wallet: exists on testnet, holds XLM for fees, has a trustline and balance for the escrow asset. `GET /wallets` reports `accountExists` and `hasEscrowTrustline`.
- Professional wallet: exists on testnet with a trustline, or the payout transfer fails.

## 10. Completion, disputes, reviews — Issues 6 and 7

| Method | Path | Who | Body → Response |
|---|---|---|---|
| POST | `/bookings/{id}/completion` | professional | `{notes, checklist: {label, done}[], photoFileIds: string[]}` → `Booking` (`COMPLETION_SUBMITTED`) |
| POST | `/disputes/{id}/evidence` | party / admin | `{note, fileId?}` → `DisputeEvidence` |
| GET | `/disputes/{id}` | party / admin | `Dispute` (+ evidence) |
| GET | `/admin/disputes` | admin | `status?` → `DisputeBundle[]` |
| POST | `/bookings/{id}/reviews` | customer | `{ratings: {quality, punctuality, communication, professionalism, value}, comment}` → `201 Review` |
| GET | `/professionals/{id}/reviews` | public | `limit, offset` → `Review[]` (published only) |
| POST | `/reviews/{id}/response` | the professional | `{body}` → `Review` |
| POST | `/reviews/{id}/report` | any authenticated user | `{reason, details?}` → `201` |
| POST | `/admin/reviews/{id}/moderate` | admin | `{action: "HIDE"\|"RESTORE"\|"REMOVE", reason}` → `Review` |

- Review rules:
  - One review per booking.
  - Only the booking's customer can review, within 30 days of completion.
  - The booking must be `COMPLETED` or `RESOLVED`; see decision D10 in DEVELOPMENT_PLAN.
  - Each rating is an integer 1–5.
  - `overall` is computed by the server as the mean of the five ratings, to one decimal.
- `Dispute` matches the current `types.ts`, plus `status: "AWAITING_SETTLEMENT"` and `evidence[]`.

## 11. Notifications and admin — Issue 8

| Method | Path | Response |
|---|---|---|
| GET | `/notifications` | `unread?, limit, offset` → `AppNotification[]` |
| POST | `/notifications/read` | `{ids?: string[]}` (omit = all) → `204` |
| GET | `/notifications/unread-count` | `{count}` |
| GET | `/admin/users`, `/admin/bookings`, `/admin/escrows`, `/admin/service-requests`, `/admin/reports`, `/admin/audit-logs` | Filterable lists |
| PATCH | `/admin/users/{id}/status` | `{status, reason}` (delivered in Issue 1) |
| GET | `/admin/ops/status` | Reconciler and RPC health |

## 12. Local development (backend)

```bash
cd backend
uv sync
cp .env.example .env               # fill JWT_SECRET etc.
brew services start postgresql@16  # or: docker compose up db
uv run alembic upgrade head
uv run python -m app.cli seed
uv run python -m app.cli create-admin --email ops@unifix.local
uv run uvicorn app.main:app --reload --port 8000
# frontend:
cd ../frontend && NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev
```

## 13. Changes the frontend needs

These are differences between the planned contract and what `frontend/src/lib/api/live.ts` and `types.ts` do today, grouped by when they matter. None of them block demo mode.

| # | Area | Today | Planned | When |
|---|---|---|---|---|
| F1 | Base URL | `NEXT_PUBLIC_API_URL=http://localhost:8000` | add `/api/v1` | Issue 1 |
| F2 | Tokens | stores `access_token` only | store `refreshToken`; on 401 call `/auth/refresh`, retry once | Issue 1 |
| F3 | Idempotency | new key per call | one key per user action, reused on retry | Issue 3 |
| F4 | Categories | hardcoded `CategoryId` union (8 trades) | load `/categories`; slugs are data | Issue 2 |
| F5 | Campus | not modelled | optional `campusId` at sign-up and in profile; `campus` filter in discovery | Issue 2 |
| F6 | Portfolio | `{caption, tone}` | `{title, caption, imageUrl}` | Issue 2 |
| F7 | `distanceKm` | always a number | `number \| null` | Issue 2 |
| F8 | Attachments / evidence photos | base64 `dataUrl` in JSON | upload first via `POST /uploads`, send `attachmentFileId` / `photoFileIds` | Issues 4, 6 |
| F9 | `Message.senderId` | always a string | `null` for system messages | Issue 4 |
| F10 | Booking actions | client-side `nextStep()` | render from `allowedActions` | Issue 3 |
| F11 | Booking statuses | 7 values | add `REFUNDED`, `RESOLVED` | Issue 3 |
| F12 | Escrow state | 5 values | add `RESOLVED`; `transactions[].kind` adds `DISPUTE`, `RESOLVE`; drop `simulated` | Issue 6 |
| F13 | Open dispute | one call → `Dispute` | prepare → sign → `POST /disputes/{id}/lock` | Issue 7 |
| F14 | Resolve dispute | one call by the admin | prepare → admin signs with the arbiter wallet → submit | Issue 7 |
| F15 | Refund | none | professional "cancel and refund" button → `/escrows/{id}/refund` | Issue 6 |
| F16 | Reviews | `ratings` only | unchanged request; response adds `overall`, `status` | Issue 7 |
| F17 | Milestones | percents shown as a plan | single payment: present milestones as work steps only | Issue 3 |
| F18 | Email verification and password reset | no screens | `/auth/verify-email/*`, `/auth/password-reset/*` | Issue 1 |
