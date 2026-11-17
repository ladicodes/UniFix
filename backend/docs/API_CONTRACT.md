# UniFix API Contract (for the frontend)

Audience: Victor (frontend). You should not need to read backend code to integrate.
Status: **Revision 3 (2026-11-17).** §1–§6 are **implemented** (Issues #1, #2 and #4). Later sections remain the planned contract until their issues land. Each section names the issue that delivers it. Once an issue merges, the live OpenAPI schema at `/api/v1/openapi.json` (Swagger UI `/api/v1/docs`) is authoritative for that issue's endpoints, and this document is updated in the same PR.

Revision 3 changes:

- Session list and revoke endpoints.
- No automatic dispute timeout; disputes carry SLA dates instead.
- The demo FX rate is flagged in every response and receipt (F26).

Revision 2 changes:

- All fields are **snake_case**.
- Refresh tokens move to an **HttpOnly cookie** with CSRF protection.
- WebSockets authenticate with **single-use tickets**.
- Money is **integers** with explicit currency or asset.
- New escrow actions: completion signature, extend, cancellation request, concessions.

**§13 lists every change the frontend needs**, with file and line references.

---

## 1. Base URL, versioning, deployment topology

| | Local | Production |
|---|---|---|
| REST base | `http://localhost:8000/api/v1` | `https://api.<domain>/api/v1` |
| WebSocket base | `ws://localhost:8000/api/v1` | `wss://api.<domain>/api/v1` |
| Frontend origin | `http://localhost:3000` | `https://app.<domain>` |

**Same-site requirement.** The refresh cookie is `SameSite=Strict`, so the frontend and API must share a registrable domain: e.g. `app.unifix.ng` + `api.unifix.ng`, or the API proxied under the frontend origin via a Next.js rewrite. `localhost:3000` and `localhost:8000` are same-site.

`*.vercel.app` preview URLs are **cross-site** to any other domain, because `vercel.app` is on the Public Suffix List. Previews must either use the rewrite proxy or a custom preview domain.

## 2. Conventions

- **snake_case everywhere:** request bodies, response bodies and query parameters. Unknown fields are rejected with `422`, so a camelCase field name fails loudly instead of being ignored.
- **Enum values are `UPPER_SNAKE_CASE`.** Slugs (categories, campuses) are lowercase-kebab data identifiers.
- **IDs** are UUID strings. **Timestamps** are RFC 3339 UTC (`2026-11-17T10:30:00Z`). **Dates** are `YYYY-MM-DD`. **On-chain deadlines** are Unix seconds (integers).
- **Fiat money:** an integer in **minor units** plus an ISO 4217 code, e.g. `{"total_minor": 3500000, "currency": "NGN"}` = ₦35,000.00. Never a float.
- **Token money:** an integer string in **base units**, e.g. `"asset_amount": "212121213"`, always alongside an `asset` object `{code, issuer, sac_contract_id, decimals}`. 21.2121213 USDC is shown as `asset_amount / 10^decimals`; use BigInt or a decimal library, not `Number`.
- **Network fees:** `fee_stroops` as an integer string (XLM).
- **Pagination:** list endpoints return a **JSON array**. Params `limit` (default 20, max 100) and `offset`. Headers `X-Total-Count`, plus `X-Next-Offset` when another page exists. Message history uses `before=<message_id>`.
- **Idempotency:** `Idempotency-Key: <uuid>` on POSTs. On 💰 routes the server stores the result: same key and body replays the response; same key with a different body returns `409 IDEMPOTENCY_KEY_REUSED`. Generate **one key per user action** and reuse it on retries.
- **Request ID:** every response carries `X-Request-ID`.

## 3. Errors

```json
{ "detail": "This quote has already been accepted.", "code": "QUOTE_NOT_PENDING",
  "request_id": "…", "errors": [{ "field": "labour_minor", "message": "Must be ≥ 0" }] }
```

`detail` is always a string. `errors` appears only on 422.

| Status | Meaning |
|---|---|
| 400 | Malformed request (bad XDR, wrong network) |
| 401 | Missing, invalid or expired access token → refresh once, then retry |
| 403 | Role not allowed, account suspended, or CSRF/Origin check failed (`CSRF_REJECTED`) |
| 404 | Not found **or not visible to you** |
| 409 | State conflict (`BOOKING_INVALID_TRANSITION`, `ACTIVE_BOOKING_EXISTS`, `REFRESH_RACE`, `TX_EXPIRED`, …) |
| 413 / 415 | Upload too large / unsupported type |
| 422 | Validation failed (`errors[]`) |
| 429 | Rate limited (`Retry-After`) |
| 502 / 503 | Stellar RPC/Horizon unavailable. Safe to retry; no state changed |

## 4. Authentication and sessions — Issue 1

### 4.1 Token model

| Token | Where it lives | Lifetime | Sent as |
|---|---|---|---|
| Access token (JWT) | **JavaScript memory only.** Not localStorage or sessionStorage | 15 min | `Authorization: Bearer <token>` on every API call |
| Refresh token (opaque, 256-bit) | **HttpOnly cookie** set by the API; JavaScript cannot read it | 14 days idle, 30 days absolute; rotated on every use | Automatically by the browser, **only** to `/api/v1/auth/*` |

**Refresh cookie attributes:**

| Attribute | Production | Development (`ENV=development`) |
|---|---|---|
| Name | `__Secure-unifix_rt` | `unifix_rt` |
| `HttpOnly` | yes | yes |
| `Secure` | yes | no (plain `http://localhost`) |
| `SameSite` | `Strict` | `Strict` |
| `Path` | `/api/v1/auth` | `/api/v1/auth` |
| `Domain` | not set (host-only, API host) | not set |
| `Max-Age` | remaining absolute lifetime | same |

The server refuses to start in production with `Secure` disabled.

### 4.2 CSRF protection

Only the routes that **read the cookie** (`/auth/refresh`, `/auth/logout`) or **set it** (`/auth/login`, `/auth/register`) are exposed to CSRF. Every other route needs the `Authorization` header, which browsers never attach automatically.

The cookie routes require **all** of the following:

1. **`Origin` header present and in the `CORS_ORIGINS` allowlist.** Missing or foreign `Origin` → `403 CSRF_REJECTED`.
2. **The header `X-CSRF-Protection: 1`.** A custom header makes the browser send a CORS preflight. The preflight succeeds only for allowlisted origins, so a hostile page cannot send it.
3. **The cookie's `SameSite=Strict`**, so cross-site requests do not carry it at all.

### 4.3 CORS

- `allow_origins` is an explicit list (`CORS_ORIGINS`). A wildcard is refused at startup, because credentials are enabled.
- `allow_credentials = true`.
- Methods: `GET, POST, PATCH, PUT, DELETE`.
- Allowed request headers: `Authorization, Content-Type, Idempotency-Key, X-Request-ID, X-CSRF-Protection`.
- Exposed headers: `X-Total-Count, X-Next-Offset, X-Request-ID, Retry-After`.
- Preflight max-age: 600 s.

### 4.4 Rotation and reuse detection

- Every `/auth/refresh` issues a new refresh cookie and invalidates the presented one.
- Presenting an **already-rotated** token is treated as theft. The whole session family is revoked, the cookie is cleared, the response is `401`, and an audit event `auth.refresh_reuse_detected` is written.
- **Multi-tab race grace:** two tabs may refresh with the same cookie at the same moment. If the presented token was rotated **less than 30 s ago** and its successor is unused, the server returns `409 REFRESH_RACE` without revoking anything. The browser's cookie jar already holds the successor, so the client simply retries once after ~300 ms.
- Logout, logout-all, password change, password reset and suspension revoke the relevant families immediately. The access tokens of revoked sessions stop working on their next request.

### 4.5 Endpoints

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| POST | `/auth/register` | Origin + CSRF header | `{name, email, password, role: "CUSTOMER"\|"PROFESSIONAL", city, country: "NG"\|"GH", campus_id?, professional?}` | `201 AuthResponse` + `Set-Cookie` |
| POST | `/auth/login` | Origin + CSRF header | `{email, password}` | `200 AuthResponse` + `Set-Cookie` |
| POST | `/auth/refresh` | cookie + Origin + CSRF header | — | `200 AuthResponse` + rotated `Set-Cookie` |
| POST | `/auth/logout` | cookie + Origin + CSRF header | — | `204` + cookie cleared |
| POST | `/auth/logout-all` | Bearer | — | `204` + cookie cleared |
| GET | `/auth/sessions` | Bearer | — | `Session[]` = `{id, created_at, last_used_at, user_agent, ip_hint, current}` |
| DELETE | `/auth/sessions/{id}` | Bearer | — | `204` (revokes that session; own sessions only) |
| GET | `/auth/me` | Bearer | — | `User` |
| PATCH | `/auth/me` | Bearer | `{name?, city?, campus_id?, phone?}` | `User` |
| POST | `/auth/change-password` | Bearer | `{current_password, new_password}` | `204` (other sessions revoked) |
| POST | `/auth/verify-email/request` | Bearer | — | `202` |
| POST | `/auth/verify-email/confirm` | — | `{token}` | `200 User` |
| POST | `/auth/password-reset/request` | — | `{email}` | `202` (always) |
| POST | `/auth/password-reset/confirm` | — | `{token, new_password}` | `204` (all sessions revoked) |
| PATCH | `/admin/users/{id}/status` | Bearer (admin) | `{status, reason}` | `User` |

```ts
AuthResponse = { access_token: string; token_type: "Bearer"; expires_in: number /* seconds */; user: User }
User = { id; name; email; role: "CUSTOMER"|"PROFESSIONAL"|"ADMIN"; status: "ACTIVE"|"SUSPENDED"|"DEACTIVATED";
         email_verified: boolean; city: string | null; country: "NG"|"GH"; phone: string | null; created_at;
         campus: Campus | null; professional_id: string | null;    // added by Issue 2
         wallet_address: string | null; wallet_verified: boolean }  // added by Issue 5
Session = { id; created_at; last_used_at; user_agent: string | null; ip_hint: string | null; current: boolean }
```

The refresh token is **never** in a response body.

Email links point to `${FRONTEND_BASE_URL}/verify-email?token=…` and `${FRONTEND_BASE_URL}/reset-password?token=…`; the frontend posts the token to the matching `/confirm` route.

Login lockout: 5 failed attempts for an email (registered or not) lock that email for 15 minutes (`429`, generic message, `Retry-After`). Auth routes are also rate-limited per client IP.

Timestamps are returned as RFC 3339 with an explicit `+00:00` offset (UTC).

The `professional` object in `register` (`category_slug, headline, bio, area, coverage, years_experience, starting_price_minor, currency, availability, skills`) is processed from Issue 2. It is processed atomically: if the profile is invalid (e.g. unknown category), no account is created. Sending it with role `CUSTOMER` is a 422.

### 4.6 Frontend session flow

```
App load ─► POST /auth/refresh (credentials: "include", X-CSRF-Protection: 1)
            ├─ 200 → keep access_token in memory, render signed-in
            └─ 401 → signed out
API call ─► Authorization: Bearer <in-memory token>
            └─ 401 → single-flight refresh (navigator.locks "unifix-refresh") → retry once
                      └─ 409 REFRESH_RACE → wait 300 ms → refresh again
Sign in / up ─► POST /auth/login|register (credentials: "include", X-CSRF-Protection: 1)
Sign out ─► POST /auth/logout (credentials: "include", X-CSRF-Protection: 1) → drop in-memory token
```

Use `fetch(url, { credentials: "include" })` for the four cookie routes. Sending it on every call is also fine.

## 5. Campuses, categories, professionals, uploads — Issue 2

| Method | Path | Notes |
|---|---|---|
| GET | `/campuses?country&q` | `Campus[]` = `{id, slug, name, short_name, city, state, country}` |
| POST / PATCH | `/admin/campuses[/{id}]` | Admin: create / update / deactivate a campus |
| POST / PATCH | `/admin/categories[/{id}]` | Admin: create / update / disable a category (one level of nesting) |
| GET | `/categories` | `Category[]` = `{id, slug, name, parent_id, description}` |
| GET | `/professionals` | Query: `q, category, campus, city, availability (NOW\|TODAY), min_rating, verified_only, sort (BEST\|NEAREST\|MOST_JOBS\|EXPERIENCE), lat, lng, limit, offset` |
| GET | `/professionals/{id}` | Public `Professional` |
| POST / GET | `/professionals/me` | Create once / read own (includes private verification details) |
| PATCH | `/professionals/{id}` | Owner: `{headline, bio, availability, starting_price_minor, skills, coverage, area, category_slugs?, campus_ids?, languages?, years_experience?}` |
| POST | `/professionals/me/portfolio` | `{title, caption, category_id?, image_file_id}` |
| PATCH / DELETE | `/professionals/me/portfolio/{item_id}` | |
| POST | `/professionals/me/verifications` | `{type: "IDENTITY"\|"TRADE"\|"PHONE", file_ids, note?}` |
| GET | `/admin/verifications?status=PENDING` | Admin |
| POST | `/admin/verifications/{id}/decision` | Admin: `{decision: "VERIFIED"\|"REJECTED", reason?}` |
| POST | `/uploads` | `multipart/form-data`: `file`, `purpose` → `FileRef` |
| GET | `/files/{id}` | Streams the file if visible to the caller |

```ts
Professional = {
  id; user_id; name; avatar_url: string | null; category: string; categories: string[];
  headline; bio; city; area; country; campuses: { id; name; short_name }[];
  distance_km: number | null; coverage: string[]; skills: string[]; languages: string[];
  rating: number; review_count: number; completed_jobs: number; years_experience: number;
  verification: { identity: boolean; trade: boolean; phone: boolean };
  verification_status: "NOT_SUBMITTED"|"PENDING"|"VERIFIED"|"REJECTED";
  availability: "NOW"|"TODAY"|"THIS_WEEK"|"UNAVAILABLE"; response_minutes: number | null;
  starting_price_minor: number; currency: "NGN"|"GHS";
  portfolio: { id; title; caption; image_url; category_id: string | null }[];
  rating_breakdown: { quality; punctuality; communication; professionalism; value };
  joined_at;
}
FileRef = { id; url; signed_url: string | null; name; content_type; size; width: number | null; height: number | null; purpose }
ProfessionalPrivateOut = Professional & { is_listed: boolean; latitude: string | null; longitude: string | null;
                                          verifications: { id; type; status; note; files: FileRef[]; submitted_at;
                                                           reviewed_at; rejection_reason }[] }
```

Implementation notes (Issue #2):

- **Discovery filters:**
  - `category` matches the primary category **or** any additional category; a parent slug also matches its sub-categories.
  - Unknown `category`/`campus` slugs return `[]`.
  - `availability=TODAY` includes `NOW`.
- **Search:** `q` runs a full-text search over headline, bio, area, city and skills, plus a name match.
- **Sorting:**
  - `BEST` is a Bayesian average, so 4.6★ from 40 reviews outranks 5★ from 2.
  - `NEAREST` uses `lat`/`lng`, else the `campus` filter's centroid, else the caller's campus. Distance is measured to the professional's approximate point, or else to their nearest served campus.
- **Verification:**
  - `verification_status` becomes `VERIFIED` once the **IDENTITY** check is approved.
  - `PENDING` while any check awaits review, `REJECTED` when all submitted checks were rejected.
  - IDENTITY and TRADE require at least one `VERIFICATION_DOCUMENT` upload; PHONE may have none (reviewed manually).
  - Rejection requires a reason.
- **Locations:** professional coordinates are rounded to 2 decimals (~1 km) before storage and only appear in `ProfessionalPrivateOut`.
- **`User` additions:** `User` now also has `avatar_url`, `campus` and `professional_id`. `PATCH /auth/me` accepts `campus_id` and `avatar_file_id` (an `AVATAR` upload of yours); `null` clears either.
- **`GET /files/{id}` response headers:** `Content-Security-Policy: default-src 'none'; sandbox`; `Content-Disposition: attachment` for PDFs; `Cache-Control: private, no-store` for private files.

`rating` and the breakdown values are display averages (`number`, 2 decimals). They are not money.

**Upload purposes:**

| Purpose | Types | Max | Visibility |
|---|---|---|---|
| `AVATAR`, `PORTFOLIO` | jpeg/png/webp | 5 MB | public |
| `REQUEST_MEDIA`, `MESSAGE_ATTACHMENT`, `COMPLETION_EVIDENCE`, `DISPUTE_EVIDENCE` | jpeg/png/webp | 10 MB | private |

Who may upload:

- `PORTFOLIO`, `VERIFICATION_DOCUMENT` and `COMPLETION_EVIDENCE`: professionals.
- `REQUEST_MEDIA`: customers.
- `MESSAGE_ATTACHMENT`: both customers and professionals.
- `AVATAR`: anyone.

Uploads are rate-limited per user (`429`). The type is detected from the file's bytes; a mismatched or unreadable file returns `415`.
| `VERIFICATION_DOCUMENT` | jpeg/png/webp/pdf | 10 MB | owner + admins only |

- Images are re-encoded, which strips EXIF and GPS.
- For a private file, use `signed_url` (5-minute expiry) in `<img>` tags, or fetch `url` with the Bearer header.

## 6. Conversations, messages, real-time, calls — Issue 4

| Method | Path | Body / Query | Response |
|---|---|---|---|
| GET | `/conversations` | `limit, offset` | `ConversationSummary[]` |
| POST | `/conversations` | `{professional_id}` | `201 Conversation` (or `200` with the existing direct thread) |
| GET | `/conversations/{id}` | `messages_limit` | `ConversationDetail` |
| GET | `/conversations/{id}/messages` | `before, limit` | `Message[]` |
| POST | `/conversations/{id}/messages` | `{body, attachment_file_id?, client_message_id?}` | `201 Message` |
| POST | `/conversations/{id}/read` | `{last_read_message_id}` | `204` |
| POST | `/conversations/{id}/report` | `{reason, details?, message_id?}` | `201` |
| POST | `/ws/tickets` | `{scope: "CONVERSATION", conversation_id}` | `201 {ticket, expires_at, ws_path}` |
| POST | `/calls/sessions` | `{conversation_id}` | `201 {session_id, status: "RINGING", ice_servers}` |
| POST | `/calls/sessions/{id}/end` | `{reason?}` | `CallSession` |

```ts
Conversation = { id; customer_id; professional_id; booking_id: string | null; service_request_id: string | null;
                 last_message_at; last_message_preview; unread_for: string[] }
ConversationSummary = { conversation; professional: Professional; customer: PublicUser; unread: boolean }
ConversationDetail  = ConversationSummary & { messages: Message[]; quotes: Quote[] }
Message = { id; conversation_id; sender_id: string | null; kind: "TEXT"|"IMAGE"|"QUOTE"|"SYSTEM";
            body; quote_id: string | null; attachment: FileRef | null; created_at; read_at: string | null }
PublicUser = { id; name; avatar_url: string | null; city; campus: Campus | null }
```

### 6.1 WebSocket authentication (single-use tickets)

The access token is never put in a WebSocket URL.

1. `POST /ws/tickets {scope: "CONVERSATION", conversation_id}` with the Bearer header. The server checks membership and returns `{ticket, expires_at, ws_path: "/ws/conversations/{id}"}`. A ticket:
   - is 256-bit random;
   - is stored only as a hash;
   - is valid for **30 seconds**;
   - is **single-use**;
   - is bound to your user, your session and that conversation.
2. Connect immediately to `wss://…/api/v1/ws/conversations/{id}?ticket=<ticket>`.
3. Before accepting the connection, the server:
   - checks the `Origin` header against the allowlist (protection against cross-site WebSocket hijacking);
   - consumes the ticket atomically (a second use fails);
   - checks the ticket's scope matches the path;
   - checks the session is not revoked and the user is `ACTIVE`;
   - re-checks membership.
4. While connected, the server re-validates the session every 60 s and closes the connection when it is revoked. Connections also close after **1 hour** with code `4000`; fetch a new ticket and reconnect.
5. Every reconnect needs a **new ticket**.

**Close codes:**

| Code | Meaning | Client action |
|---|---|---|
| `4000` | Re-authentication due (max lifetime) | New ticket, reconnect |
| `4401` | Ticket invalid, expired or already used, or session revoked | Refresh the access token, new ticket, reconnect |
| `4403` / `4404` | Origin rejected / no access | Do not retry |
| `4429` | Too many frames | Back off |
| `1011` | Server error | Back off, then reconnect |

Server → client frames:

```json
{ "type": "MESSAGE_CREATED", "conversation_id": "…", "data": { /* Message */ } }
{ "type": "MESSAGE_READ", "data": { "user_id": "…", "last_read_message_id": "…", "at": "…" } }
{ "type": "TYPING", "data": { "user_id": "…" } }
{ "type": "QUOTE_CREATED" | "QUOTE_UPDATED", "data": { /* Quote */ } }
{ "type": "BOOKING_UPDATED", "data": { "booking_id": "…", "status": "…" } }
{ "type": "CALL_OFFER" | "CALL_ANSWER" | "CALL_ICE" | "CALL_END", "data": { "session_id": "…", "from": "…", "payload": {} } }
{ "type": "PONG" }
```

Client → server: `{"type": "TYPING"}`, `{"type": "READ", "last_read_message_id": "…"}`, `{"type": "PING"}`, `{"type": "CALL_OFFER"|"CALL_ANSWER"|"CALL_ICE"|"CALL_END", "session_id": "…", "payload": {…}}`. Send chat messages over REST.

Calls: the backend handles session state and relays signaling only. `ice_servers` are public STUN servers. No TURN server is provided.

## 7. Service requests, quotes, bookings — Issue 3

| Method | Path | Who | Body → Response |
|---|---|---|---|
| POST | `/service-requests` | customer | `{category_id, title, description, item?, campus_id?, location_text?, preferred_start?, preferred_end?, media_file_ids?, target_professional_id?}` → `201 ServiceRequest` |
| GET | `/service-requests/mine` | customer | `ServiceRequest[]` |
| GET | `/service-requests/feed` | professional | `ServiceRequest[]` (approximate location only) |
| GET | `/service-requests/{id}` | owner / eligible professional | `ServiceRequest` |
| POST | `/service-requests/{id}/respond` | professional | `{message}` → `201 Conversation` |
| POST | `/service-requests/{id}/cancel` | owner | `ServiceRequest` |
| POST | `/quotes` | professional | `QuoteInput` → `201 Quote` |
| POST | `/quotes/{id}/withdraw` | professional | `Quote` |
| POST | `/quotes/{id}/accept` 💰 | customer | `201 Booking` |
| POST | `/quotes/{id}/reject` | customer | `{reason?}` → `Quote` |
| GET | `/bookings` | participant | `status?, role?, limit, offset` → `BookingBundle[]` |
| GET | `/bookings/{id}` | participant / admin | `BookingBundle` |
| GET | `/bookings/{id}/agreement` | participant / admin | `{agreement_json, agreement_hash, escrow_terms_json, terms_hash}` (canonical strings) |
| POST | `/bookings/{id}/start` | professional | `Booking` (requires `FUNDED`) |
| POST | `/bookings/{id}/cancel` | participant | `{reason}` → `Booking` (`PENDING_PAYMENT` only) |
| POST | `/bookings/{id}/cancellation-requests` | customer | `{reason}` → `CancellationRequest` (`FUNDED`/`IN_PROGRESS`) — Issue 6 |
| POST | `/cancellation-requests/{id}/decline` | professional | `{reason}` → `CancellationRequest` — Issue 6. Accepting means signing a refund (§9) |

```ts
QuoteInput = { conversation_id; title; description; labour_minor: number; materials_minor: number; currency: "NGN"|"GHS";
               completion_date; payment_terms; service_method?: "CUSTOMER_TO_PRO"|"PRO_TO_CUSTOMER"|"EITHER"|"REMOTE";
               milestones?: { title; percent }[]; valid_until? }
Quote = { id; conversation_id; service_request_id: string | null; professional_id; customer_id; version;
          status: "PENDING"|"ACCEPTED"|"REJECTED"|"SUPERSEDED"|"WITHDRAWN";
          title; description; labour_minor; materials_minor; total_minor; currency; completion_date;
          payment_terms; service_method; milestones; created_at; accepted_at: string | null; agreement_hash: string | null }
Booking = { id; quote_id; agreement_id; agreement_hash; conversation_id; customer_id; professional_id; title;
            address: string | null; status: BookingStatus; amount_minor; currency; created_at;
            escrow_id: string | null; completion: Completion | null; dispute_id: string | null; review_id: string | null;
            cancellation_request: CancellationRequest | null; timeline: TimelineEvent[] }
BookingStatus = "PENDING_PAYMENT"|"FUNDED"|"IN_PROGRESS"|"COMPLETION_SUBMITTED"|"COMPLETED"
              | "DISPUTED"|"CANCELLED"|"REFUNDED"|"RESOLVED"
TimelineEvent = { at; label; actor: "CUSTOMER"|"PROFESSIONAL"|"SYSTEM"|"CHAIN"|"ADMIN" }
BookingBundle = { booking; quote; escrow: Escrow | null; professional; customer: PublicUser;
                  dispute: Dispute | null; review: Review | null; allowed_actions: AllowedAction[] }
AllowedAction = "FUND"|"CANCEL"|"START"|"SUBMIT_COMPLETION"|"APPROVE_RELEASE"|"REFUND"|"EXTEND_DEADLINE"
              | "REQUEST_CANCELLATION"|"DECLINE_CANCELLATION"|"OPEN_DISPUTE"|"CONCEDE_RELEASE"|"CONCEDE_REFUND"|"REVIEW"
```

- `total_minor` is computed by the server (`labour_minor + materials_minor`). Do not send it.
- **Quotes are never edited.** A new `POST /quotes` creates a new version and supersedes the old one. An accepted quote and its agreement are immutable.
- Render booking buttons from `allowed_actions`.

## 8. Wallets — Issue 5

| Method | Path | Body → Response |
|---|---|---|
| POST | `/wallets/challenge` | `{address}` → `{message, nonce, expires_at}` |
| POST | `/wallets` | `{address, message, signature}` → `User` |
| GET | `/wallets` | `Wallet[]` = `{id, address, network: "TESTNET", verified_at, is_primary, account_exists, has_escrow_trustline}` |
| DELETE | `/wallets/{id}` | `204` (blocked while the wallet is party to an active escrow) |

Flow:

1. Freighter `requestAccess()`, and check the network passphrase.
2. `POST /wallets/challenge`.
3. `signMessage(message)`; send the base64 signature unchanged.
4. `POST /wallets`.

Both parties need a verified wallet before funding.

## 9. Escrow and payments — Issues 6 and 7

Every chain action is **prepare → sign in Freighter → submit**. Keep polling `GET /bookings/{id}` while `escrow.reconciliation === "PENDING_CONFIRMATION"`.

| Action | Signer | Prepare → `{…, unsigned_xdr}` | Submit `{signed_xdr}` | Booking after confirmation |
|---|---|---|---|---|
| Fund 💰 | customer | `POST /bookings/{id}/escrow {customer_wallet}` | `POST /escrows/{id}/funding` | `FUNDED` |
| Submit completion 💰 | professional | `POST /bookings/{id}/completion {notes, checklist, photo_file_ids}` | `POST /bookings/{id}/completion/submit` | `COMPLETION_SUBMITTED` |
| Approve and release, or concede 💰 | customer | `POST /escrows/{id}/release {}` | `POST /escrows/{id}/release {signed_xdr}` | `COMPLETED` |
| Refund, accept cancellation, or concede 💰 | professional | `POST /escrows/{id}/refund {}` | `POST /escrows/{id}/refund {signed_xdr}` | `REFUNDED` |
| Extend deadline 💰 | customer | `POST /escrows/{id}/extend {new_refund_after}` | `POST /escrows/{id}/extend {signed_xdr}` | unchanged |
| Open dispute 💰 | either party | `POST /escrows/{id}/disputes {reason, details}` → `{dispute, escrow, unsigned_xdr}` | `POST /disputes/{id}/lock` | `DISPUTED` |
| Resolve 💰 | admin (arbiter wallet) | `POST /disputes/{id}/resolve {outcome, split_bps_to_professional?, note}` | `POST /disputes/{id}/resolve {signed_xdr}` | `COMPLETED` / `REFUNDED` / `RESOLVED` |
| Timeout | nobody (keeper) | — | — | `REFUNDED` (deadline passed) or `COMPLETED` (auto-release) |

Sign with `signTransaction(unsigned_xdr, { networkPassphrase: "Test SDF Network ; September 2015", address })`.

- A modified transaction is rejected with `400 TX_MISMATCH`.
- A stale preparation (over ~5 min, or a sequence change) fails with `409 TX_EXPIRED`. Prepare again.

```ts
Asset = { code: "USDC"; issuer: string; sac_contract_id: string; decimals: 7 }
Escrow = { id; booking_id; contract_id; escrow_id_hex;
           state: "CREATED"|"FUNDED"|"COMPLETION_SUBMITTED"|"DISPUTED"|"RELEASED"|"REFUNDED"|"RESOLVED";
           asset: Asset; asset_amount: string;
           fiat: { amount_minor: number; currency: "NGN"|"GHS" };
           fx: { rate: string; base: "USDC"; quote: "NGN"|"GHS"; source: "DEMO_FIXED_RATE"; is_demo_rate: boolean; locked_at: string };
           fee_stroops: string | null; customer_wallet; professional_wallet;
           refund_after: number; review_deadline: number | null; disputed_at: number | null;
           reconciliation: "AWAITING_SIGNATURE"|"PENDING_CONFIRMATION"|"CONFIRMED"|"FAILED";
           failure_reason: string | null; settled_by: "CUSTOMER"|"PROFESSIONAL"|"ARBITER"|"TIMEOUT" | null;
           professional_payout: string | null; customer_refund: string | null;
           transactions: EscrowTransaction[]; created_at }
EscrowTransaction = { kind: "FUND"|"SUBMIT_COMPLETION"|"RELEASE"|"REFUND"|"EXTEND"|"DISPUTE"|"RESOLVE"|"FINALIZE";
                      hash; ledger: number | null; at; status: "PENDING"|"CONFIRMED"|"FAILED"|"EXPIRED"; explorer_url }
Receipt = { id; number; kind: "FUNDING"|"RELEASE"|"REFUND"|"RESOLUTION"; booking_id;
            asset: Asset; asset_amount: string; fiat: { amount_minor; currency };
            fx: { rate; source; is_demo_rate: boolean }; tx_hash; ledger; issued_at; payload_hash }
```

`GET /escrows/{id}` → `Escrow`. `GET /bookings/{id}/receipts` → `Receipt[]`.

**Prerequisites:**

- The customer wallet exists, holds XLM for fees, and has a USDC trustline and balance.
- The professional wallet exists with a USDC trustline.
- `GET /wallets` reports `account_exists` and `has_escrow_trustline`.

**Deadlines:**

- Show `refund_after` and `review_deadline` as countdowns. These are the policies the contract enforces (STELLAR_ESCROW_DESIGN §4).
- Disputes have **no on-chain deadline**. Show the dispute's `sla` dates instead.

**Demo rate:** while `fx.is_demo_rate` is `true`, label the rate and every converted amount **"Demo rate — testnet only"**.

## 10. Completion, disputes, reviews — Issues 6 and 7

| Method | Path | Who | Body → Response |
|---|---|---|---|
| POST | `/disputes/{id}/evidence` | party / admin | `{note, file_id?}` |
| GET | `/disputes/{id}` | party / admin | `Dispute` |
| GET | `/admin/disputes` | admin | `status?` → `DisputeBundle[]` |
| POST | `/bookings/{id}/reviews` | customer | `{ratings: {quality, punctuality, communication, professionalism, value}, comment}` → `201 Review` |
| GET | `/professionals/{id}/reviews` | public | `Review[]` |
| POST | `/reviews/{id}/response` | professional | `{body}` |
| POST | `/reviews/{id}/report` | authenticated | `{reason, details?}` |
| POST | `/admin/reviews/{id}/moderate` | admin | `{action: "HIDE"\|"RESTORE"\|"REMOVE", reason}` |

```ts
Dispute = { id; booking_id; escrow_id; opened_by; reason: "INCOMPLETE"|"DAMAGED"|"NO_SHOW"|"PRICE_CHANGED"|"QUALITY"|"OTHER";
            details; status: "OPEN"|"UNDER_REVIEW"|"AWAITING_SETTLEMENT"|"RESOLVED"|"CLOSED"; opened_at;
            outcome: "RELEASE"|"REFUND"|"SPLIT"|"CONCEDED_RELEASE"|"CONCEDED_REFUND" | null;
            sla: { evidence_closes_at: string; decision_due_at: string; escalation_level: number; escalated_at: string | null };
            split_bps_to_professional: number | null; resolution_note: string | null; resolved_at: string | null;
            evidence: DisputeEvidence[] }
Review = { id; booking_id; professional_id; customer_id; customer_name; job_title;
           ratings: { quality; punctuality; communication; professionalism; value }; overall: number;
           comment; status: "PUBLISHED"|"HIDDEN"|"REMOVED"; created_at; response: { body; created_at } | null }
```

Reviews are allowed on `COMPLETED` or `RESOLVED` bookings, by the booking's customer, within 30 days, once per booking. Ratings are integers 1–5; `overall` is the mean (one decimal).

## 11. Notifications and admin — Issue 8

| Method | Path | Response |
|---|---|---|
| GET | `/notifications` | `unread?, limit, offset` → `AppNotification[]` = `{id, user_id, type, title, body, href, created_at, read_at}` |
| POST | `/notifications/read` | `{ids?}` → `204` |
| GET | `/notifications/unread-count` | `{count}` |
| GET | `/admin/users`, `/admin/bookings`, `/admin/escrows`, `/admin/service-requests`, `/admin/reports`, `/admin/audit-logs` | Filterable lists |
| GET | `/admin/ops/status` | Reconciler and RPC health |

## 12. Local development (backend)

```bash
cd backend && uv sync && cp .env.example .env
brew services start postgresql@16
uv run alembic upgrade head && uv run python -m app.cli seed
uv run python -m app.cli create-admin --email ops@unifix.local
uv run uvicorn app.main:app --reload --port 8000
cd ../frontend && NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev   # same-site on localhost
```

## 13. Frontend integration changes

Every difference between this contract and the frontend as committed (`41f07f4`).

- **F1–F18** are the differences identified in the first review. Items marked *(rev 2)* or *(rev 3)* changed later.
- **F19–F25** were added in revision 2.
- **F26** was added in revision 3.

Nothing here affects demo mode (`src/lib/api/demo.ts`).

| # | Area | Frontend today (file:line) | Required change | Issue |
|---|---|---|---|---|
| F1 | Base URL | `NEXT_PUBLIC_API_URL=http://localhost:8000` (README) | Append `/api/v1` | 1 |
| F2 | Session tokens *(rev 2)* | Token in `localStorage` under `handi-token` (`lib/api/live.ts:11,24,69,77,81`) | Remove localStorage. Keep `access_token` in memory. Call `/auth/refresh` on app load. Use `credentials: "include"` and `X-CSRF-Protection: 1` on login/register/refresh/logout. Single-flight refresh on 401 (Web Locks). Retry on `409 REFRESH_RACE`. Deploy same-site (§1) | 1 |
| F3 | Idempotency keys | New key per call (`live.ts:30–39`) | One key per user action, reused on retry | 3 |
| F4 | Categories | Hardcoded `CategoryId` union of 8 trades (`lib/types.ts:8`) | Load `GET /categories`; treat slugs as data | 2 |
| F5 | Campus | Not modelled | Optional `campus_id` at sign-up and in profile; `campus` filter in discovery | 2 |
| F6 | Portfolio | `{caption, tone}` (`types.ts:45`) | `{title, caption, image_url, category_id}` | 2 |
| F7 | Distance *(rev 2)* | `distanceKm: number` (`types.ts:58`) | `distance_km: number \| null` | 2 |
| F8 | Attachments and evidence photos | base64 `dataUrl` in JSON (`types.ts:108,168`) | Upload via `POST /uploads`; send `attachment_file_id` / `photo_file_ids`; display `FileRef.signed_url` | 4, 6 |
| F9 | System messages | `senderId: string` (`types.ts:104`) | `sender_id: string \| null` (null = system) | 4 |
| F10 | Booking actions | Client-side `nextStep()` (`lib/booking.ts:4`) | Render from `allowed_actions` | 3 |
| F11 | Booking statuses | 7 values | Add `REFUNDED`, `RESOLVED` | 3 |
| F12 | Escrow state *(rev 2)* | 5 states; `simulated` flag (`types.ts:196`) | Add `COMPLETION_SUBMITTED`, `RESOLVED`; new tx kinds (`SUBMIT_COMPLETION`, `EXTEND`, `DISPUTE`, `RESOLVE`, `FINALIZE`) and `EXPIRED` status; remove `simulated` | 6 |
| F13 | Open dispute | One call → `Dispute` | Prepare → sign → `POST /disputes/{id}/lock` | 7 |
| F14 | Resolve dispute | One admin call | Prepare → admin signs with the arbiter wallet → submit; `split_bps_to_professional` (0–10000) replaces `splitPercentToProfessional` | 7 |
| F15 | Refund | None | Professional "cancel and refund" via `/escrows/{id}/refund` (also used to accept a cancellation request or concede a dispute) | 6 |
| F16 | Reviews | `ratings` only | Request unchanged; response adds `overall`, `status` | 7 |
| F17 | Milestones | Percent milestones in quotes | Single payment: show milestones as work steps, not payment tranches | 3 |
| F18 | Email flows | No screens | Verify-email and password-reset screens (`/auth/verify-email/*`, `/auth/password-reset/*`) | 1 |
| F19 | Field naming *(new)* | camelCase types (`types.ts`, `contract.ts`) with some snake_case bodies (`live.ts:108,117,118,122,134`) | **All fields are snake_case**, requests and responses. Query params too: `min_rating`, `verified_only`. Unknown camelCase fields return 422. Suggest one mapping layer in `live.ts`, or snake_case types | 1–8 |
| F20 | Enum values *(new)* | Lowercase values: `Role` (`types.ts:4`), `Availability` with `"this-week"` (`types.ts:30`), `MessageKind` (`types.ts:99`), timeline `actor`, sort values | `UPPER_SNAKE_CASE`: `CUSTOMER`, `THIS_WEEK`, `TEXT`, `BEST`… | 1–8 |
| F21 | WebSocket auth *(new)* | Access token in the URL (`live.ts:146`) | `POST /ws/tickets` before each (re)connect, then `?ticket=`; handle close codes `4000`/`4401` with a new ticket | 4 |
| F22 | Money fields *(new)* | Floats: `startingPrice`, `labour`, `materials`, `total` (`types.ts:67,129`), escrow `amount`, `localAmount`, `rate`, `networkFee` (`types.ts:206–210`) | Fiat: `*_minor` integers + `currency`. Escrow: `asset_amount` string + `asset` object, `fiat {amount_minor, currency}`, `fx {rate,…}` (string rate), `fee_stroops` string. Format with integer or BigInt math | 2, 3, 6 |
| F23 | Completion signature *(new)* | `submitCompletion` is a single call | Prepare (evidence) → professional signs → `POST /bookings/{id}/completion/submit` | 6 |
| F24 | Deadlines and cancellation *(new; rev 3)* | None | Show `refund_after` / `review_deadline` countdowns and dispute `sla` dates (disputes have no on-chain deadline). Actions: extend deadline (customer), cancellation request and decline, concede release or refund during a dispute (each signed by the conceding party's wallet) | 6, 7 |
| F25 | Agreement proof *(new, optional)* | `agreementHash` displayed only | Optional "verify" view using `GET /bookings/{id}/agreement` | 3, 6 |
| F26 | Demo FX rate label *(new, rev 3)* | Rate and local amount shown without qualification | When `fx.is_demo_rate` is true, label the rate and converted amounts "Demo rate — testnet only" (booking, fund panel, receipt) | 6 |

**Production domains (D4a, provisional):** the cookie design requires the frontend and API to be same-site. The actual production domains will be agreed between Ladipo and Victor before Issue 8's deployment work.
